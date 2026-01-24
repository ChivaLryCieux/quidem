import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import os
import time
import logging

# 设置日志格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# 1. 配置区域 (User Configuration)
# ==========================================
SYMBOL = 'XRP/USDT'  # 交易对
TIMEFRAME = '15m'  # K线周期
LIMIT = 10000  # 拉取K线数量
# 修改点：更新了窗口列表，包含 1
WINDOWS = [1, 5, 15, 30, 50, 96]
N_CLUSTERS = 7  # 聚类数量 K
# 预热缓冲：确保最大的窗口有足够数据进行计算
WARMUP = max(WINDOWS) + 10

# 代理设置 (根据您的实际环境调整)
PROXY_URL = 'http://127.0.0.1:7890'
PROXIES = {
    'http': PROXY_URL,
    'https': PROXY_URL,
}


# ==========================================
# 2. 数据获取 (Data Fetching)
# ==========================================
def fetch_binance_data(symbol, timeframe, target_limit, warmup_buffer, proxies):
    total_fetch_size = target_limit + warmup_buffer
    logger.info(f"正在连接币安拉取 {symbol} {timeframe}...")
    logger.info(f"目标有效K线: {target_limit}, 预热缓冲: {warmup_buffer}, 总拉取: {total_fetch_size}")

    try:
        exchange = ccxt.binanceusdm({
            'enableRateLimit': True,
            'proxies': proxies,
            'options': {'defaultType': 'future'}
        })

        duration_seconds = exchange.parse_timeframe(timeframe)
        duration_ms = duration_seconds * 1000
        since = exchange.milliseconds() - (total_fetch_size * duration_ms)

        all_ohlcv = []
        while len(all_ohlcv) < total_fetch_size:
            fetch_limit = 1500
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=fetch_limit)
            if not ohlcv: break
            all_ohlcv.extend(ohlcv)
            last_timestamp = ohlcv[-1][0]
            since = last_timestamp + 1
            if len(ohlcv) < fetch_limit: break

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        # 去重
        df = df[~df.index.duplicated(keep='first')]
        # 截取所需长度
        df = df.tail(total_fetch_size)

        logger.info(f"成功拉取并合并 {len(df)} 条K线数据")
        return df

    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return pd.DataFrame()


# ==========================================
# 3. 特征工程 (Feature Engineering)
# ==========================================
def calculate_features(df, windows):
    data = df.copy()
    feature_cols = []

    # 基础对数收益率 (用于后续计算波动率)
    # log_ret 本身其实就是 T=1 的对数动量，但为了命名统一，下面循环中会再次生成 log_mom_1
    data['log_ret'] = np.log(data['close'] / data['close'].shift(1))

    for t in windows:
        # --- 1. 对数动量 (Log Momentum) ---
        # 即使是 T=1，动量也是存在的 (即当前K线收益率)
        mom_col = f'log_mom_{t}'
        data[mom_col] = np.log(data['close'] / data['close'].shift(t))
        feature_cols.append(mom_col)

        # --- 2. 波动率 (Volatility) ---
        # 修改点：必须判断 t > 1。
        # 因为 rolling(1).std() 也就是 1个数值的标准差，在 Pandas 中默认为 NaN (ddof=1)。
        # 如果包含 NaN，后续 dropna() 会删掉所有数据。
        if t > 1:
            vol_col = f'vol_{t}'
            data[vol_col] = data['log_ret'].rolling(window=t).std()
            feature_cols.append(vol_col)
        else:
            logger.debug(f"跳过 Window={t} 的波动率计算 (需要至少2个周期)")

    # 清除由于 shift 和 rolling 产生的 NaN
    original_len = len(data)
    data.dropna(inplace=True)
    dropped_len = original_len - len(data)
    logger.info(f"特征计算完成，移除了前 {dropped_len} 行 NaN 数据 (Warmup)")

    return data, feature_cols


# ==========================================
# 4. 聚类与分析 (Clustering & Analysis)
# ==========================================
def run_clustering_analysis(df, feature_cols, n_clusters):
    logger.info("正在执行 K-Means 聚类...")

    # 提取特征矩阵
    X = df[feature_cols].values

    # 标准化 (非常重要，尤其是当混合了不同时间窗口的特征时)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_scaled)

    # 统计每个簇的占比
    stats = df['cluster'].value_counts().sort_index().to_frame(name='count')
    stats['percentage'] = stats['count'] / len(df) * 100

    # 计算簇中心 (Centroids) 的均值，用于理解每个簇代表什么市场状态
    cluster_means = df.groupby('cluster')[feature_cols].mean()

    # 保存文件逻辑
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # 保存到当前目录
    backtest_centroids_path = os.path.join(os.path.dirname(__file__), 'centroids.csv')
    cluster_means.to_csv(backtest_centroids_path)
    logger.info(f"聚类质心已保存到: {backtest_centroids_path}")

    # 尝试保存到上一级 core 目录 (如果存在)
    core_dir = os.path.join(os.path.dirname(__file__), '..', 'core')
    if os.path.exists(core_dir):
        core_centroids_path = os.path.join(core_dir, 'centroids.csv')
        cluster_means.to_csv(core_centroids_path)
        logger.info(f"聚类质心已同步到: {core_centroids_path}")

    return df, stats, cluster_means


