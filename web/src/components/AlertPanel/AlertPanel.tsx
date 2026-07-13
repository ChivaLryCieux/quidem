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
    <div className="card p-4">
      <div className="text-[10px] text-[var(--text-muted)] mb-4 font-mono tracking-widest">ALERT_LOG</div>

      {alerts.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl text-[var(--border-strong)] mb-2">◇</div>
          <div className="text-xs font-mono text-[var(--text-muted)]">NO_ALERTS</div>
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
    <div className="border border-[var(--brand)]/20 bg-[var(--brand)]/5 rounded p-3 hover:bg-[var(--brand)]/10 transition-colors">
      <div className="flex items-start gap-3">
        <span className="text-[var(--brand)] text-lg">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] text-[var(--text-muted)] font-mono">{time}</span>
            <span className="text-[10px] text-[var(--brand)] font-mono px-1.5 py-0.5 border border-[var(--brand)]/20 rounded">
              {alert.type}
            </span>
          </div>
          <div className="text-xs text-[var(--text-secondary)] font-mono truncate">{alert.message}</div>
        </div>
      </div>
    </div>
  );
}
