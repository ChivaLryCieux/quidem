import { useMarketStore } from '../../stores/marketStore';

export function PriceHeader() {
  const market = useMarketStore((s) => s.market);
  const account = useMarketStore((s) => s.account);
  const position = useMarketStore((s) => s.position);

  return (
    <div className="grid grid-cols-5 gap-3">
      {/* Price */}
      <div className="card-red-accent p-4">
        <div className="text-[10px] text-[var(--text-muted)] mb-2 font-mono tracking-widest">PRICE</div>
        <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">
          {market.price.toFixed(4)}
        </div>
        <div className={`text-xs font-mono mt-1 ${
          market.change_24h >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
        }`}>
          {market.change_24h >= 0 ? '▲' : '▼'} {Math.abs(market.change_24h).toFixed(2)}%
        </div>
      </div>

      {/* Balance */}
      <div className="card p-4">
        <div className="text-[10px] text-[var(--text-muted)] mb-2 font-mono tracking-widest">BALANCE</div>
        <div className="text-2xl font-bold font-mono text-[var(--brand)]">
          ${account.balance.toFixed(2)}
        </div>
        <div className="text-xs font-mono text-[var(--text-muted)] mt-1">{account.mode.toUpperCase()}</div>
      </div>

      {/* Unrealized PnL */}
      <div className="card p-4">
        <div className="text-[10px] text-[var(--text-muted)] mb-2 font-mono tracking-widest">UNREALIZED</div>
        <div className={`text-2xl font-bold font-mono ${
          position.unrealized_pnl >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
        }`}>
          {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
        </div>
        <div className="text-xs font-mono text-[var(--text-muted)] mt-1">
          {position.size !== 0
            ? `${position.size > 0 ? 'LONG' : 'SHORT'} ${Math.abs(position.size).toFixed(4)}`
            : 'FLAT'}
        </div>
      </div>

      {/* Funding Rate */}
      <div className="card p-4">
        <div className="text-[10px] text-[var(--text-muted)] mb-2 font-mono tracking-widest">FUNDING</div>
        <div className="text-2xl font-bold font-mono text-[var(--text-secondary)]">
          {(market.funding_rate * 100).toFixed(4)}%
        </div>
        <div className="text-xs font-mono text-[var(--text-muted)] mt-1">
          BTC: <span className="text-[var(--text-secondary)]">${market.btc_price.toFixed(0)}</span>
        </div>
      </div>

      {/* Position Info */}
      <div className="card p-4">
        <div className="text-[10px] text-[var(--text-muted)] mb-2 font-mono tracking-widest">POSITION</div>
        {position.size !== 0 ? (
          <>
            <div className="text-sm font-mono text-[var(--text-secondary)]">
              <span className="text-[var(--text-muted)]">EP:</span> {position.entry_price.toFixed(4)}
            </div>
            <div className="flex gap-3 text-xs font-mono mt-2">
              <span className="text-[var(--red)]">
                <span className="text-[var(--text-muted)]">SL:</span> {position.sl.toFixed(4)}
              </span>
              <span className="text-[var(--green)]">
                <span className="text-[var(--text-muted)]">TP:</span> {position.tp.toFixed(4)}
              </span>
            </div>
          </>
        ) : (
          <div className="text-lg font-mono text-[var(--border-strong)]">—</div>
        )}
      </div>
    </div>
  );
}
