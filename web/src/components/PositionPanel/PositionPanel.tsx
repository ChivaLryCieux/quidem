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
    <div className="halftone-card rounded-sm p-4">
      <div className="text-[10px] text-[#555] mb-4 font-mono tracking-widest">POSITION</div>

      {!hasPosition ? (
        <div className="text-center py-8">
          <div className="text-4xl text-[#222] mb-2">◇</div>
          <div className="text-xs font-mono text-[#333]">NO_POSITION</div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Direction */}
          <div className={`text-center py-3 border font-mono ${
            isLong
              ? 'border-[#2ecc71]/30 text-[#2ecc71] bg-[#2ecc71]/5'
              : 'border-[#e63946]/30 text-[#e63946] bg-[#e63946]/5'
          }`}>
            <span className="text-lg font-bold tracking-wider">
              {isLong ? '▲ LONG' : '▼ SHORT'}
            </span>
            <span className="text-sm ml-2 opacity-70">{position.leverage}x</span>
          </div>

          {/* Entry / Current */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#0a0a0a] border border-[#222] p-2">
              <div className="text-[10px] text-[#444] font-mono">ENTRY</div>
              <div className="text-sm font-mono text-[#888]">{position.entry_price.toFixed(4)}</div>
            </div>
            <div className="bg-[#0a0a0a] border border-[#222] p-2">
              <div className="text-[10px] text-[#444] font-mono">MARK</div>
              <div className="text-sm font-mono text-[#888]">{market.price.toFixed(4)}</div>
            </div>
          </div>

          {/* PnL */}
          <div className={`text-center py-3 border ${
            position.unrealized_pnl >= 0
              ? 'border-[#2ecc71]/20 bg-[#2ecc71]/5'
              : 'border-[#e63946]/20 bg-[#e63946]/5'
          }`}>
            <div className={`text-xl font-bold font-mono ${
              position.unrealized_pnl >= 0 ? 'text-[#2ecc71] text-glow-green' : 'text-[#e63946] text-glow-red'
            }`}>
              {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
            </div>
            <div className={`text-xs font-mono mt-1 ${
              pnlPct >= 0 ? 'text-[#2ecc71]/70' : 'text-[#e63946]/70'
            }`}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </div>
          </div>

          {/* SL / TP */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#0a0a0a] border border-[#e63946]/20 p-2">
              <div className="text-[10px] text-[#e63946] font-mono">STOP_LOSS</div>
              <div className="text-sm font-mono text-[#888]">{position.sl.toFixed(4)}</div>
              <div className="text-[10px] text-[#555] font-mono">-{slDist.toFixed(2)}%</div>
            </div>
            <div className="bg-[#0a0a0a] border border-[#2ecc71]/20 p-2">
              <div className="text-[10px] text-[#2ecc71] font-mono">TAKE_PROFIT</div>
              <div className="text-sm font-mono text-[#888]">{position.tp.toFixed(4)}</div>
              <div className="text-[10px] text-[#555] font-mono">+{tpDist.toFixed(2)}%</div>
            </div>
          </div>

          {/* Size */}
          <div className="flex justify-between items-center text-xs font-mono pt-2 border-t border-[#222]">
            <span className="text-[#555]">SIZE</span>
            <span className="text-[#888]">{Math.abs(position.size).toFixed(4)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
