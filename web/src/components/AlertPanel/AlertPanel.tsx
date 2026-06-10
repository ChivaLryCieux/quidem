import { useMarketStore } from '../../stores/marketStore';
import type { AlertRecord } from '../../types';

export function AlertPanel() {
  const alerts = useMarketStore((s) => s.alerts);

  const typeIcon: Record<string, string> = {
    BOCPD: '🚨',
    KDJ: '📊',
    ADX: '🟣',
    MACD: '📈',
  };

  const typeColor: Record<string, string> = {
    BOCPD: 'border-red-800 bg-red-900/10',
    KDJ: 'border-yellow-800 bg-yellow-900/10',
    ADX: 'border-purple-800 bg-purple-900/10',
    MACD: 'border-cyan-800 bg-cyan-900/10',
  };

  return (
    <div className="bg-[#1a1a2e] rounded-lg border border-gray-800 p-4">
      <div className="text-sm text-gray-500 mb-3">告警历史</div>

      {alerts.length === 0 ? (
        <div className="text-center py-8 text-gray-600">
          <div className="text-2xl mb-2">🔕</div>
          <div>暂无告警</div>
        </div>
      ) : (
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {alerts.slice(0, 20).map((alert, i) => (
            <AlertRow key={i} alert={alert} icon={typeIcon[alert.type] || '⚠️'} color={typeColor[alert.type] || 'border-gray-800'} />
          ))}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert, icon, color }: { alert: AlertRecord; icon: string; color: string }) {
  const time = new Date(alert.time).toLocaleTimeString();

  return (
    <div className={`border rounded-lg p-2 ${color}`}>
      <div className="flex items-start gap-2">
        <span className="text-lg">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-400">{time}</div>
          <div className="text-sm truncate">{alert.message}</div>
        </div>
        <span className="text-xs text-gray-600 px-1.5 py-0.5 bg-gray-800 rounded">
          {alert.type}
        </span>
      </div>
    </div>
  );
}
