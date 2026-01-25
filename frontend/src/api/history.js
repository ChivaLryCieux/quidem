/**
 * 历史数据API
 */
import apiClient from './index';

export const historyAPI = {
    // 获取交易历史
    getTrades: (limit = 100) => {
        return apiClient.get('/history/trades', { params: { limit } });
    },

    // 获取收益统计
    getPerformance: (limit = 100) => {
        return apiClient.get('/history/performance', { params: { limit } });
    },
};
