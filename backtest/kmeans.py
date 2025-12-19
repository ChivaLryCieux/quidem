import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import time

# ==========================================
# 1. 配置区域 (User Configuration)
# ==========================================
SYMBOL = 'XRP/USDT'  # 交易对
TIMEFRAME = '1h'  # K线周期，例如 15m, 1h, 4h, 1d
LIMIT = 10000  # 拉取K线数量
WINDOWS = [5, 10, 25, 50]  # 特征窗口 T
N_CLUSTERS = 5  # 聚类数量 K
WARMUP = 50  # 预热K线数量 (用于指标计算)

# 代理设置
PROXY_URL = 'http://127.0.0.1:7897'

PROXIES = {
    'http': PROXY_URL,
    'https': PROXY_URL,
}


# ==========================================
# 2. 数据获取 (Data Fetching) - 支持大额数量
# ==========================================
def fetch_binance_data(symbol, timeframe, limit, proxies):
    print(f"正在连接币安拉取 {symbol} {timeframe} 数据 (目标: {limit} 条)...")

    try:
        exchange = ccxt.binanceusdm({
            'enableRateLimit': True,
            'proxies': proxies,
            'options': {'defaultType': 'future'}
        })

        # 1. 计算起始时间 (since)
        # ccxt 的 parse_timeframe 返回的是秒，需要乘以 1000 变成毫秒
        duration_seconds = exchange.parse_timeframe(timeframe)
        duration_ms = duration_seconds * 1000

        # 当前时间 - (K线数量 * 单根K线时长) = 起始时间
        # 多预留一点 buffer (比如多 1-2 根的时间)，防止边界遗漏
        since = exchange.milliseconds() - (limit * duration_ms)

        all_ohlcv = []

        while len(all_ohlcv) < limit:
            # 计算本次还需要多少条，但不超过币安的单次最大限制 (1500)
            # 为了安全起见，我们设定单次请求 1000 或 1500
            fetch_limit = 1500

            try:
                # 使用 since 参数从特定时间点开始往后拉
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=fetch_limit)

                if not ohlcv:
                    print("未获取到更多数据，停止拉取。")
                    break

                # 将本次拉取的数据加入总列表
                all_ohlcv.extend(ohlcv)

                # 更新 since：取本次最后一根K线的时间 + 1个时间周期，作为下次拉取的起点
                last_timestamp = ohlcv[-1][0]
                since = last_timestamp + 1  # 或者 + duration_ms，但 +1ms 更通用防止覆盖

                print(f"已收集: {len(all_ohlcv)} / {limit} ...")

                # 防止请求过快 (虽然 enableRateLimit 会处理，但大循环加个小休眠更稳)
                if len(ohlcv) < fetch_limit:
                    # 如果这次拉取的不满 1500 条，说明已经拉到了最新的数据
                    break

            except Exception as loop_e:
                print(f"拉取循环中出错: {loop_e}")
                break

        # 2. 转换为 DataFrame
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        # 3. 去重与截取
        # 因为循环计算时间可能微小偏差，去重并只保留最后 limit 条
        df = df[~df.index.duplicated(keep='first')]
        df = df.tail(limit)

        print(f"成功拉取并合并 {len(df)} 条K线数据")
        return df

    except Exception as e:
        print(f"Error fetching data: {e}")
        return pd.DataFrame()


# ==========================================
# 3. 特征工程 (Feature Engineering)
# ==========================================
def calculate_features(df, windows):
    data = df.copy()
    feature_cols = []

    # 计算对数收益率 (用于波动率计算)
    data['log_ret'] = np.log(data['close'] / data['close'].shift(1))

    for t in windows:
        # 1. 动量 (Momentum): P_t / P_(t-T)
        mom_col = f'mom_{t}'
        data[mom_col] = data['close'] / data['close'].shift(t)

        # 2. 波动率 (Volatility):
        # 注: 对于 T=5,10 这样的小窗口，EGARCH 模型无法收敛且极其耗时。
        # 业界通用的短窗口波动率计算使用的是滚动标准差 (Rolling Std Dev)。
        vol_col = f'vol_{t}'
        data[vol_col] = data['log_ret'].rolling(window=t).std()

        feature_cols.extend([mom_col, vol_col])

    # 去除 NaN 值 (预热阶段产生的数据缺失)
    data.dropna(inplace=True)

    return data, feature_cols


# ==========================================
# 4. 聚类与分析 (Clustering & Analysis)
# ==========================================
def run_clustering_analysis(df, feature_cols, n_clusters):
    print("正在执行 K-Means 聚类...")

    # 提取特征矩阵
    X = df[feature_cols].values

    # 标准化数据 (StandardScaler) - 对于 K-Means 至关重要
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 执行聚类
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_scaled)

    # --- 统计 1: 每类的数量和占比 ---
    stats = df['cluster'].value_counts().sort_index().to_frame(name='count')
    stats['percentage'] = stats['count'] / len(df) * 100

    # --- 统计 2: 每类的特征均值 ---
    # 为了便于观察，我们反归一化或者直接看原始值的均值
    cluster_means = df.groupby('cluster')[feature_cols].mean()

    return df, stats, cluster_means


