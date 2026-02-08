"""
GMM-HMM 训练脚本 - SOL/USDT 5分钟版本

用于训练隐马尔可夫模型，识别市场的5种状态：
  State 0: 大跌 (Huge Drop) - 极负动量，高波动，高量
  State 1: 小跌 (Small Drop) - 弱负动量，低波动
  State 2: 震荡 (Volatility) - 动量接近0，均值回归特性强
  State 3: 小涨 (Small Rise) - 弱正动量，低波动
  State 4: 大涨 (Huge Rise) - 极正动量，高波动，高量

特征矩阵(12维):
  1. 相对成交量 Vol/MA(Vol,96)
  2. 对数动量 (1,10,50,96) - 4个特征
  3. 滚动标准差 (5,50,96) - 3个特征
  4. 归一化MACD/Close
  5. 价格与布林带中轨距离
  6. 二值化SuperTrend方向
  7. K与D差值 (KDJ)
"""

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
import joblib

# 设置日志格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# 1. 配置区域
# ==========================================
SYMBOL = 'SOL/USDT'
TIMEFRAME = '5m'
LIMIT = 8640  # 5分钟K线数量
N_CLUSTERS = 5  # 隐状态数量 (Hidden States)
N_MIX = 2  # 每个状态由几个高斯分布混合

# 特征参数
MOMENTUM_WINDOWS = [1, 10, 50, 96]
VOLATILITY_WINDOWS = [5, 50, 96]
VOL_MA_PERIOD = 96
BB_PERIOD = 20
BB_STD_MULT = 2.0
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ST_ATR_PERIOD = 10
ST_MULTIPLIER = 3.0
KDJ_K_PERIOD = 9
KDJ_D_PERIOD = 3
KDJ_J_SMOOTH = 3

WARMUP = 100

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
# 3. 技术指标计算
# ==========================================
def calc_atr(df, period=14):
    """计算ATR"""
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift()
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def calc_bollinger(df, period=20, std_mult=2.0):
    """计算布林带"""
    close = df['close']
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    band_width = upper - lower
    distance = (close - middle) / band_width.replace(0, np.nan)
    return distance.fillna(0)


def calc_supertrend(df, atr_period=10, multiplier=3.0):
    """计算SuperTrend"""
    high, low, close = df['high'], df['low'], df['close']
    atr = calc_atr(df, atr_period)
    hl2 = (high + low) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr
    
    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)
    supertrend.iloc[0] = upper_basic.iloc[0]
    direction.iloc[0] = -1
    
    for i in range(1, len(df)):
        if lower_basic.iloc[i] > supertrend.iloc[i-1] or close.iloc[i-1] < supertrend.iloc[i-1]:
            upper = upper_basic.iloc[i]
        else:
            upper = min(upper_basic.iloc[i], supertrend.iloc[i-1])
        
        if upper_basic.iloc[i] < supertrend.iloc[i-1] or close.iloc[i-1] > supertrend.iloc[i-1]:
            lower = lower_basic.iloc[i]
        else:
            lower = max(lower_basic.iloc[i], supertrend.iloc[i-1])
        
        if close.iloc[i] > supertrend.iloc[i-1]:
            supertrend.iloc[i] = lower
            direction.iloc[i] = 1
        else:
            supertrend.iloc[i] = upper
            direction.iloc[i] = -1
    
    return direction


def calc_macd_normalized(df, fast=12, slow=26, signal=9):
    """计算归一化MACD"""
    close = df['close']
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    normalized = macd / close.replace(0, np.nan)
    return normalized.fillna(0)


def calc_kdj_diff(df, k_period=9, d_period=3, j_smooth=3):
    """计算K-D差值"""
    high, low, close = df['high'], df['low'], df['close']
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-9) * 100
    k = rsv.ewm(com=d_period - 1, adjust=False).mean()
    d = k.ewm(com=j_smooth - 1, adjust=False).mean()
    return k - d


