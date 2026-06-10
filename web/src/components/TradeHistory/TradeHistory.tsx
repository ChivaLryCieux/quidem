import { useMarketStore } from '../../stores/marketStore';
import type { TradeRecord } from '../../types';

export function TradeHistory() {
  const trades = useMarketStore((s) => s.trades);

  return (
    <div className="halftone-card rounded-sm p-4">
      <div className="text-[10px] text-[#555] mb-4 font-mono tracking-widest">TRADE_LOG</div>

      {trades.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl text-[#222] mb-2">◇</div>
          <div className="text-xs font-mono text-[#333]">NO_TRADES</div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-[#444] border-b border-[#222]">
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
      <tr className="border-b border-[#1a1a1a] hover:bg-white/[0.02] transition-colors">
        <td className="py-2 px-1 text-[#555]">{time}</td>
        <td className="py-2 px-1">
          <span className="text-[#888] border border-[#333] px-1.5 py-0.5 text-[10px]">ENTRY</span>
        </td>
        <td className="py-2 px-1">
          <span className={trade.side === 'LONG' ? 'text-[#2ecc71]' : 'text-[#e63946]'}>
            {trade.side}
          </span>
        </td>
        <td className="py-2 px-1 text-right text-[#888]">{trade.price?.toFixed(4)}</td>
        <td className="py-2 px-1 text-right text-[#333]">—</td>
        <td className="py-2 px-1 text-right text-[#333]">—</td>
      </tr>
    );
  }

  const pnlColor = (trade.pnl ?? 0) >= 0 ? 'text-[#2ecc71]' : 'text-[#e63946]';

  return (
    <tr className="border-b border-[#1a1a1a] hover:bg-white/[0.02] transition-colors">
      <td className="py-2 px-1 text-[#555]">{time}</td>
      <td className="py-2 px-1">
        <span className="text-[#e63946] border border-[#e63946]/30 px-1.5 py-0.5 text-[10px]">EXIT</span>
      </td>
      <td className="py-2 px-1 text-[#666]">{trade.reason}</td>
      <td className="py-2 px-1 text-right text-[#888]">{trade.price?.toFixed(4)}</td>
      <td className={`py-2 px-1 text-right font-bold ${pnlColor}`}>
        {(trade.pnl ?? 0) >= 0 ? '+' : ''}${trade.pnl?.toFixed(2)}
      </td>
      <td className="py-2 px-1 text-right text-[#888]">
        ${trade.balance?.toFixed(2)}
      </td>
    </tr>
  );
}
