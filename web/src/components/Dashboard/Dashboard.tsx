import { PriceHeader } from './PriceHeader';
import { PositionPanel } from '../PositionPanel/PositionPanel';
import { StrategyStatus } from '../StrategyStatus/StrategyStatus';
import { TradeHistory } from '../TradeHistory/TradeHistory';
import { AlertPanel } from '../AlertPanel/AlertPanel';
import { OrderBookPanel } from './OrderBookPanel';
import { KLineChart } from './KLineChart';

export function Dashboard() {
  return (
    <div className="grid grid-cols-12 gap-4 max-w-[1600px] mx-auto">
      {/* 左侧栏：各项指标、持仓与盘口数据 */}
      <div className="col-span-12 lg:col-span-4 xl:col-span-3 space-y-4">
        <StrategyStatus />
        <PositionPanel />
        <OrderBookPanel />
      </div>

      {/* 右侧主体：K线图与成交历史 */}
      <div className="col-span-12 lg:col-span-8 xl:col-span-9 space-y-4">
        {/* 精致行情/余额数据头 */}
        <PriceHeader />

        {/* 主体 K 线图表 */}
        <KLineChart />

        {/* 底部交易与告警日志 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TradeHistory />
          <AlertPanel />
        </div>
      </div>
    </div>
  );
}
