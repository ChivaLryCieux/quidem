import { create } from 'zustand';
import type {
  MarketData,
  StrategyState,
  PositionInfo,
  AccountInfo,
  TradeRecord,
  AlertRecord,
  SystemStatus,
  Snapshot,
  WSMessage,
} from '../types';

interface MarketStore {
  // 数据
  market: MarketData;
  strategy: StrategyState;
  position: PositionInfo;
  account: AccountInfo;
  trades: TradeRecord[];
  alerts: AlertRecord[];
  system: SystemStatus;

  // 连接状态
  connected: boolean;
  lastUpdate: number;

  // Actions
  setSnapshot: (snapshot: Snapshot) => void;
  updateMarket: (data: Partial<MarketData>) => void;
  updatePrice: (price: number) => void;
  updateStrategy: (data: Partial<StrategyState>) => void;
  updatePosition: (data: Partial<PositionInfo>) => void;
  updateAccount: (data: Partial<AccountInfo>) => void;
  addTrade: (trade: TradeRecord) => void;
  addAlert: (alert: AlertRecord) => void;
  updateSystem: (data: Partial<SystemStatus>) => void;
  setConnected: (connected: boolean) => void;
  handleMessage: (msg: WSMessage) => void;
}

const defaultMarket: MarketData = {
  price: 0,
  kline_5m: null,
  kline_15m: null,
  kline_1h: null,
  orderbook: null,
  funding_rate: 0,
  btc_price: 0,
  change_24h: 0,
};

const defaultStrategy: StrategyState = {
  state: '⏳ 等待',
  color: 'white',
  adx: 0,
  macd: 0,
  reversal: 0,
  supertrend_5m: 0,
  supertrend_15m: 0,
  supertrend_1h: 0,
};

const defaultPosition: PositionInfo = {
  size: 0,
  entry_price: 0,
  sl: 0,
  tp: 0,
  entry_time: 0,
  leverage: 10,
  unrealized_pnl: 0,
};

const defaultAccount: AccountInfo = {
  balance: 0,
  mode: 'Paper',
  symbol: 'SOL/USDT',
};

const defaultSystem: SystemStatus = {
  status: 'initializing',
  uptime: 0,
  start_time: 0,
  ws_connected: false,
  exchange_connected: false,
  error_message: '',
};

export const useMarketStore = create<MarketStore>((set) => ({
  market: defaultMarket,
  strategy: defaultStrategy,
  position: defaultPosition,
  account: defaultAccount,
  trades: [],
  alerts: [],
  system: defaultSystem,

  connected: false,
  lastUpdate: 0,

  setSnapshot: (snapshot) =>
    set({
      market: snapshot.market,
      strategy: snapshot.strategy,
      position: snapshot.position,
      account: snapshot.account,
      trades: snapshot.trades,
      alerts: snapshot.alerts,
      system: snapshot.system,
      lastUpdate: Date.now(),
    }),

  updateMarket: (data) =>
    set((state) => ({
      market: { ...state.market, ...data },
      lastUpdate: Date.now(),
    })),

  updatePrice: (price) =>
    set((state) => ({
      market: { ...state.market, price },
      lastUpdate: Date.now(),
    })),

  updateStrategy: (data) =>
    set((state) => ({
      strategy: { ...state.strategy, ...data },
      lastUpdate: Date.now(),
    })),

  updatePosition: (data) =>
    set((state) => ({
      position: { ...state.position, ...data },
      lastUpdate: Date.now(),
    })),

  updateAccount: (data) =>
    set((state) => ({
      account: { ...state.account, ...data },
      lastUpdate: Date.now(),
    })),

  addTrade: (trade) =>
    set((state) => ({
      trades: [trade, ...state.trades].slice(0, 100),
      lastUpdate: Date.now(),
    })),

  addAlert: (alert) =>
    set((state) => ({
      alerts: [alert, ...state.alerts].slice(0, 50),
      lastUpdate: Date.now(),
    })),

  updateSystem: (data) =>
    set((state) => ({
      system: { ...state.system, ...data },
      lastUpdate: Date.now(),
    })),

  setConnected: (connected) => set({ connected }),

  handleMessage: (msg) => {
    const { type, data } = msg;
    const store = useMarketStore.getState();

    switch (type) {
      case 'snapshot':
        store.setSnapshot(data);
        break;
      case 'market':
        store.updateMarket(data);
        break;
      case 'price':
        store.updatePrice(data.price);
        break;
      case 'strategy':
        store.updateStrategy(data);
        break;
      case 'position':
        store.updatePosition(data);
        break;
      case 'account':
        store.updateAccount(data);
        break;
      case 'trade':
        store.addTrade(data);
        break;
      case 'alert':
        store.addAlert(data);
        break;
      case 'system':
        store.updateSystem(data);
        break;
      case 'heartbeat':
        // 心跳，只更新时间
        set({ lastUpdate: Date.now() });
        break;
    }
  },
}));
