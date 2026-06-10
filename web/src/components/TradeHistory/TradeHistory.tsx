import { useMarketStore } from '../../stores/marketStore';
import type { TradeRecord } from '../../types';

export function TradeHistory() {
  const trades = useMarketStore((s) => s.trades);

  return (
    <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
      <div className="text-sm text-gray-500 mb-3">交易历史</div>

      {trades.length === 0 ? (
        <div className="text-center py-8 text-gray-600">
          <div className="text-2xl mb-2">📋</div>
          <div>暂无交易记录</div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 px-1">时间</th>
                <th className="text-left py-2 px-1">类型</th>
                <th className="text-left py-2 px-1">方向</th>
                <th className="text-right py-2 px-1">价格</th>
                <th className="text-right py-2 px-1">盈亏</th>
                <th className="text-right py-2 px-1">余额</th>
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
  const time = new Date(trade.time).toLocaleTimeString();

  if (trade.type === 'entry') {
    return (
      <tr className="border-b border-gray-800/50 hover:bg-gray-800/20">
        <td className="py-1.5 px-1 text-gray-400 font-mono">{time}</td>
        <td className="py-1.5 px-1">
          <span className="px-1.5 py-0.5 rounded bg-blue-900/30 text-blue-400">开仓</span>
        </td>
        <td className="py-1.5 px-1">
          <span className={trade.side === 'LONG' ? 'text-green-400' : 'text-red-400'}>
            {trade.side}
          </span>
        </td>
        <td className="py-1.5 px-1 text-right font-mono">{trade.price?.toFixed(4)}</td>
        <td className="py-1.5 px-1 text-right text-gray-500">-</td>
        <td className="py-1.5 px-1 text-right text-gray-500">-</td>
      </tr>
    );
  }

  const pnlColor = (trade.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400';

  return (
    <tr className="border-b border-gray-800/50 hover:bg-gray-800/20">
      <td className="py-1.5 px-1 text-gray-400 font-mono">{time}</td>
      <td className="py-1.5 px-1">
        <span className="px-1.5 py-0.5 rounded bg-yellow-900/30 text-yellow-400">平仓</span>
      </td>
      <td className="py-1.5 px-1 text-gray-400">{trade.reason}</td>
      <td className="py-1.5 px-1 text-right font-mono">{trade.price?.toFixed(4)}</td>
      <td className={`py-1.5 px-1 text-right font-mono font-bold ${pnlColor}`}>
        {(trade.pnl ?? 0) >= 0 ? '+' : ''}${trade.pnl?.toFixed(2)}
      </td>
      <td className="py-1.5 px-1 text-right font-mono text-cyan-400">
        ${trade.balance?.toFixed(2)}
      </td>
    </tr>
  );
}
