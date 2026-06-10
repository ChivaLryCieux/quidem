import { useMarketStore } from '../../stores/marketStore';

export function PriceHeader() {
  const market = useMarketStore((s) => s.market);
  const account = useMarketStore((s) => s.account);
  const position = useMarketStore((s) => s.position);

  const pnlColor = position.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400';
  const changeColor = market.change_24h >= 0 ? 'text-green-400' : 'text-red-400';

  return (
    <div className="grid grid-cols-5 gap-4">
      {/* Price */}
      <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
        <div className="text-xs text-gray-500 mb-1">当前价格</div>
        <div className="text-2xl font-bold font-mono text-white">
          {market.price.toFixed(4)}
        </div>
        <div className={`text-sm ${changeColor}`}>
          {market.change_24h >= 0 ? '+' : ''}{market.change_24h.toFixed(2)}%
        </div>
      </div>

      {/* Balance */}
      <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
        <div className="text-xs text-gray-500 mb-1">账户余额</div>
        <div className="text-2xl font-bold font-mono text-cyan-400">
          ${account.balance.toFixed(2)}
        </div>
        <div className="text-sm text-gray-400">{account.mode}</div>
      </div>

      {/* Unrealized PnL */}
      <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
        <div className="text-xs text-gray-500 mb-1">浮动盈亏</div>
        <div className={`text-2xl font-bold font-mono ${pnlColor}`}>
          {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
        </div>
        <div className="text-sm text-gray-400">
          {position.size !== 0
            ? `${position.size > 0 ? 'LONG' : 'SHORT'} ${Math.abs(position.size).toFixed(4)}`
            : '无持仓'}
        </div>
      </div>

      {/* Funding Rate */}
      <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
        <div className="text-xs text-gray-500 mb-1">资金费率</div>
        <div className="text-2xl font-bold font-mono text-yellow-400">
          {(market.funding_rate * 100).toFixed(4)}%
        </div>
        <div className="text-sm text-gray-400">BTC: ${market.btc_price.toFixed(0)}</div>
      </div>

      {/* Position Info */}
      <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
        <div className="text-xs text-gray-500 mb-1">持仓信息</div>
        {position.size !== 0 ? (
          <>
            <div className="text-lg font-bold font-mono text-white">
              Entry: {position.entry_price.toFixed(4)}
            </div>
            <div className="flex gap-2 text-xs mt-1">
              <span className="text-red-400">SL: {position.sl.toFixed(4)}</span>
              <span className="text-green-400">TP: {position.tp.toFixed(4)}</span>
            </div>
          </>
        ) : (
          <div className="text-lg text-gray-500">-</div>
        )}
      </div>
    </div>
  );
}
