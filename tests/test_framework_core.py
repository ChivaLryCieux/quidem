import unittest

from core.engine.trader import TradeExecutor
from core.risk.manager import RiskManager
from core.strategy.analyzers import OrderBookAnalyzer


class DummyExchange:
    is_live = False

    def __init__(self):
        self.orders = []

    def get_precision_amount(self, amount, price):
        return round(amount, 3)

    def execute_order(self, side, amount, params=None):
        self.orders.append({"side": side, "amount": amount, "params": params or {}})
        return True


class DummyUI:
    def __init__(self):
        self.entries = []
        self.exits = []
        self.messages = []

    def log_msg(self, msg, level="info"):
        self.messages.append((level, msg))

    def log_entry(self, *args, **kwargs):
        self.entries.append((args, kwargs))

    def log_exit(self, *args, **kwargs):
        self.exits.append((args, kwargs))


class DummyBrain:
    state = "TEST"
    color = ""

    def __init__(self, signal=1, leverage=5.0):
        self.signal = signal
        self.leverage = leverage

    def get_entry_signal(self, analysis_data, current_price):
        return self.signal, self.leverage

    def analyze(self):
        return {"atr": 0.0, "reversal_factor": 0.0}


class RiskManagerTest(unittest.TestCase):
    def test_funding_rate_rejects_directional_carry_risk(self):
        risk = RiskManager()

        risky_long, long_msg = risk.check_funding_rate_risk(1, 0.001)
        risky_short, short_msg = risk.check_funding_rate_risk(-1, -0.001)
        safe, _ = risk.check_funding_rate_risk(1, -0.001)

        self.assertTrue(risky_long)
        self.assertIn("不做多", long_msg)
        self.assertTrue(risky_short)
        self.assertIn("不做空", short_msg)
        self.assertFalse(safe)

    def test_circuit_breaker_uses_margin_roi(self):
        risk = RiskManager()
        hours, message = risk.activate_circuit_breaker(net_pnl=-11, margin_used=100, now_ms=1_000)

        self.assertEqual(hours, 24)
        self.assertIn("暂停 24h", message)
        self.assertTrue(risk.is_in_cooldown(now_ms=1_000 + 60_000))


class MarketStructureTest(unittest.TestCase):
    def test_order_book_analyzer_returns_weighted_imbalance_and_spread(self):
        analyzer = OrderBookAnalyzer()
        orderbook = {
            "bids": [[99.0, 10.0], [98.5, 5.0]],
            "asks": [[101.0, 2.0], [101.5, 2.0]],
        }

        obi, spread = analyzer.analyze(orderbook)

        self.assertGreater(obi, 0)
        self.assertAlmostEqual(spread, 0.02)


class TradeExecutorTest(unittest.TestCase):
    def test_paper_entry_and_exit_updates_position_balance_and_orders(self):
        exchange = DummyExchange()
        ui = DummyUI()
        brain = DummyBrain(signal=1, leverage=5.0)
        trader = TradeExecutor(exchange, RiskManager(), ui, brain)
        trader.update_balance(100.0)

        analysis = {
            "atr": 0.0,
            "reversal_factor": 0.0,
            "macd_histogram": 0.0,
            "bb_middle": 100.0,
            "supertrend_value": 100.0,
        }
        trader._attempt_entry(analysis, price=100.0, funding_rate=0.0, timestamp=123)

        self.assertEqual(len(exchange.orders), 1)
        self.assertGreater(trader.position["size"], 0)
        self.assertEqual(trader.position["leverage"], 5.0)

        entry_balance = trader.balance
        trader.execute_exit("test", price=102.0)

        self.assertEqual(len(exchange.orders), 2)
        self.assertEqual(trader.position["size"], 0.0)
        self.assertGreater(trader.balance, entry_balance)
        self.assertEqual(len(ui.exits), 1)


if __name__ == "__main__":
    unittest.main()
