/**
 * Axios API客户端
 */
import axios from 'axios';
import { API_CONFIG } from '../config';

const apiClient = axios.create({
    baseURL: API_CONFIG.baseURL + '/api',
    timeout: API_CONFIG.timeout,
    headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_CONFIG.apiKey,
    },
});

// 请求拦截器
apiClient.interceptors.request.use(
    (config) => {
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// 响应拦截器
apiClient.interceptors.response.use(
    (response) => {
        return response.data;
    },
    (error) => {
        const message = error.response?.data?.detail || error.message || '请求失败';
        console.error('API Error:', message);
        return Promise.reject(new Error(message));
    }
);

export default apiClient;
