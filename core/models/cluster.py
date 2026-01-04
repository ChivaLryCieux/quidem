import numpy as np
import pandas as pd
import os
import sys
import logging

logger = logging.getLogger(__name__)

class KMeansClusterAnalyzer:
    def __init__(self, n_clusters=5):
        self.n_clusters = n_clusters
        self.feature_names = ['mom_5', 'mom_10', 'mom_25', 'mom_50', 'vol_5', 'vol_10', 'vol_25', 'vol_50']
        self.is_initialized = False
        self.last_valid_cluster = 5

        centroids_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'centroids.csv')
        if not os.path.exists(centroids_path):
            logger.error("未找到 centroids.csv 文件")
            sys.exit(1)
        try:
            centroids_df = pd.read_csv(centroids_path, index_col=0)
            self.centroids = {}
            for cluster_id in range(len(centroids_df)):
                row = centroids_df.iloc[cluster_id]
                self.centroids[cluster_id] = [
                    row.get('log_mom_5', 0), row.get('log_mom_10', 0),
                    row.get('log_mom_25', 0), row.get('log_mom_50', 0),
                    row.get('vol_5', 0), row.get('vol_10', 0),
                    row.get('vol_25', 0), row.get('vol_50', 0)
                ]
        except Exception:
            sys.exit(1)

    def predict_cluster(self, momentum_values, volatility_values):
        if not momentum_values or not volatility_values:
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (5, 999.0)

        features = []
        periods = [5, 10, 25, 50]

        for T in periods:
            val = momentum_values.get(f"T_{T}")
            features.append(val if val is not None else 0.0)

        for T in periods:
            val = volatility_values.get(f"T_{T}")
            features.append(val if val is not None else 0.0)

        feature_vector = np.array(features)

        if np.all(feature_vector == 0):
            return (self.last_valid_cluster, 0.0) if self.is_initialized else (5, 999.0)

        min_distance = float('inf')
        best_cluster = 5

        for cluster_id, centroid in self.centroids.items():
            dist = np.linalg.norm(feature_vector - np.array(centroid))
            if dist < min_distance:
                min_distance = dist
                best_cluster = cluster_id

        if best_cluster != 5:
            self.is_initialized = True
            self.last_valid_cluster = best_cluster

        return best_cluster, min_distance