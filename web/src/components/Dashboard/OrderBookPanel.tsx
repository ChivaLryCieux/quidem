import { useMarketStore } from '../../stores/marketStore';

export function OrderBookPanel() {
  const orderbook = useMarketStore((s) => s.market.orderbook);

  if (!orderbook) {
    return (
      <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4 h-full">
        <div className="text-sm text-gray-500 mb-3">盘口深度</div>
        <div className="text-center text-gray-600 py-8">等待数据...</div>
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
    <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4 h-full">
      <div className="text-sm text-gray-500 mb-3">盘口深度</div>

      {/* Asks (卖单) */}
      <div className="space-y-0.5 mb-2">
        {asks.map(([price, vol], i) => (
          <div key={i} className="relative flex justify-between text-xs font-mono">
            <div
              className="absolute inset-0 bg-red-900/20"
              style={{ width: `${(vol / maxVol) * 100}%` }}
            />
            <span className="relative text-red-400 z-10">{price.toFixed(2)}</span>
            <span className="relative text-gray-400 z-10">{vol.toFixed(2)}</span>
          </div>
        ))}
      </div>

      {/* Spread */}
      <div className="text-center text-xs text-gray-600 py-1 border-y border-gray-800">
        {orderbook.asks[0] && orderbook.bids[0] && (
          <>
            Spread: {((orderbook.asks[0][0] - orderbook.bids[0][0]) / orderbook.bids[0][0] * 100).toFixed(4)}%
          </>
        )}
      </div>

      {/* Bids (买单) */}
      <div className="space-y-0.5 mt-2">
        {bids.map(([price, vol], i) => (
          <div key={i} className="relative flex justify-between text-xs font-mono">
            <div
              className="absolute inset-0 bg-green-900/20"
              style={{ width: `${(vol / maxVol) * 100}%` }}
            />
            <span className="relative text-green-400 z-10">{price.toFixed(2)}</span>
            <span className="relative text-gray-400 z-10">{vol.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
