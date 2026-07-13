import { useWebSocket } from './hooks/useWebSocket';
import { useMarketStore } from './stores/marketStore';
import { Dashboard } from './components/Dashboard/Dashboard';

function App() {
  const { connected } = useWebSocket();
  const system = useMarketStore((s) => s.system);

  const hasError = system.status === 'exchange_error';
  const statusColor = hasError
    ? 'text-[var(--red)]'
    : system.status === 'running'
      ? 'text-[var(--green)]'
      : 'text-[var(--text-muted)]';

  return (
    <div className="min-h-screen bg-[var(--bg-page)] text-[var(--text-primary)]">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-[var(--border)] bg-[var(--bg-card)]">
        <div className="flex items-center gap-4">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-[var(--brand)] rounded flex items-center justify-center text-white font-bold text-sm">
              Q
            </div>
            <h1 className="text-lg font-bold tracking-wider text-[var(--text-primary)]">
              QUIDEM<span className="text-[var(--brand)]">_</span>CTA
            </h1>
          </div>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--border-strong)]" />

          {/* Symbol & Mode */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-[var(--text-secondary)] font-mono">
              {useMarketStore((s) => s.account.symbol)}
            </span>
            <span className={`text-xs px-2 py-0.5 font-mono tracking-wider ${
              useMarketStore((s) => s.account.mode) === 'Live'
                ? 'bg-[var(--brand)]/10 text-[var(--brand)] border border-[var(--brand)]/30'
                : 'bg-[var(--bg-subtle)] text-[var(--text-secondary)] border border-[var(--border)]'
            }`}>
              {useMarketStore((s) => s.account.mode).toUpperCase()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-6">
          {/* WebSocket Status */}
          <div className="flex items-center gap-2">
            <div className={`status-dot ${connected ? 'status-connected' : 'status-disconnected'}`} />
            <span className="text-xs font-mono text-[var(--text-secondary)]">
              WS:{connected ? 'OK' : 'OFF'}
            </span>
          </div>

          {/* Exchange Status */}
          <div className="flex items-center gap-2">
            <div className={`status-dot ${system.exchange_connected ? 'status-connected' : 'status-disconnected'}`} />
            <span className="text-xs font-mono text-[var(--text-secondary)]">
              EX:{system.exchange_connected ? 'OK' : 'OFF'}
            </span>
          </div>

          {/* Uptime */}
          <div className="text-xs font-mono text-[var(--text-muted)]">
            T+{formatUptime(system.uptime)}
          </div>

          {/* System Status */}
          <div className={`text-xs px-2 py-0.5 font-mono ${statusColor}`}>
            [{system.status.toUpperCase()}]
          </div>
        </div>
      </header>

      {/* Error Banner */}
      {hasError && (
        <div className="bg-[var(--brand)]/5 border-b border-[var(--brand)]/20 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="text-[var(--red)] text-lg">◈</span>
            <div>
              <div className="text-xs font-mono text-[var(--red)] tracking-wider">EXCHANGE_CONNECTION_FAILED</div>
              <div className="text-xs font-mono text-[var(--text-secondary)] mt-1">
                {system.error_message || 'Unable to connect to exchange. Web GUI is still running.'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="p-4">
        <Dashboard />
      </main>
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h${m.toString().padStart(2, '0')}m`;
}

export default App;
