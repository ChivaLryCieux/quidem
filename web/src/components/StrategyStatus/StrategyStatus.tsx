import { useMarketStore } from '../../stores/marketStore';

export function StrategyStatus() {
  const strategy = useMarketStore((s) => s.strategy);

  // 市场状态映射到简洁标签
  const stateMap: Record<string, { label: string; color: string }> = {
    '📈 强涨': { label: 'STRONG_UP', color: 'text-[#2ecc71] border-[#2ecc71]/30' },
    '📈 小涨': { label: 'WEAK_UP', color: 'text-[#2ecc71]/70 border-[#2ecc71]/20' },
    '📉 强跌': { label: 'STRONG_DN', color: 'text-[#e63946] border-[#e63946]/30' },
    '📉 小跌': { label: 'WEAK_DN', color: 'text-[#e63946]/70 border-[#e63946]/20' },
    '🦀 震荡': { label: 'CHOP', color: 'text-[#888] border-[#333]' },
    '⏳ 等待': { label: 'IDLE', color: 'text-[#555] border-[#222]' },
  };

  const stateInfo = stateMap[strategy.state] || { label: 'UNKNOWN', color: 'text-[#555] border-[#222]' };

  const supertrendLabel = (val: number) => {
    if (val === 1) return { text: '▲ LONG', color: 'text-[#2ecc71]' };
    if (val === -1) return { text: '▼ SHORT', color: 'text-[#e63946]' };
    return { text: '— FLAT', color: 'text-[#333]' };
  };

  const st5 = supertrendLabel(strategy.supertrend_5m);
  const st15 = supertrendLabel(strategy.supertrend_15m);
  const st1h = supertrendLabel(strategy.supertrend_1h);

  return (
    <div className="halftone-card rounded-sm p-4">
      <div className="text-[10px] text-[#555] mb-4 font-mono tracking-widest">STRATEGY</div>

      {/* Market Regime */}
      <div className={`text-center py-4 mb-4 border ${stateInfo.color}`}>
        <div className="text-lg font-bold font-mono tracking-wider">{stateInfo.label}</div>
      </div>

      {/* Indicators */}
      <div className="space-y-3">
        <IndicatorRow
          label="ADX"
          value={strategy.adx.toFixed(1)}
          threshold={20}
          above={strategy.adx > 20}
        />
        <IndicatorRow
          label="MACD"
          value={strategy.macd.toFixed(5)}
          color={strategy.macd >= 0 ? 'green' : 'red'}
        />
        <IndicatorRow
          label="REVERSAL"
          value={strategy.reversal.toFixed(3)}
          color={strategy.reversal >= 0 ? 'green' : 'red'}
        />
      </div>

      {/* SuperTrend */}
      <div className="mt-4 pt-3 border-t border-[#222]">
        <div className="text-[10px] text-[#555] mb-3 font-mono tracking-widest">SUPERTREND</div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="bg-[#0a0a0a] border border-[#222] p-2">
            <div className="text-[10px] text-[#444] font-mono">5m</div>
            <div className={`text-xs font-bold font-mono mt-1 ${st5.color}`}>{st5.text}</div>
          </div>
          <div className="bg-[#0a0a0a] border border-[#222] p-2">
            <div className="text-[10px] text-[#444] font-mono">15m</div>
            <div className={`text-xs font-bold font-mono mt-1 ${st15.color}`}>{st15.text}</div>
          </div>
          <div className="bg-[#0a0a0a] border border-[#222] p-2">
            <div className="text-[10px] text-[#444] font-mono">1h</div>
            <div className={`text-xs font-bold font-mono mt-1 ${st1h.color}`}>{st1h.text}</div>
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
  let valueClass = 'text-[#888]';
  if (color === 'green') valueClass = 'text-[#2ecc71]';
  if (color === 'red') valueClass = 'text-[#e63946]';
  if (threshold !== undefined && above !== undefined) {
    valueClass = above ? 'text-[#2ecc71]' : 'text-[#e63946]';
  }

  return (
    <div className="flex justify-between items-center">
      <span className="text-[10px] text-[#555] font-mono tracking-wider">{label}</span>
      <span className={`text-sm font-mono font-bold ${valueClass}`}>{value}</span>
    </div>
  );
}
