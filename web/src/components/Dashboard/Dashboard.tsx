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
          <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4 h-[400px] flex items-center justify-center">
            <div className="text-center text-gray-500">
              <p className="text-lg mb-2">📊 K线图表</p>
              <p className="text-sm">TradingView Lightweight Charts</p>
              <p className="text-xs mt-2">
                当前价格: <span className="text-cyan-400 font-mono">{market.price.toFixed(4)}</span>
              </p>
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
