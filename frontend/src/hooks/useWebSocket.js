/**
 * WebSocket自定义Hook
 */
import { useEffect, useRef, useCallback } from 'react';
import { API_CONFIG, WS_CONFIG } from '../config';
import useBotStore from '../store/useBotStore';

export const useWebSocket = () => {
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const reconnectAttemptsRef = useRef(0);

    const { setStatus, setOffline } = useBotStore();

    const connect = useCallback(() => {
        try {
            const ws = new WebSocket(API_CONFIG.wsURL);

            ws.onopen = () => {
                console.log('WebSocket连接成功');
                reconnectAttemptsRef.current = 0;
            };

            ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);

                    if (message.type === 'status_update' && message.data) {
                        setStatus(message.data);
                    } else if (message.type === 'error') {
                        console.error('WebSocket错误:', message.message);
                    }
                } catch (error) {
                    console.error('解析WebSocket消息失败:', error);
                }
            };

            ws.onerror = (error) => {
                console.error('WebSocket错误:', error);
            };

            ws.onclose = () => {
                console.log('WebSocket连接关闭');
                setOffline();

                // 尝试重连
                if (reconnectAttemptsRef.current < WS_CONFIG.maxReconnectAttempts) {
                    reconnectAttemptsRef.current += 1;
                    console.log(`尝试重连 (${reconnectAttemptsRef.current}/${WS_CONFIG.maxReconnectAttempts})...`);

                    reconnectTimeoutRef.current = setTimeout(() => {
                        connect();
                    }, WS_CONFIG.reconnectInterval);
                } else {
                    console.error('WebSocket重连失败,已达到最大重连次数');
                }
            };

            wsRef.current = ws;
        } catch (error) {
            console.error('WebSocket连接失败:', error);
        }
    }, [setStatus, setOffline]);

    const disconnect = useCallback(() => {
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
        }

        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }
    }, []);

    useEffect(() => {
        connect();

        return () => {
            disconnect();
        };
    }, [connect, disconnect]);

    return { connect, disconnect };
};