# ==========================================
# 5. 马尔可夫链 (Markov Chain)
# ==========================================
def calculate_transition_matrix(df, n_clusters):
    logger.info("正在计算马尔可夫转移矩阵...")
    df['next_cluster'] = df['cluster'].shift(-1)
    valid_transitions = df.dropna(subset=['next_cluster'])

    transition_counts = pd.crosstab(
        valid_transitions['cluster'],
        valid_transitions['next_cluster'].astype(int)
    )
    # 归一化：将频数转换为概率
    transition_probs = transition_counts.div(transition_counts.sum(axis=1), axis=0)
    return transition_probs


# ==========================================
# 6. 可视化 (Visualization)
# ==========================================
def plot_results_custom(df, transition_probs, n_clusters):
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 2)

    # --- 图 1: 价格路径 (Price Action) ---
    ax1 = fig.add_subplot(gs[0, :])
    cmap = plt.get_cmap('tab10')

    # 绘制灰色背景线
    ax1.plot(df.index, df['close'], color='white', alpha=0.1, linewidth=1, label='Price')

    # 绘制彩色点
    for i in range(n_clusters):
        mask = df['cluster'] == i
        if mask.any():
            ax1.scatter(df.index[mask], df['close'][mask],
                        s=15, color=cmap(i), label=f'Cluster {i}', alpha=0.9, edgecolors='none')

    ax1.set_title(f'Price Action by Cluster (TIMEFRAME: {TIMEFRAME}, Limit: {LIMIT})', fontsize=14)
    ax1.legend(loc='upper left', frameon=True, facecolor='black')
    ax1.grid(True, alpha=0.15)

    # --- 图 2: 特征热力图 (Feature Heatmap) ---
    ax2 = fig.add_subplot(gs[1, 0])

    # 动态筛选列名
    mom_cols = [c for c in df.columns if 'log_mom_' in c]
    vol_cols = [c for c in df.columns if 'vol_' in c]

    # 排序：按照窗口大小排序，为了热力图好看
    # 提取数字进行排序
    mom_cols.sort(key=lambda x: int(x.split('_')[-1]))
    vol_cols.sort(key=lambda x: int(x.split('_')[-1]))

    feature_cols_sorted = mom_cols + vol_cols

    cluster_means = df.groupby('cluster')[feature_cols_sorted].mean()

    # 使用 'vlag' 色阶 (红蓝)，Center=0。
    # 红色 = 正向动量/高波动，蓝色 = 负向动量/低波动
    sns.heatmap(cluster_means.T, annot=True, cmap='vlag', center=0.0,
                fmt=".4f", ax=ax2, cbar_kws={'label': 'Z-Score / Mean Value'})
    ax2.set_title('Cluster Centroids Features')

    # --- 图 3: 转移矩阵 (Transition Matrix) ---
    ax3 = fig.add_subplot(gs[1, 1])
    sns.heatmap(transition_probs, annot=True, cmap='viridis', fmt=".2f", ax=ax3)
    ax3.set_title('Transition Probability (t -> t+1)')
    ax3.set_ylabel('Current Cluster')
    ax3.set_xlabel('Next Cluster')

    plt.tight_layout()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    plot_path = os.path.join(os.path.dirname(__file__), f'kmeans_{timestamp}.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    logger.info(f"聚类分析图表已保存到: {plot_path}")
    plt.show()


# ==========================================
# 主程序
# ==========================================
def main():
    # 1. 获取数据
    df = fetch_binance_data(SYMBOL, TIMEFRAME, LIMIT, WARMUP, PROXIES)
    if df.empty: return

    # 2. 计算特征
    df_features, feature_list = calculate_features(df, WINDOWS)
    logger.info("--- 特征计算完毕 (对数动量 + 波动率) ---")
    logger.info(f"使用的特征列表: {feature_list}")

    # 3. 执行聚类
    df_clustered, stats, means = run_clustering_analysis(df_features, feature_list, N_CLUSTERS)
    logger.info("--- 聚类统计 ---")
    logger.info(f"\n{stats}")
    logger.info("--- 聚类中心 ---")
    logger.info(f"\n{means}")

    # 4. 计算马尔可夫转移矩阵
    trans_matrix = calculate_transition_matrix(df_clustered, N_CLUSTERS)

    # 5. 绘图
    plot_results_custom(df_clustered, trans_matrix, N_CLUSTERS)


if __name__ == "__main__":
    main()