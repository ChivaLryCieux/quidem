/**
 * API配置
 */
export const API_CONFIG = {
    baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
    wsURL: import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/realtime',
    apiKey: import.meta.env.VITE_API_KEY || 'your-secret-api-key-change-this',
    timeout: 10000,
};

/**
 * WebSocket重连配置
 */
export const WS_CONFIG = {
    reconnectInterval: 3000, // 重连间隔(毫秒)
    maxReconnectAttempts: 10, // 最大重连次数
};

/**
 * 图表配置
 */
export const CHART_CONFIG = {
    theme: 'dark',
    backgroundColor: 'transparent',
};
