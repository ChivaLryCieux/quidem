/**
 * 状态查询API
 */
import apiClient from './index';

export const statusAPI = {
    // 获取当前状态
    getCurrentStatus: () => {
        return apiClient.get('/status/current');
    },

    // 心跳检测
    getHeartbeat: () => {
        return apiClient.get('/status/heartbeat');
    },
};
