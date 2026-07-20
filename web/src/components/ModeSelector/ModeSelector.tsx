import { useEffect, useRef, useState } from 'react';
import { useMarketStore } from '../../stores/marketStore';
import type { TradingMode } from '../../types';

// 模式显示配置
const MODE_CONFIG: Record<TradingMode, { label: string; badge: string }> = {
  dashboard: {
    label: 'DASHBOARD',
    badge: 'bg-[var(--bg-subtle)] text-[var(--text-secondary)] border border-[var(--border)]',
  },
  paper: {
    label: 'PAPER',
    badge: 'bg-[var(--brand)]/10 text-[var(--brand)] border border-[var(--brand)]/30',
  },
  live: {
    label: 'LIVE',
    badge: 'bg-[var(--red)]/10 text-[var(--red)] border border-[var(--red)]/40',
  },
};

// 模式等级，用于单向升级过滤
const MODE_LEVEL: Record<TradingMode, number> = {
  dashboard: 0,
  paper: 1,
  live: 2,
};

const ALL_MODES: TradingMode[] = ['dashboard', 'paper', 'live'];

export function ModeSelector() {
  const tradingMode = useMarketStore((s) => s.system.trading_mode);
  const positionSize = useMarketStore((s) => s.position.size);
  const modeSwitching = useMarketStore((s) => s.modeSwitching);
  const modeSwitchError = useMarketStore((s) => s.modeSwitchError);
  const switchMode = useMarketStore((s) => s.switchMode);

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击外部关闭下拉
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const hasPosition = positionSize !== 0;
  const currentConfig = MODE_CONFIG[tradingMode];

  const handleSelect = async (target: TradingMode) => {
    // 同级或降级：仅关闭下拉
    if (MODE_LEVEL[target] <= MODE_LEVEL[tradingMode]) {
      setOpen(false);
      return;
    }

    // LIVE 二次确认（资金安全）
    if (target === 'live') {
      const ok = window.confirm(
        '⚠️ 即将切换到实盘 (LIVE) 模式\n\n实盘模式将使用真实资金进行交易。\n请确认你已配置 BINANCE_API_KEY 并了解风险。',
      );
      if (!ok) return;
    }

    setOpen(false);
    await switchMode(target as 'paper' | 'live');
  };

  const isDisabled = hasPosition || modeSwitching;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => !isDisabled && setOpen((v) => !v)}
        disabled={isDisabled}
        title={
          hasPosition
            ? '当前有持仓，禁止切换模式'
            : modeSwitching
              ? '模式切换中...'
              : '点击切换交易模式'
        }
        className={`text-xs px-2 py-0.5 font-mono tracking-wider ${currentConfig.badge} ${
          isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:opacity-80'
        } transition-opacity flex items-center gap-1`}
      >
        {modeSwitching ? (
          <span className="inline-block w-2 h-2 border border-current border-t-transparent rounded-full animate-spin" />
        ) : null}
        {currentConfig.label}
        {!isDisabled ? <span className="text-[8px]">▾</span> : null}
      </button>

      {/* 下拉菜单 */}
      {open && !isDisabled ? (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] card p-1 shadow-lg">
          <div className="px-2 py-1 text-[10px] font-mono text-[var(--text-muted)] tracking-wider border-b border-[var(--border)] mb-1">
            切换交易模式
          </div>
          {ALL_MODES.map((mode) => {
            const config = MODE_CONFIG[mode];
            const isCurrent = mode === tradingMode;
            const isUpgrade = MODE_LEVEL[mode] > MODE_LEVEL[tradingMode];
            return (
              <button
                key={mode}
                type="button"
                onClick={() => handleSelect(mode)}
                disabled={isCurrent}
                className={`w-full text-left px-2 py-1.5 text-xs font-mono flex items-center justify-between rounded transition-colors ${
                  isCurrent
                    ? 'bg-[var(--bg-subtle)] text-[var(--text-muted)] cursor-default'
                    : 'hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] cursor-pointer'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                    mode === 'live' ? 'bg-[var(--red)]' :
                    mode === 'paper' ? 'bg-[var(--brand)]' :
                    'bg-[var(--text-muted)]'
                  }`} />
                  {config.label}
                </span>
                <span className="text-[9px] text-[var(--text-muted)]">
                  {isCurrent ? '●' : isUpgrade ? '↑' : '—'}
                </span>
              </button>
            );
          })}
          <div className="px-2 py-1 mt-1 border-t border-[var(--border)] text-[9px] font-mono text-[var(--text-muted)] leading-relaxed">
            仅允许单向升级
            <br />
            有持仓时禁止切换
          </div>
        </div>
      ) : null}

      {/* 错误提示 */}
      {modeSwitchError ? (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[200px] card p-2 text-[10px] font-mono text-[var(--red)] border-[var(--red)]/30">
          {modeSwitchError}
        </div>
      ) : null}
    </div>
  );
}
