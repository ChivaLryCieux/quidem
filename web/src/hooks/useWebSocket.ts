import { useEffect, useRef, useCallback } from 'react';
import { useMarketStore } from '../stores/marketStore';
import type { WSMessage } from '../types';

const WS_URL = `ws://${window.location.host}/ws`;
const RECONNECT_DELAY = 3000;
const PING_INTERVAL = 25000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const { setConnected, handleMessage } = useMarketStore();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setConnected(true);

      // Start ping
      pingTimerRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        if (event.data === 'pong') return;

        const msg: WSMessage = JSON.parse(event.data);
        handleMessage(msg);
      } catch (err) {
        console.error('Failed to parse WS message:', err);
      }
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setConnected(false);
      cleanup();

      // Reconnect
      reconnectTimerRef.current = window.setTimeout(() => {
        connect();
      }, RECONNECT_DELAY);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      ws.close();
    };

    wsRef.current = ws;
  }, [setConnected, handleMessage]);

  const cleanup = useCallback(() => {
    if (pingTimerRef.current) {
      clearInterval(pingTimerRef.current);
      pingTimerRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    cleanup();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [cleanup]);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return {
    connected: useMarketStore((s) => s.connected),
    disconnect,
    reconnect: connect,
  };
}