# ==========================================
# 5. 马尔可夫链 (Markov Chain)
# ==========================================
def calculate_transition_matrix(df, n_clusters):
    print("正在计算马尔可夫转移矩阵...")

    # 创建当前状态和下一时刻状态的列
    df['next_cluster'] = df['cluster'].shift(-1)

    # 移除最后一行 (因为它没有下一个状态)
    valid_transitions = df.dropna(subset=['next_cluster'])

    # 创建交叉表 (Transition Count Matrix)
    transition_counts = pd.crosstab(
        valid_transitions['cluster'],
        valid_transitions['next_cluster'].astype(int)
    )

    # 归一化为概率 (Transition Probability Matrix)
    # div(axis=0) 表示按行求和并相除
    transition_probs = transition_counts.div(transition_counts.sum(axis=1), axis=0)

    return transition_probs


# ==========================================
# 6. 可视化 (Visualization)
# ==========================================
def plot_results_custom(df, transition_probs, n_clusters):
    """
    可视化函数，使用了专业的 'tab10' 配色方案
    """
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 2)

    # --- 图 1: 价格折线图 ---
    ax1 = fig.add_subplot(gs[0, :])

    # 使用 'tab10' 离散色盘，它专门用于分类数据，颜色更清晰
    # tab10 包含: 蓝, 橙, 绿, 红, 紫, 棕, 粉, 灰, 黄, 青
    cmap = plt.get_cmap('tab10')

    # 绘制灰色背景线
    ax1.plot(df.index, df['close'], color='white', alpha=0.1, linewidth=1, label='Price Path')

    # 循环绘制每一类
    for i in range(n_clusters):
        mask = df['cluster'] == i
        # cmap(i) 会自动从 tab10 中取出第 i 个颜色
        ax1.scatter(df.index[mask], df['close'][mask],
                    s=15, color=cmap(i), label=f'Cluster {i}', alpha=0.9, edgecolors='none')

    ax1.set_title(f'Price Action by Cluster (TIMEFRAME: {TIMEFRAME}, K-LIMIT:{LIMIT})', fontsize=14)
    ax1.set_ylabel('Price')
    ax1.legend(loc='upper left', frameon=True, facecolor='black')
    ax1.grid(True, alpha=0.15)

    # --- 图 2: 聚类特征热力图 ---
    ax2 = fig.add_subplot(gs[1, 0])
    # 筛选出特征列
    feature_cols = df.columns[df.columns.str.contains('mom_|vol_')]
    cluster_means = df.groupby('cluster')[feature_cols].mean()

    # 使用 diverging colormap (红蓝) 来显示特征的高低
    sns.heatmap(cluster_means.T, annot=True, cmap='vlag', center=1.0,
                fmt=".3f", ax=ax2, cbar_kws={'label': 'Feature Value'})
    ax2.set_title('Cluster Centroids (Mean Feature Values)')

    # --- 图 3: 马尔可夫转移矩阵 ---
    ax3 = fig.add_subplot(gs[1, 1])
    sns.heatmap(transition_probs, annot=True, cmap='viridis', fmt=".2f", ax=ax3)
    ax3.set_title('Probability of Switching Clusters (t -> t+1)')
    ax3.set_ylabel('Current Cluster')
    ax3.set_xlabel('Next Cluster')

    plt.tight_layout()
    plt.show()


# ==========================================
# 主程序
# ==========================================
def main():
    # 1. 获取数据
    df = fetch_binance_data(SYMBOL, TIMEFRAME, LIMIT, PROXIES)

    if df.empty:
        print("未获取到数据，请检查代理设置或网络。")
        return

    # 2. 计算特征
    df_features, feature_list = calculate_features(df, WINDOWS)

    print("\n--- 特征计算完毕 ---")
    print(f"保留数据行数: {len(df_features)}")
    print(f"特征列表: {feature_list}")

    # 3. K-Means 聚类
    df_clustered, stats, means = run_clustering_analysis(df_features, feature_list, N_CLUSTERS)

    print("\n--- 聚类统计 (Counts & Percentage) ---")
    print(stats)

    print("\n--- 聚类中心均值 (Centroids) ---")
    print(means)

    # 4. 马尔可夫链
    trans_matrix = calculate_transition_matrix(df_clustered, N_CLUSTERS)

    print("\n--- 马尔可夫转移矩阵 ---")
    print(trans_matrix)

    # 5. 可视化
    print("\n正在生成图表...")
    plot_results_custom(df_clustered, trans_matrix, N_CLUSTERS)


if __name__ == "__main__":
    main()