/**
 * Zustand状态管理
 */
import { create } from 'zustand';

const useBotStore = create((set) => ({
    // 机器人状态
    status: null,
    isOnline: false,

    // 交易历史
    trades: [],
    performance: null,

    // 配置
    config: null,

    // UI状态
    loading: false,
    error: null,

    // 更新状态
    setStatus: (status) => set({ status, isOnline: true, error: null }),

    // 设置离线
    setOffline: () => set({ isOnline: false }),

    // 更新交易历史
    setTrades: (trades) => set({ trades }),

    // 更新收益统计
    setPerformance: (performance) => set({ performance }),

    // 更新配置
    setConfig: (config) => set({ config }),

    // 设置加载状态
    setLoading: (loading) => set({ loading }),

    // 设置错误
    setError: (error) => set({ error }),

    // 清除错误
    clearError: () => set({ error: null }),
}));

export default useBotStore;
