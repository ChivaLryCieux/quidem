"""
BOCPD on SOLUSDT 5m — v4 (pure BOCPD + paper trading simulation)

Trading logic:
  - Start with $100 capital, no position.
  - At the FIRST changepoint:
      * Look back to find the most recent extremum BEFORE the changepoint.
      * If it was a local minimum → go LONG (price was at bottom, expect rise).
      * If it was a local maximum → go SHORT (price was at top, expect fall).
  - At each SUBSEQUENT changepoint: close current position, reverse direction.
  - After the last changepoint: hold until the final bar, then close.
  - Position sizing: deploy full equity each trade (no leverage).
  - No fees modelled (paper trading baseline).
"""

import sys
import numpy as np
import pandas as pd
import requests
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
from scipy.signal import argrelextrema
from scipy.special import gammaln
import warnings
warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────
# Proxy
# ──────────────────────────────────────────────────────────────
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 7890
PROXIES = {
    "http":  f"http://{PROXY_HOST}:{PROXY_PORT}",
    "https": f"http://{PROXY_HOST}:{PROXY_PORT}",
}


# ──────────────────────────────────────────────────────────────
# 1. Data
# ──────────────────────────────────────────────────────────────
def fetch_klines(symbol="SOLUSDT", interval="5m", limit=1000):
    url    = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    session = requests.Session()
    session.trust_env = False
    for label, kw in [
        ("proxy",  dict(proxies=PROXIES, timeout=15, verify=True)),
        ("direct", dict(proxies={"http": None, "https": None}, timeout=15)),
    ]:
        try:
            print(f"  Trying {label} ...")
            r = session.get(url, params=params, **kw)
            r.raise_for_status()
            print(f"  {label.capitalize()} OK.")
            return _parse(r)
        except Exception as e:
            print(f"  {label.capitalize()} failed: {type(e).__name__}: {e}")
    print("\n[ERROR] Cannot reach Binance. Check proxy / network.")
    sys.exit(1)


