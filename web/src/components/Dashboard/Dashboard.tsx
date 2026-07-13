import { useMarketStore } from '../../stores/marketStore';
import { PriceHeader } from './PriceHeader';
import { PositionPanel } from '../PositionPanel/PositionPanel';
import { StrategyStatus } from '../StrategyStatus/StrategyStatus';
import { TradeHistory } from '../TradeHistory/TradeHistory';
import { AlertPanel } from '../AlertPanel/AlertPanel';
import { OrderBookPanel } from './OrderBookPanel';

export function Dashboard() {
  const market = useMarketStore((s) => s.market);

  return (
    <div className="space-y-4">
      {/* Price Header */}
      <PriceHeader />

      {/* Main Grid */}
      <div className="grid grid-cols-12 gap-4">
        {/* Left: Strategy + Position */}
        <div className="col-span-3 space-y-4">
          <StrategyStatus />
          <PositionPanel />
        </div>

        {/* Center: Chart placeholder */}
        <div className="col-span-6">
          <div className="card p-4 h-[400px] flex items-center justify-center">
            <div className="text-center">
              <div className="text-6xl mb-4 text-[var(--border-strong)]">◈</div>
              <p className="text-lg mb-2 text-[var(--text-secondary)] font-mono tracking-wider">CHART_MODULE</p>
              <p className="text-xs text-[var(--text-muted)] font-mono">TradingView Lightweight Charts</p>
              <div className="mt-6 pt-4 border-t border-[var(--border)]">
                <span className="text-xs text-[var(--text-muted)] font-mono">PRICE_FEED: </span>
                <span className="text-lg font-mono text-[var(--brand)]">
                  {market.price.toFixed(4)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Right: OrderBook */}
        <div className="col-span-3">
          <OrderBookPanel />
        </div>
      </div>

      {/* Bottom Grid */}
      <div className="grid grid-cols-2 gap-4">
        <TradeHistory />
        <AlertPanel />
      </div>
    </div>
  );
}
