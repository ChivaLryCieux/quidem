import { useMarketStore } from '../../stores/marketStore';
import type { TradeRecord } from '../../types';

export function TradeHistory() {
  const trades = useMarketStore((s) => s.trades);

  return (
    <div className="card p-4">
      <div className="text-[10px] text-[var(--text-muted)] mb-4 font-mono tracking-widest">TRADE_LOG</div>

      {trades.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl text-[var(--border-strong)] mb-2">◇</div>
          <div className="text-xs font-mono text-[var(--text-muted)]">NO_TRADES</div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-[var(--text-muted)] border-b border-[var(--border)]">
                <th className="text-left py-2 px-1 tracking-wider">TIME</th>
                <th className="text-left py-2 px-1 tracking-wider">TYPE</th>
                <th className="text-left py-2 px-1 tracking-wider">SIDE</th>
                <th className="text-right py-2 px-1 tracking-wider">PRICE</th>
                <th className="text-right py-2 px-1 tracking-wider">PnL</th>
                <th className="text-right py-2 px-1 tracking-wider">BAL</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 20).map((trade, i) => (
                <TradeRow key={i} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TradeRow({ trade }: { trade: TradeRecord }) {
  const time = new Date(trade.time).toLocaleTimeString('en-US', { hour12: false });

  if (trade.type === 'entry') {
    return (
      <tr className="border-b border-[var(--border)] hover:bg-[var(--bg-subtle)] transition-colors">
        <td className="py-2 px-1 text-[var(--text-muted)]">{time}</td>
        <td className="py-2 px-1">
          <span className="text-[var(--text-secondary)] border border-[var(--border)] px-1.5 py-0.5 text-[10px] rounded">ENTRY</span>
        </td>
        <td className="py-2 px-1">
          <span className={trade.side === 'LONG' ? 'text-[var(--green)]' : 'text-[var(--red)]'}>
            {trade.side}
          </span>
        </td>
        <td className="py-2 px-1 text-right text-[var(--text-secondary)]">{trade.price?.toFixed(4)}</td>
        <td className="py-2 px-1 text-right text-[var(--text-muted)]">—</td>
        <td className="py-2 px-1 text-right text-[var(--text-muted)]">—</td>
      </tr>
    );
  }

  const pnlColor = (trade.pnl ?? 0) >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]';

  return (
    <tr className="border-b border-[var(--border)] hover:bg-[var(--bg-subtle)] transition-colors">
      <td className="py-2 px-1 text-[var(--text-muted)]">{time}</td>
      <td className="py-2 px-1">
        <span className="text-[var(--red)] border border-[var(--red)]/30 px-1.5 py-0.5 text-[10px] rounded">EXIT</span>
      </td>
      <td className="py-2 px-1 text-[var(--text-secondary)]">{trade.reason}</td>
      <td className="py-2 px-1 text-right text-[var(--text-secondary)]">{trade.price?.toFixed(4)}</td>
      <td className={`py-2 px-1 text-right font-bold ${pnlColor}`}>
        {(trade.pnl ?? 0) >= 0 ? '+' : ''}${trade.pnl?.toFixed(2)}
      </td>
      <td className="py-2 px-1 text-right text-[var(--text-secondary)]">
        ${trade.balance?.toFixed(2)}
      </td>
    </tr>
  );
}