def _parse(resp):
    df = pd.DataFrame(resp.json(), columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_base","taker_quote","ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    return df.set_index("open_time")


# ──────────────────────────────────────────────────────────────
# 2. Signal
# ──────────────────────────────────────────────────────────────
def build_signal(close, ema_span=5):
    log_ret  = np.diff(np.log(np.maximum(close, 1e-10)))
    ema      = pd.Series(log_ret).ewm(span=ema_span, adjust=False).mean().values
    ema_lag  = np.concatenate([[0.0], ema[:-1]])
    return log_ret - ema_lag


# ──────────────────────────────────────────────────────────────
# 3. BOCPD
# ──────────────────────────────────────────────────────────────
def _st_logpdf(x, alpha, beta, kappa, mu):
    nu = 2.0 * alpha
    s2 = beta * (kappa + 1.0) / (alpha * kappa)
    return (gammaln((nu + 1.0) / 2.0) - gammaln(nu / 2.0)
            - 0.5 * np.log(np.pi * nu * s2)
            - (nu + 1.0) / 2.0 * np.log(1.0 + (x - mu)**2 / (nu * s2)))


def bocpd(signal, hazard_lambda=30,
          mu0=0.0, kappa0=0.1, alpha0=2.0, beta0=0.0001):
    T = len(signal)
    H = 1.0 / hazard_lambda
    log_R = np.array([0.0])
    mu_a  = np.array([mu0]);    k_a = np.array([kappa0])
    a_a   = np.array([alpha0]); b_a = np.array([beta0])
    mode_rl = []
    for t in range(T):
        x  = signal[t]
        lp = _st_logpdf(x, a_a, b_a, k_a, mu_a)
        lj = log_R + lp
        nR = np.concatenate([[np.logaddexp.reduce(lj) + np.log(H)],
                              lj + np.log(1.0 - H)])
        nR -= np.logaddexp.reduce(nR)
        log_R = nR
        mode_rl.append(int(np.argmax(np.exp(log_R))))
        kn = k_a + 1.0;  mn = (k_a * mu_a + x) / kn
        an = a_a + 0.5;  bn = b_a + k_a * (x - mu_a)**2 / (2.0 * kn)
        mu_a = np.concatenate([[mu0],    mn])
        k_a  = np.concatenate([[kappa0], kn])
        a_a  = np.concatenate([[alpha0], an])
        b_a  = np.concatenate([[beta0],  bn])
    mode_rl = np.array(mode_rl)
    return np.concatenate([[mode_rl[0]], mode_rl])


def detect_changepoints(mode_rl, drop_thresh=8, min_gap=5):
    drops = np.where(np.diff(mode_rl) < -drop_thresh)[0] + 1
    out, last = [], -min_gap
    for d in drops:
        if d - last >= min_gap:
            out.append(d)
            last = d
    return np.array(out, dtype=int)


# ──────────────────────────────────────────────────────────────
# 4. Extrema
# ──────────────────────────────────────────────────────────────
def find_extrema(close, order=5):
    idx_max = argrelextrema(close, np.greater_equal, order=order)[0]
    idx_min = argrelextrema(close, np.less_equal,    order=order)[0]
    return idx_max, idx_min


# ──────────────────────────────────────────────────────────────
# 5. Paper trading simulation
# ──────────────────────────────────────────────────────────────
def run_simulation(close, bocpd_cps, idx_max, idx_min,
                   initial_capital=100.0):
    """
    Rules (all decisions use only information available at the
    changepoint bar — no look-ahead):

    At changepoint cp_i:
      1. Close any open position at close[cp_i].
      2. Find the most recent extremum strictly before cp_i.
         - If it was a local minimum  → enter LONG  at close[cp_i].
         - If it was a local maximum  → enter SHORT at close[cp_i].
      3. Repeat until no more changepoints.
    After the last CP: hold until close[-1], then close.

    Returns
    -------
    trades : list of dicts with per-trade details
    equity : ndarray of equity curve (same length as close)
    """
    if len(bocpd_cps) == 0:
        return [], np.full(len(close), initial_capital)

    # Build sorted extrema lookup: (bar_index, 'max'|'min')
    ext_max_set = set(idx_max.tolist())
    ext_min_set = set(idx_min.tolist())
    all_ext = sorted(
        [(i, "max") for i in idx_max] + [(i, "min") for i in idx_min],
        key=lambda x: x[0]
    )

    def last_extremum_before(bar):
        """Return type of the most recent extremum strictly before `bar`."""
        result = None
        for idx, kind in all_ext:
            if idx < bar:
                result = kind
            else:
                break
        return result   # None if no extremum exists before bar

    equity   = np.full(len(close), np.nan)
    trades   = []
    capital  = initial_capital
    position = None   # None | 'long' | 'short'
    entry_price  = None
    entry_bar    = None
    entry_equity = None

    equity[0] = capital

    # We'll process changepoints as decision points
    # Between CPs, equity evolves with the open position
    decision_bars = list(bocpd_cps) + [len(close) - 1]   # last bar = forced close

    prev_bar = 0
    for k, bar in enumerate(decision_bars):
        bar = int(bar)
        is_last = (k == len(decision_bars) - 1)

        # ── Fill equity between prev_bar and bar ──
        for b in range(prev_bar, bar + 1):
            if position is None:
                equity[b] = capital
            elif position == "long":
                equity[b] = capital * (close[b] / entry_price)
            else:  # short
                equity[b] = capital * (2.0 - close[b] / entry_price)

        # ── Close open position at this bar ──
        if position is not None:
            exit_price = close[bar]
            if position == "long":
                pnl_pct = (exit_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - exit_price) / entry_price
            pnl_usd = capital * pnl_pct
            capital += pnl_usd
            trades.append({
                "entry_bar":   entry_bar,
                "exit_bar":    bar,
                "entry_price": entry_price,
                "exit_price":  exit_price,
                "direction":   position,
                "pnl_pct":     pnl_pct * 100,
                "pnl_usd":     pnl_usd,
                "equity_after": capital,
            })
            position = None

        # ── Open new position (unless this is the forced final close) ──
        if not is_last:
            ext_kind = last_extremum_before(bar)
            if ext_kind == "min":
                position    = "long"
            elif ext_kind == "max":
                position    = "short"
            else:
                # No extremum seen yet — skip this CP, stay flat
                position = None

            if position is not None:
                entry_price  = close[bar]
                entry_bar    = bar
                entry_equity = capital

        prev_bar = bar + 1

    # Fill any trailing NaN (shouldn't happen but safety net)
    for b in range(len(close)):
        if np.isnan(equity[b]):
            equity[b] = capital

    return trades, equity


# ──────────────────────────────────────────────────────────────
# 6. Plot
# ──────────────────────────────────────────────────────────────
def plot_result(df, signal, mode_rl, bocpd_cps,
                idx_max, idx_min, trades, equity, params):
    close = df["close"].values
    times = np.arange(len(close))

    bg, fg   = "#0d1117", "#e6edf3"
    green    = "#3fb950";  red    = "#f85149"
    yellow   = "#e3b341";  blue   = "#58a6ff"
    orange   = "#f0883e";  purple = "#bc8cff"
    teal     = "#39d353";  pink   = "#ff7b72"

    fig = plt.figure(figsize=(26, 20), facecolor=bg)
    gs  = GridSpec(5, 1, figure=fig,
                   height_ratios=[3, 0.7, 0.7, 0.9, 1.4],
                   hspace=0.07)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax4 = fig.add_subplot(gs[3], sharex=ax1)
    ax5 = fig.add_subplot(gs[4], sharex=ax1)

    for ax in [ax1, ax2, ax3, ax4, ax5]:
        ax.set_facecolor(bg)
        ax.tick_params(colors=fg, labelsize=8)
        for sp in ax.spines.values(): sp.set_color("#30363d")
        ax.yaxis.label.set_color(fg)

    colors_bar = [green if df["close"].iloc[i] >= df["open"].iloc[i] else red
                  for i in range(len(df))]

    # ── Panel 1: price + trades ──
    ax1.bar(times, df["high"].values - df["low"].values,
            bottom=df["low"].values, width=0.7,
            color=colors_bar, alpha=0.18, zorder=1)
    ax1.plot(times, close, color=blue, lw=0.8, alpha=0.9, zorder=2, label="Close")

    for cp_i in bocpd_cps:
        ax1.axvspan(cp_i - 1.5, cp_i + 1.5, color=yellow, alpha=0.12, zorder=0)
        ax1.axvline(x=cp_i, color=yellow, alpha=0.85, lw=1.2,
                    linestyle="--", zorder=3)

    ax1.scatter(times[idx_max], close[idx_max],
                marker="^", color=green, s=60, zorder=5,
                label=f"Local max ({len(idx_max)})")
    for i in idx_max:
        ax1.annotate(f"{close[i]:.2f}", (times[i], close[i]),
                     textcoords="offset points", xytext=(0, 9),
                     fontsize=5, color=green, ha="center", zorder=6)

    ax1.scatter(times[idx_min], close[idx_min],
                marker="v", color=red, s=60, zorder=5,
                label=f"Local min ({len(idx_min)})")
    for i in idx_min:
        ax1.annotate(f"{close[i]:.2f}", (times[i], close[i]),
                     textcoords="offset points", xytext=(0, -11),
                     fontsize=5, color=red, ha="center", zorder=6)

    # Draw trade entry/exit arrows on price panel
    for t in trades:
        eb, xb = t["entry_bar"], t["exit_bar"]
        ep, xp = t["entry_price"], t["exit_price"]
        is_long = t["direction"] == "long"
        win     = t["pnl_usd"] >= 0
        c_arrow = teal if win else pink

        # Entry marker
        ax1.annotate(
            "▲ L" if is_long else "▼ S",
            xy=(eb, ep),
            fontsize=7, color=c_arrow, ha="center", va="top" if is_long else "bottom",
            fontweight="bold", zorder=8,
            xytext=(0, -14 if is_long else 14),
            textcoords="offset points"
        )
        # Shaded trade region
        ax1.axvspan(eb, xb,
                    color=(teal if is_long else pink),
                    alpha=0.06, zorder=0)

    handles, labels = ax1.get_legend_handles_labels()
    handles.append(Line2D([0], [0], color=yellow, lw=1.5, linestyle="--"))
    ext_set   = set(idx_max.tolist()) | set(idx_min.tolist())
    n_overlap = sum(1 for cp in bocpd_cps
                    if any(abs(cp - e) <= 2 for e in ext_set))
    pct = 100 * n_overlap / max(len(bocpd_cps), 1)
    labels.append(f"BOCPD CP ({len(bocpd_cps)} | {n_overlap} within ±2 bars = {pct:.0f}%)")
    ax1.legend(handles=handles, labels=labels, loc="upper left",
               facecolor="#161b22", edgecolor="#30363d",
               labelcolor=fg, fontsize=7.5)

    lam = params["hazard_lambda"]
    ax1.set_ylabel("Price (USDT)", color=fg)
    ax1.set_title(
        f"SOLUSDT 5m  |  BOCPD (pure)  |  λ={lam}  κ₀={params['kappa0']}  "
        f"ema={params['ema_span']}  drop={params['drop_thresh']}  "
        f"gap={params['min_gap']}  ext_order={params['extrema_order']}  |  {len(df)} bars",
        color=fg, fontsize=11, pad=10)
    ax1.grid(axis="y", color="#21262d", lw=0.5)
    plt.setp(ax1.get_xticklabels(), visible=False)

    # ── Panel 2: volume ──
    ax2.bar(times, df["volume"].values, color=colors_bar, alpha=0.6, width=0.8)
    ax2.set_ylabel("Volume", color=fg, fontsize=9)
    ax2.grid(axis="y", color="#21262d", lw=0.5)
    for cp_i in bocpd_cps:
        ax2.axvline(x=cp_i, color=yellow, alpha=0.4, lw=0.9, linestyle="--")
    plt.setp(ax2.get_xticklabels(), visible=False)

    # ── Panel 3: de-trended signal ──
    sig_plot = np.concatenate([[0.0], signal])
    ax3.plot(times, sig_plot, color=purple, lw=0.7, alpha=0.8,
             label=f"EMA-detrended log-return (span={params['ema_span']})")
    ax3.axhline(0, color="#30363d", lw=0.8)
    ax3.fill_between(times, sig_plot, 0, where=sig_plot >= 0, alpha=0.15, color=green)
    ax3.fill_between(times, sig_plot, 0, where=sig_plot <  0, alpha=0.15, color=red)
    for cp_i in bocpd_cps:
        ax3.axvline(x=cp_i, color=yellow, alpha=0.4, lw=0.9, linestyle="--")
    ax3.set_ylabel("Signal", color=fg, fontsize=9)
    ax3.legend(loc="upper right", facecolor="#161b22",
               edgecolor="#30363d", labelcolor=fg, fontsize=7.5)
    ax3.grid(axis="y", color="#21262d", lw=0.5)
    plt.setp(ax3.get_xticklabels(), visible=False)

    # ── Panel 4: run-length mode ──
    ax4.plot(times, mode_rl, color=orange, lw=0.9, alpha=0.85,
             label="Run-length mode (MAP)")
    ax4.fill_between(times, mode_rl, alpha=0.12, color=orange)
    for cp_i in bocpd_cps:
        ax4.axvline(x=cp_i, color=yellow, alpha=0.5, lw=0.9, linestyle="--")
    ax4.set_ylabel("Run Length", color=fg, fontsize=9)
    ax4.legend(loc="upper right", facecolor="#161b22",
               edgecolor="#30363d", labelcolor=fg, fontsize=7.5)
    ax4.grid(axis="y", color="#21262d", lw=0.5)
    plt.setp(ax4.get_xticklabels(), visible=False)

    # ── Panel 5: equity curve ──
    final_eq   = equity[-1]
    total_pnl  = final_eq - 100.0
    total_ret  = total_pnl / 100.0 * 100.0
    eq_color   = teal if final_eq >= 100 else pink

    ax5.plot(times, equity, color=eq_color, lw=1.2, zorder=3,
             label=f"Equity  (start $100 → end ${final_eq:.2f})")
    ax5.fill_between(times, equity, 100,
                     where=equity >= 100, alpha=0.18, color=teal, zorder=2)
    ax5.fill_between(times, equity, 100,
                     where=equity <  100, alpha=0.18, color=pink,  zorder=2)
    ax5.axhline(100, color=fg, lw=0.7, linestyle=":", alpha=0.5)

    # Mark each trade close on equity curve
    for t in trades:
        xb = t["exit_bar"]
        eq_val = equity[xb]
        win = t["pnl_usd"] >= 0
        ax5.scatter(xb, eq_val, color=teal if win else pink,
                    s=55, zorder=6, linewidths=0)
        ax5.annotate(
            f"{'+' if win else ''}{t['pnl_usd']:.2f}",
            (xb, eq_val),
            textcoords="offset points",
            xytext=(0, 9 if win else -13),
            fontsize=6.5, color=teal if win else pink,
            ha="center", zorder=7
        )

    for cp_i in bocpd_cps:
        ax5.axvline(x=cp_i, color=yellow, alpha=0.35, lw=0.9, linestyle="--")

    ax5.set_ylabel("Equity (USD)", color=fg, fontsize=9)
    ret_str = f"+{total_ret:.1f}%" if total_ret >= 0 else f"{total_ret:.1f}%"
    ax5.legend(loc="upper left", facecolor="#161b22",
               edgecolor="#30363d", labelcolor=fg, fontsize=8)
    ax5.grid(axis="y", color="#21262d", lw=0.5)

    # Summary stats box
    n_wins  = sum(1 for t in trades if t["pnl_usd"] >= 0)
    n_total = len(trades)
    wr      = 100 * n_wins / max(n_total, 1)
    avg_w   = np.mean([t["pnl_usd"] for t in trades if t["pnl_usd"] >= 0]) if n_wins else 0
    avg_l   = np.mean([t["pnl_usd"] for t in trades if t["pnl_usd"] <  0]) if n_total - n_wins else 0
    stats_txt = (
        f"Trades: {n_total}   Win rate: {wr:.0f}%   "
        f"Avg win: ${avg_w:.2f}   Avg loss: ${avg_l:.2f}\n"
        f"Start: $100.00   End: ${final_eq:.2f}   "
        f"Total P&L: {'+'if total_pnl>=0 else ''}{total_pnl:.2f} USD  ({ret_str})"
    )
    ax5.text(0.01, 0.97, stats_txt,
             transform=ax5.transAxes,
             va="top", ha="left",
             fontsize=8.5, color=fg,
             bbox=dict(boxstyle="round,pad=0.4",
                       facecolor="#161b22", edgecolor="#30363d",
                       alpha=0.85))

    n_ticks  = 14
    tick_idx = np.linspace(0, len(df) - 1, n_ticks, dtype=int)
    ax5.set_xticks(tick_idx)
    ax5.set_xticklabels(
        [df.index[i].strftime("%m/%d %H:%M") for i in tick_idx],
        rotation=30, ha="right", fontsize=7, color=fg)
    ax5.set_xlabel("Time (UTC)", color=fg, fontsize=9)

    plt.savefig("bocpd_solusdt.png", dpi=150, bbox_inches="tight", facecolor=bg)
    print("Chart saved → bocpd_solusdt.png")
    plt.show()


# ──────────────────────────────────────────────────────────────
# 7. Main
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching SOLUSDT 5m klines (1000 bars) ...")
    df    = fetch_klines("SOLUSDT", "5m", 1000)
    close = df["close"].values
    print(f"Data range: {df.index[0]}  →  {df.index[-1]}")

    PARAMS = dict(
        ema_span       = 5,
        hazard_lambda  = 30,
        mu0            = 0.0,
        kappa0         = 0.1,
        alpha0         = 2.0,
        beta0          = 1e-5,
        drop_thresh    = 8,
        min_gap        = 5,
        extrema_order  = 5,
    )

    signal = build_signal(close, ema_span=PARAMS["ema_span"])

    print(f"Running BOCPD  λ={PARAMS['hazard_lambda']}  "
          f"κ₀={PARAMS['kappa0']}  ema_span={PARAMS['ema_span']} ...")

    mode_rl = bocpd(
        signal,
        hazard_lambda = PARAMS["hazard_lambda"],
        mu0    = PARAMS["mu0"],   kappa0 = PARAMS["kappa0"],
        alpha0 = PARAMS["alpha0"], beta0  = PARAMS["beta0"],
    )
    bocpd_cps = detect_changepoints(
        mode_rl,
        drop_thresh = PARAMS["drop_thresh"],
        min_gap     = PARAMS["min_gap"],
    )
    idx_max, idx_min = find_extrema(close, order=PARAMS["extrema_order"])

    ext_set   = set(idx_max.tolist()) | set(idx_min.tolist())
    n_overlap = sum(1 for cp in bocpd_cps
                    if any(abs(cp - e) <= 2 for e in ext_set))
    pct = 100 * n_overlap / max(len(bocpd_cps), 1)
    print(f"Local maxima        : {len(idx_max)}")
    print(f"Local minima        : {len(idx_min)}")
    print(f"BOCPD changepoints  : {len(bocpd_cps)}")
    print(f"Within ±2 bars      : {n_overlap} ({pct:.0f}%)")

    # ── Paper trading ──
    print("\nRunning paper trading simulation (initial capital = $100) ...")
    trades, equity = run_simulation(
        close, bocpd_cps, idx_max, idx_min,
        initial_capital=100.0
    )

    print(f"\n{'─'*60}")
    print(f"{'Trade':>5}  {'Dir':>5}  {'Entry':>7}  {'Exit':>7}  "
          f"{'Entry $':>9}  {'Exit $':>9}  {'P&L USD':>9}  {'P&L %':>7}")
    print(f"{'─'*60}")
    for i, t in enumerate(trades):
        print(f"{i+1:>5}  {t['direction'].upper():>5}  "
              f"{t['entry_price']:>7.3f}  {t['exit_price']:>7.3f}  "
              f"{100 if i==0 else trades[i-1]['equity_after']:>9.2f}  "
              f"{t['equity_after']:>9.2f}  "
              f"{'+' if t['pnl_usd']>=0 else ''}{t['pnl_usd']:>8.2f}  "
              f"{'+' if t['pnl_pct']>=0 else ''}{t['pnl_pct']:>6.2f}%")
    print(f"{'─'*60}")
    n_wins = sum(1 for t in trades if t["pnl_usd"] >= 0)
    print(f"\nTotal trades : {len(trades)}")
    print(f"Win / Loss   : {n_wins} / {len(trades)-n_wins}  "
          f"({100*n_wins/max(len(trades),1):.0f}% win rate)")
    print(f"Final equity : ${equity[-1]:.4f}  "
          f"({'+'if equity[-1]>=100 else ''}{equity[-1]-100:.4f} USD  "
          f"{'+'if equity[-1]>=100 else ''}{(equity[-1]-100):.2f}%)")

    print("\nPlotting ...")
    plot_result(df, signal, mode_rl, bocpd_cps,
                idx_max, idx_min, trades, equity, PARAMS)