# ==========================================
# 4. 特征工程
# ==========================================
def calculate_features(df):
    """计算12维HMM特征矩阵"""
    data = df.copy()
    feature_cols = []

    # 1. 相对成交量 Vol/MA(Vol,96)
    vol_ma = data['volume'].rolling(window=VOL_MA_PERIOD).mean()
    data['relative_volume'] = data['volume'] / (vol_ma + 1e-9)
    feature_cols.append('relative_volume')

    # 2. 对数动量 (1,10,50,96)
    for t in MOMENTUM_WINDOWS:
        col_name = f'log_mom_{t}'
        data[col_name] = np.log(data['close'] / data['close'].shift(t))
        feature_cols.append(col_name)

    # 3. 滚动标准差 (5,50,96)
    data['log_ret'] = np.log(data['close'] / data['close'].shift(1))
    for t in VOLATILITY_WINDOWS:
        col_name = f'vol_{t}'
        data[col_name] = data['log_ret'].rolling(window=t).std()
        feature_cols.append(col_name)

    # 4. 归一化MACD/Close
    data['macd_normalized'] = calc_macd_normalized(data, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    feature_cols.append('macd_normalized')

    # 5. 布林带距离
    data['bb_distance'] = calc_bollinger(data, BB_PERIOD, BB_STD_MULT)
    feature_cols.append('bb_distance')

    # 6. SuperTrend方向 (二值化)
    data['supertrend_direction'] = calc_supertrend(data, ST_ATR_PERIOD, ST_MULTIPLIER)
    feature_cols.append('supertrend_direction')

    # 7. K-D差值
    data['k_minus_d'] = calc_kdj_diff(data, KDJ_K_PERIOD, KDJ_D_PERIOD, KDJ_J_SMOOTH)
    feature_cols.append('k_minus_d')

    original_len = len(data)
    data.dropna(inplace=True)
    logger.info(f"特征计算完成，移除 NaN: {original_len - len(data)}，剩余: {len(data)}")
    
    return data, feature_cols


# ==========================================
# 5. GMM-HMM 核心逻辑
# ==========================================
def run_hmm_analysis(df, feature_cols, n_components, n_mix):
    logger.info(f"正在训练 GMM-HMM (States={n_components}, Mixtures={n_mix})...")

    # 1. 数据准备
    X = df[feature_cols].values
    
    # 数据清洗：替换 NaN 和 Inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    
    # 异常值裁剪 (防止极端值导致协方差计算问题)
    X = np.clip(X, -10, 10)
    
    # 过滤低方差特征 (防止协方差奇异)
    feature_variances = np.var(X, axis=0)
    valid_features = feature_variances > 1e-6
    
    if not all(valid_features):
        removed = [feature_cols[i] for i in range(len(feature_cols)) if not valid_features[i]]
        logger.warning(f"⚠️ 移除低方差特征: {removed}")
        X = X[:, valid_features]
        feature_cols_filtered = [f for i, f in enumerate(feature_cols) if valid_features[i]]
    else:
        feature_cols_filtered = feature_cols
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 再次检查缩放后的数据
    X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)
    
    # 添加微小噪声防止完全相同的值
    X_scaled += np.random.normal(0, 1e-6, X_scaled.shape)

    # 2. 使用 GaussianHMM (比 GMMHMM 更稳定)
    from hmmlearn.hmm import GaussianHMM
    logger.info("使用 GaussianHMM 进行稳定训练...")
    model = GaussianHMM(n_components=n_components, covariance_type='diag', 
                        n_iter=1000, random_state=42)
    model.fit(X_scaled)

    # 3. 预测状态
    hidden_states = model.predict(X_scaled)

    # --- 状态重排序逻辑 (按动量均值排序) ---
    df['temp_state'] = hidden_states
    # 使用第一个动量特征(log_mom_1)作为排序依据
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

    # 5. 保存结果
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # A. 保存 CSV
    backtest_centroids_path = os.path.join(os.path.dirname(__file__), 'centroids_hmm.csv')
    cluster_means.to_csv(backtest_centroids_path)
    logger.info(f"HMM 状态特征均值已保存: {backtest_centroids_path}")

    # B. 保存模型包 .pkl
    model_filename = f'hmm_strategy_{timestamp}.pkl'
    model_path = os.path.join(os.path.dirname(__file__), model_filename)

    strategy_bundle = {
        "model": model,
        "scaler": scaler,
        "state_map": state_map,
        "feature_cols": feature_cols,
        "n_clusters": n_components,
        "n_mix": n_mix,
        "timestamp": timestamp,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME
    }

    joblib.dump(strategy_bundle, model_path)
    logger.info(f"🔥🔥🔥 实盘策略模型包已保存: {model_path}")

    # 同步到 core 目录
    core_dir = os.path.join(os.path.dirname(__file__), '..', 'core')
    if os.path.exists(core_dir):
        core_csv_path = os.path.join(core_dir, 'centroids_hmm.csv')
        cluster_means.to_csv(core_csv_path)
        # 使用 sol_hmm_latest.pkl 作为固定文件名
        core_pkl_path = os.path.join(core_dir, 'sol_hmm_latest.pkl')
        joblib.dump(strategy_bundle, core_pkl_path)
        logger.info(f"模型已同步到 Core 目录: {core_pkl_path}")

    return df, stats, cluster_means, sorted_transmat


