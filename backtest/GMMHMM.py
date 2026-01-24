import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from hmmlearn.hmm import GMMHMM
from sklearn.preprocessing import StandardScaler
import os
import time
import logging
import joblib  # 用于保存模型

# 设置日志格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# 1. 配置区域
# ==========================================
SYMBOL = 'XRP/USDT'
TIMEFRAME = '15m'
LIMIT = 10000
WINDOWS = [1, 5, 15, 30, 50, 96]
N_CLUSTERS = 5  # 隐状态数量 (Hidden States)
N_MIX = 2  # 每个状态由几个高斯分布混合 (解决肥尾问题)
WARMUP = max(WINDOWS) + 10

PROXY_URL = 'http://127.0.0.1:7890'
PROXIES = {
    'http': PROXY_URL,
    'https': PROXY_URL,
}


# ==========================================
# 2. 数据获取
# ==========================================
def fetch_binance_data(symbol, timeframe, target_limit, warmup_buffer, proxies):
    total_fetch_size = target_limit + warmup_buffer
    logger.info(f"正在连接币安拉取 {symbol} {timeframe}...")

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
        logger.info(f"成功拉取 {len(df)} 条K线")
        return df

    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return pd.DataFrame()


# ==========================================
# 3. 特征工程
# ==========================================
def calculate_features(df, windows):
    data = df.copy()
    feature_cols = []

    # 基础收益率
    data['log_ret'] = np.log(data['close'] / data['close'].shift(1))

    for t in windows:
        mom_col = f'log_mom_{t}'
        data[mom_col] = np.log(data['close'] / data['close'].shift(t))
        feature_cols.append(mom_col)

        if t > 1:
            vol_col = f'vol_{t}'
            data[vol_col] = data['log_ret'].rolling(window=t).std()
            feature_cols.append(vol_col)

    original_len = len(data)
    data.dropna(inplace=True)
    logger.info(f"特征计算完成，移除 NaN: {original_len - len(data)}")
    return data, feature_cols


# ==========================================
# 4. GMM-HMM 核心逻辑
# ==========================================
def run_hmm_analysis(df, feature_cols, n_components, n_mix):
    logger.info(f"正在训练 GMM-HMM (States={n_components}, Mixtures={n_mix})...")

    # 1. 数据准备
    X = df[feature_cols].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 2. 训练 GMM-HMM 模型
    model = GMMHMM(n_components=n_components, n_mix=n_mix,
                   covariance_type='diag', n_iter=1000, random_state=42, verbose=False)
    model.fit(X_scaled)

    # 3. 预测状态
    hidden_states = model.predict(X_scaled)

    # --- 状态重排序逻辑 ---
    df['temp_state'] = hidden_states
    state_mom_means = df.groupby('temp_state')['log_mom_1'].mean()
    sorted_states = state_mom_means.sort_values().index
    state_map = {old_id: new_id for new_id, old_id in enumerate(sorted_states)}

    df['cluster'] = df['temp_state'].map(state_map)
    df.drop(columns=['temp_state'], inplace=True)

    # 重排转移矩阵
    P = np.zeros((n_components, n_components))
    for old_i, new_i in state_map.items():
        P[new_i, old_i] = 1
    sorted_transmat = P @ model.transmat_ @ P.T

    logger.info("模型训练与状态重排序完成。")

    # 4. 统计与质心计算
    stats = df['cluster'].value_counts().sort_index().to_frame(name='count')
    stats['percentage'] = stats['count'] / len(df) * 100
    cluster_means = df.groupby('cluster')[feature_cols].mean()

    # 5. 保存结果 (CSV 和 模型包)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # A. 保存 CSV
    backtest_centroids_path = os.path.join(os.path.dirname(__file__), 'centroids_hmm.csv')
    cluster_means.to_csv(backtest_centroids_path)
    logger.info(f"HMM 状态特征均值已保存: {backtest_centroids_path}")

    # B. 保存模型包 .pkl (给实盘程序用) -- 新增部分
    model_filename = f'hmm_strategy_{timestamp}.pkl'
    model_path = os.path.join(os.path.dirname(__file__), model_filename)

    strategy_bundle = {
        "model": model,  # 训练好的 HMM 模型 (包含几千个参数)
        "scaler": scaler,  # 训练好的标尺 (均值和方差)
        "state_map": state_map,  # 状态 ID 映射表
        "feature_cols": feature_cols,  # 特征列名
        "n_clusters": n_components,
        "n_mix": n_mix,
        "timestamp": timestamp
    }

    joblib.dump(strategy_bundle, model_path)
    logger.info(f"🔥🔥🔥 实盘策略模型包已保存: {model_path}")

    # 如果有 core 目录，也同步一份固定的名字方便读取
    core_dir = os.path.join(os.path.dirname(__file__), '..', 'core')
    if os.path.exists(core_dir):
        # 同步 CSV
        core_csv_path = os.path.join(core_dir, 'centroids_hmm.csv')
        cluster_means.to_csv(core_csv_path)
        # 同步模型 PKL (使用固定文件名 xrp_hmm_latest.pkl，方便实盘读取)
        core_pkl_path = os.path.join(core_dir, 'xrp_hmm_latest.pkl')
        joblib.dump(strategy_bundle, core_pkl_path)
        logger.info(f"模型已同步到 Core 目录: {core_pkl_path}")

    return df, stats, cluster_means, sorted_transmat


