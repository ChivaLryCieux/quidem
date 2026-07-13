import { useMarketStore } from '../../stores/marketStore';

export function StrategyStatus() {
  const strategy = useMarketStore((s) => s.strategy);

  // 市场状态映射到简洁标签
  const stateMap: Record<string, { label: string; color: string }> = {
    '📈 强涨': { label: 'STRONG_UP', color: 'text-[var(--green)] border-[var(--green)]/30 bg-[var(--green)]/5' },
    '📈 小涨': { label: 'WEAK_UP', color: 'text-[var(--green)]/80 border-[var(--green)]/20 bg-[var(--green)]/5' },
    '📉 强跌': { label: 'STRONG_DN', color: 'text-[var(--red)] border-[var(--red)]/30 bg-[var(--red)]/5' },
    '📉 小跌': { label: 'WEAK_DN', color: 'text-[var(--red)]/80 border-[var(--red)]/20 bg-[var(--red)]/5' },
    '🦀 震荡': { label: 'CHOP', color: 'text-[var(--text-secondary)] border-[var(--border-strong)] bg-[var(--bg-subtle)]' },
    '⏳ 等待': { label: 'IDLE', color: 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--bg-subtle)]' },
  };

  const stateInfo = stateMap[strategy.state] || { label: 'UNKNOWN', color: 'text-[var(--text-muted)] border-[var(--border)]' };

  const supertrendLabel = (val: number) => {
    if (val === 1) return { text: '▲ LONG', color: 'text-[var(--green)]' };
    if (val === -1) return { text: '▼ SHORT', color: 'text-[var(--red)]' };
    return { text: '— FLAT', color: 'text-[var(--text-muted)]' };
  };

  const st5 = supertrendLabel(strategy.supertrend_5m);
  const st15 = supertrendLabel(strategy.supertrend_15m);
  const st1h = supertrendLabel(strategy.supertrend_1h);

  return (
    <div className="card p-4">
      <div className="text-[10px] text-[var(--text-muted)] mb-4 font-mono tracking-widest">STRATEGY</div>

      {/* Market Regime */}
      <div className={`text-center py-4 mb-4 border rounded ${stateInfo.color}`}>
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
      <div className="mt-4 pt-3 border-t border-[var(--border)]">
        <div className="text-[10px] text-[var(--text-muted)] mb-3 font-mono tracking-widest">SUPERTREND</div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="bg-[var(--bg-subtle)] border border-[var(--border)] rounded p-2">
            <div className="text-[10px] text-[var(--text-muted)] font-mono">5m</div>
            <div className={`text-xs font-bold font-mono mt-1 ${st5.color}`}>{st5.text}</div>
          </div>
          <div className="bg-[var(--bg-subtle)] border border-[var(--border)] rounded p-2">
            <div className="text-[10px] text-[var(--text-muted)] font-mono">15m</div>
            <div className={`text-xs font-bold font-mono mt-1 ${st15.color}`}>{st15.text}</div>
          </div>
          <div className="bg-[var(--bg-subtle)] border border-[var(--border)] rounded p-2">
            <div className="text-[10px] text-[var(--text-muted)] font-mono">1h</div>
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
  let valueClass = 'text-[var(--text-secondary)]';
  if (color === 'green') valueClass = 'text-[var(--green)]';
  if (color === 'red') valueClass = 'text-[var(--red)]';
  if (threshold !== undefined && above !== undefined) {
    valueClass = above ? 'text-[var(--green)]' : 'text-[var(--red)]';
  }

  return (
    <div className="flex justify-between items-center">
      <span className="text-[10px] text-[var(--text-muted)] font-mono tracking-wider">{label}</span>
      <span className={`text-sm font-mono font-bold ${valueClass}`}>{value}</span>
    </div>
  );
}
