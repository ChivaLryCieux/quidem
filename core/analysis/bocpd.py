import numpy as np
import pandas as pd
from scipy.special import gammaln


class BOCPDDetector:
    """BOCPD变点检测器（离线重算，在线触发）。"""

    def __init__(self, ema_span=5, hazard_lambda=30, drop_thresh=8, min_gap=5):
        self.ema_span = ema_span
        self.hazard_lambda = hazard_lambda
        self.drop_thresh = drop_thresh
        self.min_gap = min_gap

    @staticmethod
    def _st_logpdf(x, alpha, beta, kappa, mu):
        nu = 2.0 * alpha
        s2 = beta * (kappa + 1.0) / (alpha * kappa)
        return (
            gammaln((nu + 1.0) / 2.0)
            - gammaln(nu / 2.0)
            - 0.5 * np.log(np.pi * nu * s2)
            - (nu + 1.0) / 2.0 * np.log(1.0 + (x - mu) ** 2 / (nu * s2))
        )

    def _build_signal(self, close):
        log_ret = np.diff(np.log(np.maximum(close, 1e-10)))
        ema = pd.Series(log_ret).ewm(span=self.ema_span, adjust=False).mean().values
        ema_lag = np.concatenate([[0.0], ema[:-1]])
        return log_ret - ema_lag

    def _bocpd(self, signal, mu0=0.0, kappa0=0.1, alpha0=2.0, beta0=0.0001):
        if len(signal) == 0:
            return np.array([], dtype=int)

        hazard = 1.0 / self.hazard_lambda
        log_run_length = np.array([0.0])
        mu_arr = np.array([mu0])
        kappa_arr = np.array([kappa0])
        alpha_arr = np.array([alpha0])
        beta_arr = np.array([beta0])

        mode_rl = []
        for x in signal:
            log_pred = self._st_logpdf(x, alpha_arr, beta_arr, kappa_arr, mu_arr)
            log_joint = log_run_length + log_pred
            next_run_length = np.concatenate(
                [
                    [np.logaddexp.reduce(log_joint) + np.log(hazard)],
                    log_joint + np.log(1.0 - hazard),
                ]
            )
            next_run_length -= np.logaddexp.reduce(next_run_length)
            log_run_length = next_run_length
            mode_rl.append(int(np.argmax(np.exp(log_run_length))))

            kappa_new = kappa_arr + 1.0
            mu_new = (kappa_arr * mu_arr + x) / kappa_new
            alpha_new = alpha_arr + 0.5
            beta_new = beta_arr + kappa_arr * (x - mu_arr) ** 2 / (2.0 * kappa_new)

            mu_arr = np.concatenate([[mu0], mu_new])
            kappa_arr = np.concatenate([[kappa0], kappa_new])
            alpha_arr = np.concatenate([[alpha0], alpha_new])
            beta_arr = np.concatenate([[beta0], beta_new])

        mode_rl = np.array(mode_rl, dtype=int)
        return np.concatenate([[mode_rl[0]], mode_rl])

    def detect_changepoints(self, close_series):
        close = np.asarray(close_series, dtype=float)
        if len(close) < 30:
            return np.array([], dtype=int)

        mode_rl = self._bocpd(self._build_signal(close))
        if len(mode_rl) < 2:
            return np.array([], dtype=int)

        drops = np.where(np.diff(mode_rl) < -self.drop_thresh)[0] + 1
        changepoints = []
        last_cp = -self.min_gap
        for cp in drops:
            if cp - last_cp >= self.min_gap:
                changepoints.append(int(cp))
                last_cp = cp

        return np.array(changepoints, dtype=int)
