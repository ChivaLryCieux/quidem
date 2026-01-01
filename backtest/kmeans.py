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

logger = logging.getLogger(__name__)

# ==========================================
# 1. 配置区域 (User Configuration)
# ==========================================
SYMBOL = 'XRP/USDT'  # 交易对
TIMEFRAME = '1m'  # K线周期, 主要分析15m和1h
LIMIT = 10000  # 拉取K线数量
WINDOWS = [5, 10, 25, 50]  # 特征窗口 T
N_CLUSTERS = 5  # 聚类数量 K
# 预热缓冲：根据最大窗口动态计算，或者手动设置一个较大的值
WARMUP = max(WINDOWS) + 10

# 代理设置
PROXY_URL = 'http://127.0.0.1:7897'
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
        df = df[~df.index.duplicated(keep='first')]
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

    # 计算单周期对数收益率 (用于波动率计算)
    # log_ret 本身就是 T=1 时的对数动量
    data['log_ret'] = np.log(data['close'] / data['close'].shift(1))

    for t in windows:
        # 1. 对数动量 (Log Momentum): ln(P_t / P_(t-T))
        # 这等价于 ln(P_t) - ln(P_(t-T))，表示 T 周期内的连续复利收益率
        mom_col = f'log_mom_{t}'
        data[mom_col] = np.log(data['close'] / data['close'].shift(t))

        # 2. 波动率 (Volatility): 使用对数收益率的滚动标准差
        vol_col = f'vol_{t}'
        data[vol_col] = data['log_ret'].rolling(window=t).std()

        feature_cols.extend([mom_col, vol_col])

    data.dropna(inplace=True)
    return data, feature_cols


# ==========================================
# 4. 聚类与分析 (Clustering & Analysis)
# ==========================================
def run_clustering_analysis(df, feature_cols, n_clusters):
    logger.info("正在执行 K-Means 聚类...")
    X = df[feature_cols].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_scaled)

    stats = df['cluster'].value_counts().sort_index().to_frame(name='count')
    stats['percentage'] = stats['count'] / len(df) * 100
    cluster_means = df.groupby('cluster')[feature_cols].mean()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    
    backtest_centroids_path = os.path.join(os.path.dirname(__file__), 'centroids.csv')
    cluster_means.to_csv(backtest_centroids_path)
    logger.info(f"聚类质心已保存到: {backtest_centroids_path}")
    
    core_centroids_path = os.path.join(os.path.dirname(__file__), '..', 'core', 'centroids.csv')
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
    transition_probs = transition_counts.div(transition_counts.sum(axis=1), axis=0)
    return transition_probs


# ==========================================
# 6. 可视化 (Visualization)
# ==========================================
def plot_results_custom(df, transition_probs, n_clusters):
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 2)

    # --- 图 1: 价格路径 ---
    ax1 = fig.add_subplot(gs[0, :])
    cmap = plt.get_cmap('tab10')
    ax1.plot(df.index, df['close'], color='white', alpha=0.1, linewidth=1, label='Price')
    for i in range(n_clusters):
        mask = df['cluster'] == i
        ax1.scatter(df.index[mask], df['close'][mask],
                    s=15, color=cmap(i), label=f'Cluster {i}', alpha=0.9, edgecolors='none')
    ax1.set_title(f'Price Action by Cluster (TIMEFRAME: {TIMEFRAME}, K-LIMIT: {LIMIT})', fontsize=14)
    ax1.legend(loc='upper left', frameon=True, facecolor='black')
    ax1.grid(True, alpha=0.15)

    # --- 图 2: 特征热力图 ---
    ax2 = fig.add_subplot(gs[1, 0])
    # 1. 分别筛选出 mom_ 和 vol_ 开头的列
    mom_cols = df.columns[df.columns.str.contains('mom_')]
    vol_cols = df.columns[df.columns.str.contains('vol_')]
    # 2. 使用 np.r_ 按顺序连接两个列表
    feature_cols = np.r_[mom_cols, vol_cols]
    # 3. 转换为 Pandas Index 对象，以保持一致性
    feature_cols = pd.Index(feature_cols)
    cluster_means = df.groupby('cluster')[feature_cols].mean()

    # 因为对数动量均值通常接近0，这里使用 'vlag' (红蓝)
    # 并将 center 设置为 0，这样红色代表正收益，蓝色代表负收益
    sns.heatmap(cluster_means.T, annot=True, cmap='vlag', center=0.0,
                fmt=".4f", ax=ax2, cbar_kws={'label': 'Mean Feature Value'})
    ax2.set_title('Cluster Centroids (Log Momentum & Volatility)')

    # --- 图 3: 转移矩阵 ---
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
    df = fetch_binance_data(SYMBOL, TIMEFRAME, LIMIT, WARMUP, PROXIES)
    if df.empty: return

    df_features, feature_list = calculate_features(df, WINDOWS)
    logger.info("--- 特征计算完毕 (已启用对数动量) ---")

    df_clustered, stats, means = run_clustering_analysis(df_features, feature_list, N_CLUSTERS)
    logger.info("--- 聚类统计 ---")
    logger.info(f"\n{stats}")
    logger.info("--- 聚类中心 (对数动量) ---")
    logger.info(f"\n{means}")

    trans_matrix = calculate_transition_matrix(df_clustered, N_CLUSTERS)
    plot_results_custom(df_clustered, trans_matrix, N_CLUSTERS)


if __name__ == "__main__":
    main()