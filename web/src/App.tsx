import { useWebSocket } from './hooks/useWebSocket';
import { useMarketStore } from './stores/marketStore';
import { Dashboard } from './components/Dashboard/Dashboard';

function App() {
  const { connected } = useWebSocket();
  const system = useMarketStore((s) => s.system);

  return (
    <div className="min-h-screen bg-[#0f0f23] text-white">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-800 bg-[#16171d]">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🤖</span>
          <h1 className="text-xl font-bold text-cyan-400">Quidem CTA</h1>
          <span className="text-sm text-gray-500">|</span>
          <span className="text-sm text-gray-400">
            {useMarketStore((s) => s.account.symbol)}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded ${
            useMarketStore((s) => s.account.mode) === 'Live'
              ? 'bg-red-900/50 text-red-400'
              : 'bg-blue-900/50 text-blue-400'
          }`}>
            {useMarketStore((s) => s.account.mode)}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${
              connected ? 'bg-green-500 animate-pulse' : 'bg-red-500'
            }`} />
            <span className="text-xs text-gray-400">
              {connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <span className="text-xs text-gray-500">
            Uptime: {formatUptime(system.uptime)}
          </span>
        </div>
      </header>

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
  return `${h}h ${m}m`;
}

export default App;