# ==========================================
# 6. 可视化
# ==========================================
def plot_results_hmm(df, transition_matrix, n_clusters, feature_cols):
    plt.style.use('dark_background')
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig = plt.figure(figsize=(18, 12))
    gs = fig.add_gridspec(2, 2)

    # --- 图 1: 价格路径 ---
    ax1 = fig.add_subplot(gs[0, :])
    cmap = plt.get_cmap('RdYlGn', n_clusters)
    ax1.plot(df.index, df['close'], color='white', alpha=0.1, linewidth=1, label='Price')
    scatter = ax1.scatter(df.index, df['close'], c=df['cluster'], cmap=cmap, s=10, alpha=0.8, edgecolors='none')
    cbar = plt.colorbar(scatter, ax=ax1, ticks=range(n_clusters))
    cbar.set_label('Market State (0=大跌, 4=大涨)')
    ax1.set_title(f'SOL/USDT HMM Market States - {TIMEFRAME}', fontsize=14)
    ax1.grid(True, alpha=0.15)

    # --- 图 2: 特征热力图 ---
    ax2 = fig.add_subplot(gs[1, 0])
    cluster_means = df.groupby('cluster')[feature_cols].mean()
    sns.heatmap(cluster_means.T, annot=True, cmap='vlag', center=0.0, fmt=".3f", ax=ax2)
    ax2.set_title('State Feature Means (Centroids)')

    # --- 图 3: 转移矩阵 ---
    ax3 = fig.add_subplot(gs[1, 1])
    state_labels = ['0:大跌', '1:小跌', '2:震荡', '3:小涨', '4:大涨']
    sns.heatmap(transition_matrix, annot=True, cmap='viridis', fmt=".2f", ax=ax3,
                xticklabels=state_labels, yticklabels=state_labels)
    ax3.set_title('HMM Transition Probability')
    ax3.set_ylabel('Current State')
    ax3.set_xlabel('Next State')

    plt.tight_layout()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    plot_path = os.path.join(os.path.dirname(__file__), f'hmm_{timestamp}.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    logger.info(f"图表已保存: {plot_path}")
    plt.show()


# ==========================================
# 7. 主程序
# ==========================================
def main():
    # 1. 获取数据
    df = fetch_binance_data(SYMBOL, TIMEFRAME, LIMIT, WARMUP, PROXIES)
    if df.empty: return

    # 2. 计算特征
    df_features, feature_list = calculate_features(df)

    # 3. 执行 GMM-HMM 分析
    df_clustered, stats, means, trans_matrix = run_hmm_analysis(df_features, feature_list, N_CLUSTERS, N_MIX)

    logger.info("--- 状态分布统计 ---")
    logger.info(f"\n{stats}")
    logger.info("--- 状态特征均值 (已排序: 0=大跌, 4=大涨) ---")
    logger.info(f"\n{means}")

    # 4. 绘图
    plot_results_hmm(df_clustered, trans_matrix, N_CLUSTERS, feature_list)


if __name__ == "__main__":
    main()