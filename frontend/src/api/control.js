/**
 * 交易控制API
 */
import apiClient from './index';

export const controlAPI = {
    // 发送控制命令
    sendCommand: (action, params = {}) => {
        return apiClient.post('/control/command', { action, params });
    },

    // 启动交易
    start: () => {
        return apiClient.post('/control/start');
    },

    // 停止交易
    stop: () => {
        return apiClient.post('/control/stop');
    },

    // 暂停交易
    pause: () => {
        return apiClient.post('/control/pause');
    },

    // 强制平仓
    closePosition: () => {
        return apiClient.post('/control/close-position');
    },
};
