import { useMarketStore } from '../../stores/marketStore';

export function PositionPanel() {
  const position = useMarketStore((s) => s.position);
  const market = useMarketStore((s) => s.market);

  const hasPosition = position.size !== 0;
  const isLong = position.size > 0;

  // Calculate PnL percentage
  const pnlPct = hasPosition
    ? ((market.price - position.entry_price) / position.entry_price) * (isLong ? 1 : -1) * 100
    : 0;

  // Calculate SL/TP distance
  const slDist = hasPosition
    ? Math.abs(position.entry_price - position.sl) / position.entry_price * 100
    : 0;
  const tpDist = hasPosition
    ? Math.abs(position.tp - position.entry_price) / position.entry_price * 100
    : 0;

  return (
    <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
      <div className="text-sm text-gray-500 mb-3">持仓详情</div>

      {!hasPosition ? (
        <div className="text-center py-8 text-gray-600">
          <div className="text-3xl mb-2">💤</div>
          <div>无持仓</div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Direction */}
          <div className={`text-center py-2 rounded-lg ${
            isLong ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
          }`}>
            <span className="text-lg font-bold">
              {isLong ? '🟢 LONG' : '🔴 SHORT'}
            </span>
            <span className="text-sm ml-2">{position.leverage}x</span>
          </div>

          {/* Entry / Current */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#0f0f23] rounded p-2">
              <div className="text-xs text-gray-600">入场价</div>
              <div className="text-sm font-mono">{position.entry_price.toFixed(4)}</div>
            </div>
            <div className="bg-[#0f0f23] rounded p-2">
              <div className="text-xs text-gray-600">当前价</div>
              <div className="text-sm font-mono">{market.price.toFixed(4)}</div>
            </div>
          </div>

          {/* PnL */}
          <div className={`text-center py-2 rounded-lg ${
            position.unrealized_pnl >= 0 ? 'bg-green-900/20' : 'bg-red-900/20'
          }`}>
            <div className={`text-xl font-bold font-mono ${
              position.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
            </div>
            <div className={`text-xs ${
              pnlPct >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </div>
          </div>

          {/* SL / TP */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#0f0f23] rounded p-2">
              <div className="text-xs text-red-400">止损 SL</div>
              <div className="text-sm font-mono">{position.sl.toFixed(4)}</div>
              <div className="text-xs text-gray-600">-{slDist.toFixed(2)}%</div>
            </div>
            <div className="bg-[#0f0f23] rounded p-2">
              <div className="text-xs text-green-400">止盈 TP</div>
              <div className="text-sm font-mono">{position.tp.toFixed(4)}</div>
              <div className="text-xs text-gray-600">+{tpDist.toFixed(2)}%</div>
            </div>
          </div>

          {/* Size */}
          <div className="flex justify-between text-xs">
            <span className="text-gray-500">数量</span>
            <span className="font-mono">{Math.abs(position.size).toFixed(4)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
