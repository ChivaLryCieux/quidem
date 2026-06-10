// 市场数据
export interface MarketData {
  price: number;
  kline_5m: number[] | null;
  kline_15m: number[] | null;
  kline_1h: number[] | null;
  orderbook: OrderBook | null;
  funding_rate: number;
  btc_price: number;
  change_24h: number;
}

export interface OrderBook {
  bids: [number, number][];
  asks: [number, number][];
}

// 策略状态
export interface StrategyState {
  state: string;
  color: string;
  adx: number;
  macd: number;
  reversal: number;
  supertrend_5m: number;
  supertrend_15m: number;
  supertrend_1h: number;
}

// 持仓信息
export interface PositionInfo {
  size: number;
  entry_price: number;
  sl: number;
  tp: number;
  entry_time: number;
  leverage: number;
  unrealized_pnl: number;
}

// 账户信息
export interface AccountInfo {
  balance: number;
  mode: string;
  symbol: string;
}

// 交易记录
export interface TradeRecord {
  type: 'entry' | 'exit';
  time: number;
  // 开仓字段
  side?: string;
  price?: number;
  leverage?: number;
  sl?: number;
  tp?: number;
  regime?: string;
  // 平仓字段
  reason?: string;
  pnl?: number;
  fee?: number;
  balance?: number;
}

// 告警记录
export interface AlertRecord {
  type: string;
  message: string;
  details: Record<string, any>;
  time: number;
}

// 系统状态
export interface SystemStatus {
  status: string;
  uptime: number;
  start_time: number;
  ws_connected: boolean;
}

// 完整快照
export interface Snapshot {
  market: MarketData;
  strategy: StrategyState;
  position: PositionInfo;
  account: AccountInfo;
  trades: TradeRecord[];
  alerts: AlertRecord[];
  system: SystemStatus;
}

// WebSocket 消息
export interface WSMessage {
  type: 'snapshot' | 'market' | 'price' | 'strategy' | 'position' | 'account' | 'trade' | 'alert' | 'system' | 'heartbeat';
  data: any;
  timestamp: number;
}
