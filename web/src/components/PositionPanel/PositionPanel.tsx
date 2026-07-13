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
    <div className="card p-4">
      <div className="text-[10px] text-[var(--text-muted)] mb-4 font-mono tracking-widest">POSITION</div>

      {!hasPosition ? (
        <div className="text-center py-8">
          <div className="text-4xl text-[var(--border-strong)] mb-2">◇</div>
          <div className="text-xs font-mono text-[var(--text-muted)]">NO_POSITION</div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Direction */}
          <div className={`text-center py-3 border rounded font-mono ${
            isLong
              ? 'border-[var(--green)]/30 text-[var(--green)] bg-[var(--green)]/5'
              : 'border-[var(--red)]/30 text-[var(--red)] bg-[var(--red)]/5'
          }`}>
            <span className="text-lg font-bold tracking-wider">
              {isLong ? '▲ LONG' : '▼ SHORT'}
            </span>
            <span className="text-sm ml-2 opacity-70">{position.leverage}x</span>
          </div>

          {/* Entry / Current */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[var(--bg-subtle)] border border-[var(--border)] rounded p-2">
              <div className="text-[10px] text-[var(--text-muted)] font-mono">ENTRY</div>
              <div className="text-sm font-mono text-[var(--text-secondary)]">{position.entry_price.toFixed(4)}</div>
            </div>
            <div className="bg-[var(--bg-subtle)] border border-[var(--border)] rounded p-2">
              <div className="text-[10px] text-[var(--text-muted)] font-mono">MARK</div>
              <div className="text-sm font-mono text-[var(--text-secondary)]">{market.price.toFixed(4)}</div>
            </div>
          </div>

          {/* PnL */}
          <div className={`text-center py-3 border rounded ${
            position.unrealized_pnl >= 0
              ? 'border-[var(--green)]/20 bg-[var(--green)]/5'
              : 'border-[var(--red)]/20 bg-[var(--red)]/5'
          }`}>
            <div className={`text-xl font-bold font-mono ${
              position.unrealized_pnl >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
            }`}>
              {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
            </div>
            <div className={`text-xs font-mono mt-1 ${
              pnlPct >= 0 ? 'text-[var(--green)]/70' : 'text-[var(--red)]/70'
            }`}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </div>
          </div>

          {/* SL / TP */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[var(--bg-subtle)] border border-[var(--red)]/20 rounded p-2">
              <div className="text-[10px] text-[var(--red)] font-mono">STOP_LOSS</div>
              <div className="text-sm font-mono text-[var(--text-secondary)]">{position.sl.toFixed(4)}</div>
              <div className="text-[10px] text-[var(--text-muted)] font-mono">-{slDist.toFixed(2)}%</div>
            </div>
            <div className="bg-[var(--bg-subtle)] border border-[var(--green)]/20 rounded p-2">
              <div className="text-[10px] text-[var(--green)] font-mono">TAKE_PROFIT</div>
              <div className="text-sm font-mono text-[var(--text-secondary)]">{position.tp.toFixed(4)}</div>
              <div className="text-[10px] text-[var(--text-muted)] font-mono">+{tpDist.toFixed(2)}%</div>
            </div>
          </div>

          {/* Size */}
          <div className="flex justify-between items-center text-xs font-mono pt-2 border-t border-[var(--border)]">
            <span className="text-[var(--text-muted)]">SIZE</span>
            <span className="text-[var(--text-secondary)]">{Math.abs(position.size).toFixed(4)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
