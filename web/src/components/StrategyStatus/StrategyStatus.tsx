import { useMarketStore } from '../../stores/marketStore';

export function StrategyStatus() {
  const strategy = useMarketStore((s) => s.strategy);

  const stateColorMap: Record<string, string> = {
    '📈 强涨': 'text-green-400 bg-green-900/30',
    '📈 小涨': 'text-green-300 bg-green-900/20',
    '📉 强跌': 'text-red-400 bg-red-900/30',
    '📉 小跌': 'text-red-300 bg-red-900/20',
    '🦀 震荡': 'text-yellow-400 bg-yellow-900/30',
    '⏳ 等待': 'text-gray-400 bg-gray-800/30',
  };

  const stateClass = stateColorMap[strategy.state] || 'text-gray-400 bg-gray-800/30';

  const supertrendLabel = (val: number) => {
    if (val === 1) return { text: '🟢 多', color: 'text-green-400' };
    if (val === -1) return { text: '🔴 空', color: 'text-red-400' };
    return { text: '⚪ -', color: 'text-gray-500' };
  };

  const st5 = supertrendLabel(strategy.supertrend_5m);
  const st15 = supertrendLabel(strategy.supertrend_15m);
  const st1h = supertrendLabel(strategy.supertrend_1h);

  return (
    <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
      <div className="text-sm text-gray-500 mb-3">策略状态</div>

      {/* Market Regime */}
      <div className={`text-center py-3 rounded-lg mb-4 ${stateClass}`}>
        <div className="text-2xl font-bold">{strategy.state}</div>
      </div>

      {/* Indicators */}
      <div className="space-y-3">
        <IndicatorRow label="ADX" value={strategy.adx.toFixed(1)} threshold={20} above={strategy.adx > 20} />
        <IndicatorRow label="MACD" value={strategy.macd.toFixed(5)} color={strategy.macd >= 0 ? 'green' : 'red'} />
        <IndicatorRow label="Reversal" value={strategy.reversal.toFixed(3)} color={strategy.reversal >= 0 ? 'green' : 'red'} />
      </div>

      {/* SuperTrend */}
      <div className="mt-4 pt-3 border-t border-gray-800">
        <div className="text-xs text-gray-500 mb-2">SuperTrend</div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="bg-[#0f0f23] rounded p-2">
            <div className="text-xs text-gray-600">5m</div>
            <div className={`text-sm font-bold ${st5.color}`}>{st5.text}</div>
          </div>
          <div className="bg-[#0f0f23] rounded p-2">
            <div className="text-xs text-gray-600">15m</div>
            <div className={`text-sm font-bold ${st15.color}`}>{st15.text}</div>
          </div>
          <div className="bg-[#0f0f23] rounded p-2">
            <div className="text-xs text-gray-600">1h</div>
            <div className={`text-sm font-bold ${st1h.color}`}>{st1h.text}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function IndicatorRow({
  label,
  value,
  threshold,
  above,
  color,
}: {
  label: string;
  value: string;
  threshold?: number;
  above?: boolean;
  color?: 'green' | 'red';
}) {
  let valueClass = 'text-white';
  if (color === 'green') valueClass = 'text-green-400';
  if (color === 'red') valueClass = 'text-red-400';
  if (threshold !== undefined && above !== undefined) {
    valueClass = above ? 'text-green-400' : 'text-red-400';
  }

  return (
    <div className="flex justify-between items-center">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`text-sm font-mono font-bold ${valueClass}`}>{value}</span>
    </div>
  );
}
