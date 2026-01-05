import numpy as np
import pandas as pd
import os
import sys
import logging

logger = logging.getLogger(__name__)

class KMeansClusterAnalyzer:
    def __init__(self, n_clusters=7):
        self.n_clusters = n_clusters
        # 更新窗口列表以匹配kmeans.py版本
        self.windows = [1, 5, 15, 30, 50, 96]
        self.feature_names = []
        # 生成特征名称列表
        for t in self.windows:
            self.feature_names.append(f'log_mom_{t}')
        for t in self.windows:
            if t > 1:  # 只在大于1的窗口添加波动率特征
                self.feature_names.append(f'vol_{t}')
        
        self.is_initialized = False
        self.last_valid_cluster = 99  # 入口簇改为99

        centroids_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'centroids.csv')
        if not os.path.exists(centroids_path):
            logger.error("未找到 centroids.csv 文件")
            sys.exit(1)
        try:
            centroids_df = pd.read_csv(centroids_path, index_col=0)
            self.centroids = {}
            for cluster_id in range(len(centroids_df)):
                row = centroids_df.iloc[cluster_id]
                centroid = []
                # 添加对数动量特征
                for t in self.windows:
                    centroid.append(row.get(f'log_mom_{t}', 0))
                # 添加波动率特征（只在大于1的窗口）
                for t in self.windows:
                    if t > 1:
                        centroid.append(row.get(f'vol_{t}', 0))
                self.centroids[cluster_id] = centroid
        except Exception:
            sys.exit(1)

    def predict_cluster(self, momentum_values, volatility_values):
        if not momentum_values or not volatility_values:
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (99, 999.0)

        features = []
        
        # 添加对数动量特征 - 按照窗口顺序
        for T in self.windows:
            val = momentum_values.get(f"T_{T}")
            features.append(val if val is not None else 0.0)

        # 添加波动率特征 - 只在大于1的窗口
        for T in self.windows:
            if T > 1:
                val = volatility_values.get(f"T_{T}")
                features.append(val if val is not None else 0.0)

        feature_vector = np.array(features)

        if np.all(feature_vector == 0):
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (99, 999.0)

        min_distance = float('inf')
        best_cluster = 99

        for cluster_id, centroid in self.centroids.items():
            dist = np.linalg.norm(feature_vector - np.array(centroid))
            if dist < min_distance:
                min_distance = dist
                best_cluster = cluster_id

        if best_cluster != 99:  # 一旦计算出具体簇后不回入口簇99
            self.is_initialized = True
            self.last_valid_cluster = best_cluster

        return best_cluster, min_distance