# ==========================================
# 5. 可视化
# ==========================================
def plot_results_hmm(df, transition_matrix, n_clusters):
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 2)

    # --- 图 1: 价格路径 ---
    ax1 = fig.add_subplot(gs[0, :])
    cmap = plt.get_cmap('RdYlGn', n_clusters)  # 使用红绿渐变，因为我们已经对状态排序了

    ax1.plot(df.index, df['close'], color='white', alpha=0.1, linewidth=1, label='Price')

    # 为了性能，不画所有点，只画状态切换段，或者降采样
    # 这里保持散点图逻辑，但建议在数据量大时改为着色线段
    scatter = ax1.scatter(df.index, df['close'], c=df['cluster'], cmap=cmap, s=10, alpha=0.8, edgecolors='none')

    cbar = plt.colorbar(scatter, ax=ax1, ticks=range(n_clusters))
    cbar.set_label('Market State (Sorted: Bear -> Bull)')

    ax1.set_title(f'HMM Market States (Sorted by Momentum) - {TIMEFRAME}', fontsize=14)
    ax1.grid(True, alpha=0.15)

    # --- 图 2: 特征热力图 ---
    ax2 = fig.add_subplot(gs[1, 0])
    mom_cols = sorted([c for c in df.columns if 'log_mom_' in c], key=lambda x: int(x.split('_')[-1]))
    vol_cols = sorted([c for c in df.columns if 'vol_' in c], key=lambda x: int(x.split('_')[-1]))
    feature_cols_sorted = mom_cols + vol_cols

    cluster_means = df.groupby('cluster')[feature_cols_sorted].mean()

    sns.heatmap(cluster_means.T, annot=True, cmap='vlag', center=0.0, fmt=".4f", ax=ax2)
    ax2.set_title('State Feature Means (Centroids)')

    # --- 图 3: 转移矩阵 (直接使用 HMM 学习到的概率) ---
    ax3 = fig.add_subplot(gs[1, 1])
    sns.heatmap(transition_matrix, annot=True, cmap='viridis', fmt=".2f", ax=ax3)
    ax3.set_title('HMM Learned Transition Probability')
    ax3.set_ylabel('Current State')
    ax3.set_xlabel('Next State')

    plt.tight_layout()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    plot_path = os.path.join(os.path.dirname(__file__), f'hmm_{timestamp}.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    logger.info(f"图表已保存: {plot_path}")
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

    # 3. 执行 GMM-HMM 分析
    # 注意：这里直接返回了整理好的转移矩阵，不需要再手动计算
    df_clustered, stats, means, trans_matrix = run_hmm_analysis(df_features, feature_list, N_CLUSTERS, N_MIX)

    logger.info("--- 状态分布统计 ---")
    logger.info(f"\n{stats}")
    logger.info("--- 状态特征均值 (已排序: 0=最弱, N=最强) ---")
    logger.info(f"\n{means}")

    # 4. 绘图
    plot_results_hmm(df_clustered, trans_matrix, N_CLUSTERS)


if __name__ == "__main__":
    main()