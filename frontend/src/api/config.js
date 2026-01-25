/**
 * 配置管理API
 */
import apiClient from './index';

export const configAPI = {
    // 获取配置
    getConfig: () => {
        return apiClient.get('/config/get');
    },

    // 更新配置
    updateConfig: (config) => {
        return apiClient.post('/config/update', config);
    },
};
