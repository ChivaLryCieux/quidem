import { useMarketStore } from '../../stores/marketStore';

export function PriceHeader() {
  const market = useMarketStore((s) => s.market);
  const account = useMarketStore((s) => s.account);
  const position = useMarketStore((s) => s.position);

  return (
    <div className="grid grid-cols-5 gap-3">
      {/* Price */}
      <div className="halftone-card halftone-red rounded-sm p-4">
        <div className="text-[10px] text-[#555] mb-2 font-mono tracking-widest">PRICE</div>
        <div className="text-2xl font-bold font-mono text-white">
          {market.price.toFixed(4)}
        </div>
        <div className={`text-xs font-mono mt-1 ${
          market.change_24h >= 0 ? 'text-[#2ecc71]' : 'text-[#e63946]'
        }`}>
          {market.change_24h >= 0 ? '▲' : '▼'} {Math.abs(market.change_24h).toFixed(2)}%
        </div>
      </div>

      {/* Balance */}
      <div className="halftone-card rounded-sm p-4">
        <div className="text-[10px] text-[#555] mb-2 font-mono tracking-widest">BALANCE</div>
        <div className="text-2xl font-bold font-mono text-[#e63946] text-glow-red">
          ${account.balance.toFixed(2)}
        </div>
        <div className="text-xs font-mono text-[#555] mt-1">{account.mode.toUpperCase()}</div>
      </div>

      {/* Unrealized PnL */}
      <div className="halftone-card rounded-sm p-4">
        <div className="text-[10px] text-[#555] mb-2 font-mono tracking-widest">UNREALIZED</div>
        <div className={`text-2xl font-bold font-mono ${
          position.unrealized_pnl >= 0 ? 'text-[#2ecc71] text-glow-green' : 'text-[#e63946] text-glow-red'
        }`}>
          {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
        </div>
        <div className="text-xs font-mono text-[#555] mt-1">
          {position.size !== 0
            ? `${position.size > 0 ? 'LONG' : 'SHORT'} ${Math.abs(position.size).toFixed(4)}`
            : 'FLAT'}
        </div>
      </div>

      {/* Funding Rate */}
      <div className="halftone-card rounded-sm p-4">
        <div className="text-[10px] text-[#555] mb-2 font-mono tracking-widest">FUNDING</div>
        <div className="text-2xl font-bold font-mono text-[#888]">
          {(market.funding_rate * 100).toFixed(4)}%
        </div>
        <div className="text-xs font-mono text-[#555] mt-1">
          BTC: <span className="text-[#888]">${market.btc_price.toFixed(0)}</span>
        </div>
      </div>

      {/* Position Info */}
      <div className="halftone-card rounded-sm p-4">
        <div className="text-[10px] text-[#555] mb-2 font-mono tracking-widest">POSITION</div>
        {position.size !== 0 ? (
          <>
            <div className="text-sm font-mono text-[#888]">
              <span className="text-[#555]">EP:</span> {position.entry_price.toFixed(4)}
            </div>
            <div className="flex gap-3 text-xs font-mono mt-2">
              <span className="text-[#e63946]">
                <span className="text-[#555]">SL:</span> {position.sl.toFixed(4)}
              </span>
              <span className="text-[#2ecc71]">
                <span className="text-[#555]">TP:</span> {position.tp.toFixed(4)}
              </span>
            </div>
          </>
        ) : (
          <div className="text-lg font-mono text-[#333]">—</div>
        )}
      </div>
    </div>
  );
}
