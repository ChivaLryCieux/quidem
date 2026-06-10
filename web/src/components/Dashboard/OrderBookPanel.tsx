import { useMarketStore } from '../../stores/marketStore';

export function OrderBookPanel() {
  const orderbook = useMarketStore((s) => s.market.orderbook);

  if (!orderbook) {
    return (
      <div className="halftone-card rounded-sm p-4 h-full">
        <div className="text-[10px] text-[#555] mb-4 font-mono tracking-widest">ORDER_BOOK</div>
        <div className="flex flex-col items-center justify-center py-12 text-[#333]">
          <div className="text-4xl mb-2">◇</div>
          <div className="text-xs font-mono">AWAITING_DATA...</div>
        </div>
      </div>
    );
  }

  const asks = orderbook.asks.slice(0, 10).reverse();
  const bids = orderbook.bids.slice(0, 10);

  const maxVol = Math.max(
    ...asks.map(([, v]) => v),
    ...bids.map(([, v]) => v)
  );

  return (
    <div className="halftone-card rounded-sm p-4 h-full">
      <div className="text-[10px] text-[#555] mb-4 font-mono tracking-widest">ORDER_BOOK</div>

      {/* Asks (卖单) */}
      <div className="space-y-0.5 mb-3">
        {asks.map(([price, vol], i) => (
          <div key={i} className="relative flex justify-between text-xs font-mono py-0.5">
            <div
              className="absolute inset-0 bg-[#e63946]/10"
              style={{ width: `${(vol / maxVol) * 100}%` }}
            />
            <span className="relative text-[#e63946] z-10">{price.toFixed(2)}</span>
            <span className="relative text-[#666] z-10">{vol.toFixed(3)}</span>
          </div>
        ))}
      </div>

      {/* Spread */}
      <div className="text-center text-[10px] text-[#444] py-2 border-y border-[#222] font-mono">
        {orderbook.asks[0] && orderbook.bids[0] && (
          <>
            SPREAD: {((orderbook.asks[0][0] - orderbook.bids[0][0]) / orderbook.bids[0][0] * 100).toFixed(4)}%
          </>
        )}
      </div>

      {/* Bids (买单) */}
      <div className="space-y-0.5 mt-3">
        {bids.map(([price, vol], i) => (
          <div key={i} className="relative flex justify-between text-xs font-mono py-0.5">
            <div
              className="absolute inset-0 bg-white/5"
              style={{ width: `${(vol / maxVol) * 100}%` }}
            />
            <span className="relative text-[#888] z-10">{price.toFixed(2)}</span>
            <span className="relative text-[#666] z-10">{vol.toFixed(3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
