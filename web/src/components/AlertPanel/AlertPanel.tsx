import { useMarketStore } from '../../stores/marketStore';
import type { AlertRecord } from '../../types';

export function AlertPanel() {
  const alerts = useMarketStore((s) => s.alerts);

  const typeIcon: Record<string, string> = {
    BOCPD: '◈',
    KDJ: '◆',
    ADX: '◇',
    MACD: '▣',
  };

  return (
    <div className="halftone-card rounded-sm p-4">
      <div className="text-[10px] text-[#555] mb-4 font-mono tracking-widest">ALERT_LOG</div>

      {alerts.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl text-[#222] mb-2">◇</div>
          <div className="text-xs font-mono text-[#333]">NO_ALERTS</div>
        </div>
      ) : (
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {alerts.slice(0, 20).map((alert, i) => (
            <AlertRow
              key={i}
              alert={alert}
              icon={typeIcon[alert.type] || '◈'}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert, icon }: { alert: AlertRecord; icon: string }) {
  const time = new Date(alert.time).toLocaleTimeString('en-US', { hour12: false });

  return (
    <div className="border border-[#e63946]/20 bg-[#e63946]/5 p-3 hover:bg-[#e63946]/10 transition-colors">
      <div className="flex items-start gap-3">
        <span className="text-[#e63946] text-lg">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] text-[#444] font-mono">{time}</span>
            <span className="text-[10px] text-[#e63946] font-mono px-1.5 py-0.5 border border-[#e63946]/20">
              {alert.type}
            </span>
          </div>
          <div className="text-xs text-[#888] font-mono truncate">{alert.message}</div>
        </div>
      </div>
    </div>
  );
}
