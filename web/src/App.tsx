import { useWebSocket } from './hooks/useWebSocket';
import { useMarketStore } from './stores/marketStore';
import { Dashboard } from './components/Dashboard/Dashboard';

function App() {
  const { connected } = useWebSocket();
  const system = useMarketStore((s) => s.system);

  const hasError = system.status === 'exchange_error';
  const statusColor = hasError
    ? 'text-[#e63946]'
    : system.status === 'running'
      ? 'text-[#2ecc71]'
      : 'text-[#555]';

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-[#f0f0f0]">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-[#222] bg-[#111] relative scanline">
        <div className="flex items-center gap-4">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-[#e63946] rounded flex items-center justify-center text-white font-bold text-sm">
              Q
            </div>
            <h1 className="text-lg font-bold tracking-wider text-white">
              QUIDEM<span className="text-[#e63946]">_</span>CTA
            </h1>
          </div>

          {/* Divider */}
          <div className="w-px h-6 bg-[#333]" />

          {/* Symbol & Mode */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-[#888] font-mono">
              {useMarketStore((s) => s.account.symbol)}
            </span>
            <span className={`text-xs px-2 py-0.5 font-mono tracking-wider ${
              useMarketStore((s) => s.account.mode) === 'Live'
                ? 'bg-[#e63946]/20 text-[#e63946] border border-[#e63946]/30'
                : 'bg-white/5 text-[#888] border border-[#333]'
            }`}>
              {useMarketStore((s) => s.account.mode).toUpperCase()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-6">
          {/* WebSocket Status */}
          <div className="flex items-center gap-2">
            <div className={`status-dot ${connected ? 'status-connected' : 'status-disconnected'}`} />
            <span className="text-xs font-mono text-[#888]">
              WS:{connected ? 'OK' : 'OFF'}
            </span>
          </div>

          {/* Exchange Status */}
          <div className="flex items-center gap-2">
            <div className={`status-dot ${system.exchange_connected ? 'status-connected' : 'status-disconnected'}`} />
            <span className="text-xs font-mono text-[#888]">
              EX:{system.exchange_connected ? 'OK' : 'OFF'}
            </span>
          </div>

          {/* Uptime */}
          <div className="text-xs font-mono text-[#555]">
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
        <div className="bg-[#e63946]/10 border-b border-[#e63946]/30 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="text-[#e63946] text-lg">◈</span>
            <div>
              <div className="text-xs font-mono text-[#e63946] tracking-wider">EXCHANGE_CONNECTION_FAILED</div>
              <div className="text-xs font-mono text-[#888] mt-1">
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
