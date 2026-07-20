import { useMarketStore } from '../../stores/marketStore';
import { PriceHeader } from './PriceHeader';
import { PositionPanel } from '../PositionPanel/PositionPanel';
import { StrategyStatus } from '../StrategyStatus/StrategyStatus';
import { TradeHistory } from '../TradeHistory/TradeHistory';
import { AlertPanel } from '../AlertPanel/AlertPanel';
import { OrderBookPanel } from './OrderBookPanel';
import { KLineChart } from './KLineChart';

export function Dashboard() {
  const mode = useMarketStore((s) => s.account.mode?.toLowerCase() || 'dashboard');
  const isDashboardMode = mode === 'dashboard';

  return (
    <div className="flex h-full w-full gap-4 overflow-hidden">
      {/* 左侧栏：各项指标、持仓与盘口数据 */}
      <div className="w-[300px] flex flex-col gap-4 h-full shrink-0 overflow-y-auto pr-1">
        <StrategyStatus />
        <PositionPanel />
        <OrderBookPanel />
      </div>

      {/* 右侧主体：K线图与成交历史 */}
      <div className="flex-1 flex flex-col gap-4 h-full overflow-hidden">
        {isDashboardMode ? (
          // 看板模式下，右侧纯是 K 线图，撑满全高
          <div className="flex-1 h-full min-h-0">
            <KLineChart />
          </div>
        ) : (
          // 其他模式（模拟/实盘）下，有头部数据与底部日志
          <>
            <PriceHeader />
            <div className="flex-1 min-h-0">
              <KLineChart />
            </div>
            <div className="grid grid-cols-2 gap-4 h-[180px] shrink-0 min-h-0">
              <div className="h-full overflow-y-auto">
                <TradeHistory />
              </div>
              <div className="h-full overflow-y-auto">
                <AlertPanel />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
