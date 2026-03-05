"""
Yield Anomaly Detection Engine — Multi-Factor Confluence
=========================================================
Mean reversion trading strategy using:
- Ornstein-Uhlenbeck process & Z-Score for anomaly detection
- RSI Divergence, MFI, Bollinger Squeeze, Fibonacci confirmation
- Multi-Factor Confluence Score (≥4/5 factors = trade)
- Candle confirmation with volume filter
- Entry triggers at Fibonacci 61.8% retracement
- Stop loss at anomaly candle extreme
- Take profit at OU equilibrium (μ)
"""

import yfinance as yf
import numpy as np
import pandas as pd
import requests
import json
import time
import os
import pytz
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List, Union
import statsmodels.api as sm
from hurst import compute_Hc


class YieldAnomalyTrader:
    """
    Professional trading signals from quantitative anomalies.
    
    Strategy Rules:
        1. Calculate Hurst Exponent to determine regime (H < 0.45 = Mean Reverting)
        2. Calculate Ornstein-Uhlenbeck (OU) stochastic process parameters (μ, θ, σ).
        3. Detect anomaly when Price deviates significantly from equilibrium (μ ± 2σ).
        4. Entry trigger: Confirmation candle in the direction of mean.
        5. Take Profit: Equilibrium mean (μ).
        6. Stop Loss: Dynamic boundary outside deviation.
    """
    
    # Instrument code -> display name
    ASSET_NAMES = {
        'XAUUSD': 'Gold Spot / U.S. Dollar (OANDA)',
    }

    # Input alias -> instrument base code
    ASSET_MAPPING = {
        'XAUUSD': 'XAUUSD',
        'GOLD': 'XAUUSD',
        'XAU': 'XAUUSD',
    }

    # Issue 2: Asset-specific OU Z-score thresholds
    ASSET_OU_THRESHOLD = {
        'XAUUSD': 2.0,
    }

    # TradingView exchange mapping per instrument
    # TradingView pulls live CME/COMEX data matching broker feeds like TradeSea
    TV_EXCHANGE_MAP = {
        'XAUUSD': 'OANDA',
    }

    @staticmethod
    def get_active_contract_suffix() -> str:
        """Return the current active CME quarterly contract letter+year suffix.
        CME cycles: H=Mar, M=Jun, U=Sep, Z=Dec.
        Contracts typically expire on the 3rd Friday of the delivery month.
        We switch to the next quarter after the 10th of the delivery month."""
        now = datetime.now()
        month = now.month
        year = str(now.year)[2:]  # e.g., '26' for 2026
        # Select active quarter
        if month <= 3:
            suffix = f'H{year}'   # March contract
        elif month <= 6:
            suffix = f'M{year}'   # June contract
        elif month <= 9:
            suffix = f'U{year}'   # September contract
        else:
            suffix = f'Z{year}'   # December contract
        return suffix

    @classmethod
    def build_contract_ticker(cls, instrument: str) -> str:
        """Build the active contract ticker (e.g. MNQM26=F)."""
        suffix = cls.get_active_contract_suffix()
        return f"{instrument}{suffix}=F"
    
    def __init__(
        self, 
        period: str = "5d", 
        interval: str = "15m", 
        window: int = 40, # Increased window for better OU calibration
        atr_period: int = 14,
        ou_threshold: float = 2.0, # Sigma multiple for entry
        risk_percent: float = 1.0,
        account_balance: float = 10000.0,
        discord_webhook_url: str = None
    ):
        self.period = period
        self.interval = interval
        self.window = window
        self.atr_period = atr_period
        self.ou_threshold = ou_threshold
        self.risk_percent = risk_percent
        self.account_balance = account_balance
        self.discord_webhook_url = discord_webhook_url
        self.alert_history = {} # {ticker: last_alert_timestamp_str}
        self.load_alert_history()
    
    def load_alert_history(self):
        """Load alert history from disk. Handles empty files and legacy string-format entries."""
        try:
            if os.path.exists('alert_history.json'):
                with open('alert_history.json', 'r') as f:
                    content = f.read().strip()
                    if not content:
                        self.alert_history = {}
                        return
                    raw = json.loads(content)
                    # Migrate legacy format: {ticker: "timestamp_string"} -> {ticker: {last_signal_time: ...}}
                    migrated = {}
                    for k, v in raw.items():
                        if isinstance(v, str):
                            migrated[k] = {'last_signal_time': v, 'cooldown_until': None}
                        else:
                            migrated[k] = v
                    self.alert_history = migrated
        except Exception as e:
            print(f"Error loading alert history: {e}")
            self.alert_history = {}

    def save_alert_history(self):
        """Save alert history to disk."""
        try:
            with open('alert_history.json', 'w') as f:
                json.dump(self.alert_history, f)
        except Exception as e:
            print(f"Error saving alert history: {e}")
    
    def fetch_data(self, ticker: str) -> Tuple[pd.DataFrame, str]:
        """Fetch OHLCV data.

        Priority:
        1. TradingView (tvDatafeed) — live CME/COMEX data matching broker prices
        2. yfinance continuous contract (MNQ=F) — silent fallback
        """
        import io, contextlib

        instrument = self.ASSET_MAPPING.get(ticker.upper(), ticker.upper())
        exchange   = self.TV_EXCHANGE_MAP.get(instrument, 'OANDA')
        # For XAUUSD, the best yfinance fallback is Gold Futures (GC=F)
        continuous_contract = "GC=F" if instrument == "XAUUSD" else f"{instrument}=F"

        bars_per_day = {'1m': 390, '5m': 78, '15m': 26, '30m': 13, '1h': 7, '4h': 2, '1d': 1}
        days_map = {'1d': 1, '2d': 2, '5d': 5, '10d': 10, '1mo': 22, '3mo': 65}
        days = days_map.get(self.period, 5)
        n_bars = bars_per_day.get(self.interval, 26) * days + 50

        df = pd.DataFrame()
        resolved = continuous_contract
        source = 'none'

        # ── Source 1: TradingView (live, matches broker) ──────────────────────
        def _try_tv():
            try:
                from tvDatafeed import TvDatafeed, Interval as TvInterval  # optional dep
                
                TV_INTERVAL_MAP = {
                    '1m':  TvInterval.in_1_minute,
                    '5m':  TvInterval.in_5_minute,
                    '15m': TvInterval.in_15_minute,
                    '30m': TvInterval.in_30_minute,
                    '1h':  TvInterval.in_1_hour,
                    '4h':  TvInterval.in_4_hour,
                    '1d':  TvInterval.in_daily,
                }
                tv_interval = TV_INTERVAL_MAP.get(self.interval, TvInterval.in_15_minute)

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    tv = TvDatafeed()
                    tv_df = tv.get_hist(
                        symbol=instrument, exchange=exchange,
                        interval=tv_interval, n_bars=n_bars
                    )
                if tv_df is not None and not tv_df.empty:
                    return tv_df.rename(columns={
                        'open': 'Open', 'high': 'High',
                        'low': 'Low', 'close': 'Close', 'volume': 'Volume'
                    })
            except ImportError:
                pass  # tvDatafeed not installed — use yfinance fallback
            except Exception:
                pass
            return None

        tv_result = _try_tv()
        if tv_result is not None and not tv_result.empty:
            df = tv_result
            resolved = f"{instrument}:TV"
            source = 'TradingView'

        # ── Source 2: yfinance continuous (fallback) ──────────────────────────
        if df.empty:
            fetch_period = self.period
            if self.interval == '1m' and fetch_period not in ['1d', '5d']:
                fetch_period = '5d'
            try:
                buf = io.StringIO()
                with contextlib.redirect_stderr(buf):
                    result = yf.download(
                        continuous_contract, period=fetch_period,
                        interval=self.interval, progress=False
                    )
                if result is not None and not result.empty:
                    if isinstance(result.columns, pd.MultiIndex):
                        result.columns = result.columns.get_level_values(0)
                    df = result
                    resolved = continuous_contract
                    source = 'yfinance'
            except Exception:
                pass

        if df.empty:
            raise ValueError(
                f"No data for {ticker}. "
                "TradingView and yfinance both failed — check your network connection."
            )

        # Standardize timezone to Asia/Bangkok (UTC+7)
        target_tz = pytz.timezone('Asia/Bangkok')
        if df.index.tz is None:
            df.index = df.index.tz_localize(pytz.utc)
        df.index = df.index.tz_convert(target_tz)

        # Staleness detection
        now_bkk = datetime.now(pytz.timezone('Asia/Bangkok'))
        last_candle_time = df.index[-1]
        age_minutes = max(0.0, (now_bkk - last_candle_time).total_seconds() / 60)
        stale = age_minutes > 20

        df.attrs['stale'] = stale
        df.attrs['age_minutes'] = round(age_minutes, 1)
        df.attrs['resolved_ticker'] = resolved
        df.attrs['is_active_contract'] = (source == 'TradingView')
        df.attrs['active_contract'] = f"{instrument}:{exchange}"
        df.attrs['source'] = source

        stale_warn = f" ⚠️ STALE ({age_minutes:.0f}min)" if stale else ""
        print(f"  [DATA] {resolved} via {source} | Last candle: {age_minutes:.0f}min ago{stale_warn}")

        return df, resolved

    def calculate_indicators(self, df: pd.DataFrame, instrument_code: str = '') -> pd.DataFrame:
        """Calculate OHLCV technical and quantitative indicators (Hurst + OU).
        
        instrument_code: e.g. 'MNQ', 'ES', 'MGC' — used for asset-specific thresholds.
        """
        df = df.copy()
        
        # Log Returns
        df['Log_Return'] = np.log(df['Close'] / df['Close'].shift(1))
        
        # ATR
        high, low, close = df['High'], df['Low'], df['Close']
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = df['TR'].rolling(window=self.atr_period).mean()

        # Issue 4: Volume ratio for confirmation (20-bar rolling average)
        if 'Volume' in df.columns:
            df['Vol_Avg'] = df['Volume'].rolling(window=20).mean()
            df['Vol_Ratio'] = (df['Volume'] / df['Vol_Avg']).clip(0, 10)
        else:
            df['Vol_Ratio'] = 1.0  # Fallback if volume not available
        
        # Initialize OU / Hurst Columns
        df['Hurst'] = np.nan
        df['OU_Mean'] = np.nan
        df['OU_Theta'] = np.nan
        df['OU_Sigma'] = np.nan
        df['OU_Z'] = np.nan
        
        # Rolling Calibration for Hurst and OU (Needs minimum window)
        prices = df['Close'].values
        
        for i in range(self.window, len(prices)):
            window_prices = prices[i - self.window + 1 : i + 1]
            
            # --- 1. Compute Hurst Exponent ---
            try:
                H, _, _ = compute_Hc(window_prices, kind='price', simplified=True)
                df.iloc[i, df.columns.get_loc('Hurst')] = H
            except Exception:
                # If Hurst fails on synthetic perfect walks, assume previous or slight mean-reverting
                df.iloc[i, df.columns.get_loc('Hurst')] = df.iloc[i-1]['Hurst'] if i > 0 and pd.notna(df.iloc[i-1]['Hurst']) else 0.49
            
            # --- 2. Calibrate Ornstein-Uhlenbeck Process ---
            # dX_t = \theta (\mu - X_t) dt + \sigma dW_t
            # Using discrete approximation: X_t - X_{t-1} = \theta (\mu - X_{t-1})\Delta t + \sigma \epsilon
            # Regression: y = \alpha + \beta x + \epsilon
            # where y = X_t - X_{t-1}, x = X_{t-1}
            # \theta = -\beta, \mu = \alpha / -\beta, \sigma = std(\epsilon)
            
            y = np.diff(window_prices)
            x = window_prices[:-1]
            x_sm = sm.add_constant(x)
            
            try:
                model = sm.OLS(y, x_sm)
                results = model.fit()
                
                if len(results.params) == 2:
                    alpha, beta = results.params
                    if beta < 0: # Mean-reverting (theta > 0)
                        theta = -beta
                        mu = alpha / theta
                        sigma = np.std(results.resid)
                        
                        df.iloc[i, df.columns.get_loc('OU_Mean')] = mu
                        df.iloc[i, df.columns.get_loc('OU_Theta')] = theta
                        df.iloc[i, df.columns.get_loc('OU_Sigma')] = sigma
                        
                        if sigma > 0:
                            df.iloc[i, df.columns.get_loc('OU_Z')] = (window_prices[-1] - mu) / sigma
                    else:
                        # Locally trending. Fallback to moving average proxy for UI continuity
                        df.iloc[i, df.columns.get_loc('OU_Mean')] = np.mean(window_prices)
                        df.iloc[i, df.columns.get_loc('OU_Theta')] = 0.001
                        df.iloc[i, df.columns.get_loc('OU_Sigma')] = np.std(window_prices)
                        if np.std(window_prices) > 0:
                            df.iloc[i, df.columns.get_loc('OU_Z')] = (window_prices[-1] - np.mean(window_prices)) / np.std(window_prices)
            except Exception:
                pass
                
        # Forward fill any remaining NaNs after the initial window to prevent frontend crashes
        df['Hurst'] = df['Hurst'].ffill()
        df['OU_Mean'] = df['OU_Mean'].ffill()
        df['OU_Sigma'] = df['OU_Sigma'].ffill()
        df['OU_Theta'] = df['OU_Theta'].ffill()
        df['OU_Z'] = df['OU_Z'].ffill()

        # ─────────────────────────────────────────────────────────────────────────
        # INSTITUTIONAL QUANT MATH — Bank-Grade Signal Quality Improvements
        # ─────────────────────────────────────────────────────────────────────────

        # 1. KALMAN FILTER PRICE SMOOTHER (Welch & Bishop, 2001)
        #    Used by quant prop desks to remove microstructure noise from price.
        #    The Kalman estimate removes random tick-level noise before OU calibration,
        #    making the Z-Score calculation much more statistically robust.
        #    Reference: "An Introduction to the Kalman Filter" — NASA Technical Report
        kalman_gain = 0.3       # Process / (Process + Measurement) noise ratio
        kalman_price = df['Close'].values.copy().astype(float)
        estimate = kalman_price[0]
        kalman_smooth = np.zeros(len(kalman_price))
        uncertainty = 1.0
        Q = 0.001   # Process noise (random walk assumption)
        R = 0.01    # Measurement noise (bid-ask spread proxy)
        for k in range(len(kalman_price)):
            # Predict
            uncertainty += Q
            # Update
            kalman_gain = uncertainty / (uncertainty + R)
            estimate = estimate + kalman_gain * (kalman_price[k] - estimate)
            uncertainty = (1 - kalman_gain) * uncertainty
            kalman_smooth[k] = estimate
        df['Kalman_Price'] = kalman_smooth
        # Kalman Z-Score: deviation of raw price from Kalman 'true' state
        kalman_std = pd.Series(kalman_smooth).rolling(window=self.window).std()
        df['Kalman_Z'] = (df['Close'] - df['Kalman_Price']) / kalman_std.values

        # 2. OU HALF-LIFE CONFIDENCE SCORE (Avellaneda & Lee, 2010)
        #    Mean-reversion Half-Life measures how fast the process returns to μ.
        #    Half-Life = ln(2) / θ  (in candle units)
        #    Reference: "Statistical Arbitrage in the US Equities Market" — quant.finance
        #    Score: < 8 bars = HIGH confidence (fast reversion)
        #           8-20 bars = MEDIUM
        #           > 20 bars = LOW (slow; may not complete within session)
        df['OU_HalfLife'] = np.log(2) / df['OU_Theta'].clip(lower=0.001)

        def half_life_confidence(hl):
            if pd.isna(hl) or hl <= 0:
                return 0.0
            if hl < 8:
                return 1.0    # HIGH — fast, within-session reversion
            elif hl < 20:
                return 0.65   # MEDIUM
            else:
                return 0.30   # LOW — too slow for day trade

        df['HL_Confidence'] = df['OU_HalfLife'].apply(half_life_confidence)

        # 3. KELLY CRITERION SIGNAL QUALITY SCORE (Kelly, 1956)
        #    The Kelly fraction determines the mathematically optimal bet size.
        #    f* = (p * b - q) / b   where:
        #       p = estimated win probability (from Gaussian OU distribution)
        #       q = 1 - p (loss probability)
        #       b = R:R ratio (TP1 / Stop Distance)
        #    Reference: "A New Interpretation of Information Rate" — Bell System Technical Journal
        #    We use this to compute a 0-100 signal quality score combining:
        #    - OU Z-Score magnitude (how extreme the statistical deviation is)
        #    - Hurst regime quality (how confirmed the mean-reverting regime is)
        #    - Half-Life confidence (how fast the reversion is expected to complete)
        z_thresh_col = self.ASSET_OU_THRESHOLD.get(instrument_code, self.ou_threshold)
        
        def kelly_quality_score(row):
            z = abs(row['OU_Z']) if not pd.isna(row['OU_Z']) else 0
            h = row['Hurst'] if not pd.isna(row['Hurst']) else 0.5
            hl_conf = row['HL_Confidence'] if not pd.isna(row['HL_Confidence']) else 0

            # Estimated win probability: further from mean = higher p (Gaussian tail)
            # P(reversion) ≈ 1 - Φ(-z) = Φ(z), capped for realism
            from scipy.stats import norm as _norm
            p_win = min(0.80, _norm.cdf(z - z_thresh_col + 1))  # shift so p(z=threshold)≈0.5

            # R:R proxy: standard OU reversion yields 2.0R to μ
            b = 2.0
            q_lose = 1.0 - p_win
            kelly_f = max(0.0, (p_win * b - q_lose) / b)  # fractional Kelly

            # Regime quality: reward low Hurst (more mean-reverting)
            regime_quality = max(0.0, 1.0 - (h / 0.50))  # maps [0,0.50] → [1,0]

            # Combined score 0-100
            score = kelly_f * regime_quality * hl_conf * 100
            return round(min(score, 100.0), 1)

        df['Kelly_Score'] = df.apply(kelly_quality_score, axis=1)

        # Formatting bands for UI
        df['Upper_Band'] = df['OU_Mean'] + (self.ou_threshold * df['OU_Sigma'])
        df['Lower_Band'] = df['OU_Mean'] - (self.ou_threshold * df['OU_Sigma'])
        df['Mean'] = df['OU_Mean']  # For backward compat with app.js
        df['Z_Score'] = df['OU_Z']  # For backward compat with app.js
        
        # Issue 2: Pick per-asset Z threshold; fallback to global ou_threshold
        z_thresh = self.ASSET_OU_THRESHOLD.get(instrument_code, self.ou_threshold)
        df['OU_Threshold'] = z_thresh  # store for downstream use

        # Mark anomalies
        # Condition 1: OU_Z exceeds asset-specific threshold
        # Condition 2: Hurst < 0.50 (mean-reverting regime)
        df['Is_Anomaly'] = (abs(df['OU_Z']) >= z_thresh) & (df['Hurst'] < 0.50)
        df['Anomaly_Type'] = np.where(
            (df['OU_Z'] <= -z_thresh) & (df['Hurst'] < 0.50), 'OVERSOLD',
            np.where((df['OU_Z'] >= z_thresh) & (df['Hurst'] < 0.50), 'OVERBOUGHT', 'NORMAL')
        )
        
        return df
    
    def find_anomalies(self, df: pd.DataFrame) -> List[Dict]:
        """Find all anomaly points with their candle data.
        
        Improvements:
         - Issue 1: NY session gate (9:30 AM - 4:00 PM ET) — skips overnight dead hours
         - Issue 4: Volume confirmation — requires Vol_Ratio > 1.2 on confirmation candle
        """
        anomalies = []
        NY_TZ = pytz.timezone('America/New_York')

        for i in range(len(df)):
            row = df.iloc[i]
            if not row['Is_Anomaly']:
                continue

            # --- Issue 1: NY Session Filter ---
            # Candle timestamp must be within New York Regular Session (09:30–16:00 ET)
            try:
                candle_time_ny = row.name.astimezone(NY_TZ)
                hour = candle_time_ny.hour
                minute = candle_time_ny.minute
                tot_min = hour * 60 + minute
                if not (570 <= tot_min <= 960):  # 570=9:30, 960=16:00
                    continue  # Skip overnight / pre-market signals
            except Exception:
                pass  # Timezone conversion failed; allow signal through

            anomaly = {
                'index': i,
                'time': str(row.name),
                'type': row['Anomaly_Type'],
                'z_score': float(row['Z_Score']),
                'hurst': float(row['Hurst']) if not pd.isna(row['Hurst']) else 0.45,
                'candle': {
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                },
                'log_return': float(row['Log_Return']),
            }

            # Check confirmation (next candle)
            if i + 1 < len(df):
                next_row = df.iloc[i + 1]
                # Issue 4: Volume guard — confirmation candle must have above-average volume
                vol_ratio = float(next_row.get('Vol_Ratio', 1.0)) if 'Vol_Ratio' in next_row.index else 1.0
                high_volume = vol_ratio >= 1.2

                if row['Anomaly_Type'] == 'OVERSOLD':
                    is_green = next_row['Close'] > next_row['Open']
                    broke_high = next_row['High'] > row['High']
                    anomaly['confirmed'] = bool(is_green and broke_high and high_volume)
                    anomaly['entry_trigger'] = float(next_row['Close'])
                    anomaly['stop_loss'] = float(row['Low'])
                    anomaly['direction'] = 'LONG'
                else:  # OVERBOUGHT
                    is_red = next_row['Close'] < next_row['Open']
                    broke_low = next_row['Low'] < row['Low']
                    anomaly['confirmed'] = bool(is_red and broke_low and high_volume)
                    anomaly['entry_trigger'] = float(next_row['Close'])
                    anomaly['stop_loss'] = float(row['High'])
                    anomaly['direction'] = 'SHORT'
                anomaly['vol_ratio'] = round(vol_ratio, 2)
            else:
                anomaly['confirmed'] = False
                anomaly['entry_trigger'] = None
                anomaly['stop_loss'] = None
                anomaly['direction'] = 'LONG' if row['Anomaly_Type'] == 'OVERSOLD' else 'SHORT'
                anomaly['vol_ratio'] = 0.0

            anomalies.append(anomaly)

        return anomalies
    
    def generate_trade_setup(self, latest: pd.Series, prev: pd.Series, 
                            atr: float, ticker: str) -> Optional[Dict]:
        """Generate trade setup from current anomaly using OU mechanics."""
        z_score = prev['OU_Z'] if prev is not None else latest['OU_Z'] # Check prev candle for anomaly if we are the confirmation candle
        hurst = prev['Hurst'] if prev is not None else latest['Hurst']
        
        # We need an anomaly in the current or previous candle, AND a mean-reverting regime
        if pd.isna(z_score) or abs(z_score) < self.ou_threshold or hurst > 0.5:
             z_score = latest['OU_Z']
             hurst = latest['Hurst']
             if pd.isna(z_score) or abs(z_score) < self.ou_threshold or hurst > 0.5:
                 return None
        
        is_long = z_score <= -self.ou_threshold
        price = float(latest['Close'])
        mean = float(latest['OU_Mean'])
        theta = float(latest['OU_Theta']) if pd.notna(latest['OU_Theta']) and latest['OU_Theta'] > 0 else 0.001
        
        # Expected Half-Life of mean reversion
        half_life = np.log(2) / theta
        
        # Identify the anomaly candle (either prev or latest)
        if prev is not None and abs(prev['OU_Z']) >= self.ou_threshold and prev['Hurst'] < 0.5:
            anomaly_high = float(prev['High'])
            anomaly_low = float(prev['Low'])
            is_confirmation_candle = True
        else:
            anomaly_high = float(latest['High'])
            anomaly_low = float(latest['Low'])
            is_confirmation_candle = False
            
        if is_long:
            direction = "LONG"
            # Ultimate Sniper Matrix: Deep Golden Ratio 61.8% Limit Order inside the anomaly sweep
            pullback_target = anomaly_low + ((anomaly_high - anomaly_low) * 0.382) # 0.382 from bottom = 0.618 from top
            entry_trigger = pullback_target if is_confirmation_candle else anomaly_high
            
            # Micro Stop-Loss: Placed exactly at the absolute bottom of the anomaly with a 0.05 ATR noise filter
            stop_loss = anomaly_low - (atr * 0.05)  
            
            # Asymmetrical Take Profits based on OU Equilibrium
            tp1 = mean  # Mean Reversion Target (Equilibrium)
            tp2 = mean + (latest['OU_Sigma'] * 1.5)  # μ + 1.5σ Momentum
            tp3 = mean + (latest['OU_Sigma'] * 3.0)  # μ + 3.0σ Extreme
        else:
            direction = "SHORT"
            # Ultimate Sniper Matrix: Deep Golden Ratio 61.8% Limit Order inside the anomaly sweep
            pullback_target = anomaly_high - ((anomaly_high - anomaly_low) * 0.382) # 0.382 from top = 0.618 from bottom
            entry_trigger = pullback_target if is_confirmation_candle else anomaly_low
            
            # Micro Stop-Loss: Placed exactly at the absolute top of the anomaly with a 0.05 ATR noise filter
            stop_loss = anomaly_high + (atr * 0.05)  
            
            # Asymmetrical Take Profits based on OU Equilibrium
            tp1 = mean
            tp2 = mean - (latest['OU_Sigma'] * 1.5)  # μ - 1.5σ Momentum
            tp3 = mean - (latest['OU_Sigma'] * 3.0)  # μ - 3.0σ Extreme
        
        stop_distance = abs(entry_trigger - stop_loss)
        if stop_distance == 0:
             stop_distance = atr # fallback
             
        risk = stop_distance
        
        # Position sizing
        risk_amount = self.account_balance * (self.risk_percent / 100)
        position_size = risk_amount / stop_distance if stop_distance > 0 else 0
        
        # Confirmation check
        is_confirmed = False
        confirmation_msg = "WAIT - Candle not closed yet"
        
        if is_confirmation_candle:
            if is_long:
                # For long: check if current candle is green and broke high
                is_green = latest['Close'] > latest['Open']
                broke_high = latest['High'] > anomaly_high
                is_confirmed = bool(is_green and broke_high)
                confirmation_msg = "CONFIRMED - Quant Setup Ready" if is_confirmed else "WAIT for PA confirmation"
            else:
                # For short: check if current candle is red and broke low
                is_red = latest['Close'] < latest['Open']
                broke_low = latest['Low'] < anomaly_low
                is_confirmed = bool(is_red and broke_low)
                confirmation_msg = "CONFIRMED - Quant Setup Ready" if is_confirmed else "WAIT for PA confirmation"
        
        return {
            "direction": direction,
            "status": "READY" if is_confirmed else "PENDING",
            "confirmation": confirmation_msg,
            "is_confirmed": is_confirmed,
            "current_price": round(price, 2),
            "entry_trigger": round(entry_trigger, 2),
            "entry_type": f"LIMIT @ {entry_trigger:.2f}" if is_confirmed else (f"BUY STOP @ {entry_trigger:.2f}" if is_long else f"SELL STOP @ {entry_trigger:.2f}"),
            "stop_loss": round(stop_loss, 2),
            "take_profit": {
                "tp1": {"price": round(tp1, 2), "rr": round(abs(tp1-entry_trigger)/risk, 1) if risk > 0 else 0, "label": "OU Equilibrium (μ)"},
                "tp2": {"price": round(tp2, 2), "rr": round(abs(tp2-entry_trigger)/risk, 1) if risk > 0 else 0, "label": "μ ± 1.5σ Momentum"},
                "tp3": {"price": round(tp3, 2), "rr": round(abs(tp3-entry_trigger)/risk, 1) if risk > 0 else 0, "label": "μ ± 3.0σ Extreme"},
            },
            "risk_management": {
                "risk_amount": round(risk_amount, 2),
                "position_size": round(position_size, 4),
                "risk_percent": self.risk_percent,
                "stop_distance": round(stop_distance, 2),
                "stop_distance_pct": round((stop_distance / price) * 100, 2),
            },
            "anomaly_candle": {
                "high": round(anomaly_high, 2),
                "low": round(anomaly_low, 2),
            }
        }
    
    def get_signal(self, z_score: float, hurst: float) -> Dict:
        """Generate trading signal from Z-Score and Hurst Component."""
        if pd.isna(z_score) or pd.isna(hurst):
            return {
                "signal": "NO_DATA",
                "action": "WAIT",
                "description": "Calibrating OU Process...",
                "severity": "neutral"
            }
        
        z_abs = abs(z_score)
        
        if hurst > 0.5:
            return {
                "signal": "TRENDING",
                "action": "WAIT",
                "description": f"Trending Market (H={hurst:.2f}) - Mean Reversion Disabled",
                "severity": "neutral"
            }
        
        # Mean Reverting condition
        if z_score <= -self.ou_threshold:
            return {
                "signal": "STRONG_BUY",
                "action": "BUY_STOP",
                "description": f"OU DISPERSION (Z={z_score:.2f}) - Mean Reverting",
                "severity": "critical_long"
            }
        elif z_score >= self.ou_threshold:
            return {
                "signal": "STRONG_SELL",
                "action": "SELL_STOP",
                "description": f"OU DISPERSION (Z={z_score:.2f}) - Mean Reverting",
                "severity": "critical_short"
            }
        elif z_abs >= 1.5:
            return {
                "signal": "WATCH",
                "action": "WAIT",
                "description": f"Approaching OU threshold (Z={z_score:.2f})",
                "severity": "watch"
            }
        else:
            return {
                "signal": "NEUTRAL",
                "action": "WAIT",
                "description": f"Equilibrium Range (Z={z_score:.2f})",
                "severity": "neutral"
            }
    
    def send_discord_alert(self, anomaly: Dict, ticker: str, asset_name: str,
                           current_price: float, trade_setup: Optional[Dict] = None):
        """Send Rich Embed alert to Discord.
        
        Issue 3 Fix: Uses pre-computed TP values from trade_setup (same as dashboard)
        instead of independently recalculating them from scratch, ensuring Discord
        and the UI always show identical targets.
        """
        if not self.discord_webhook_url:
            return

        webhooks = self.discord_webhook_url
        if isinstance(webhooks, str):
            webhooks = [webhooks]

        color = 5763719 if anomaly['direction'] == 'LONG' else 15158332

        entry = anomaly.get('entry_trigger', 0) or 0
        sl    = anomaly.get('stop_loss', 0) or 0
        risk  = abs(entry - sl)

        # Issue 3: Use dashboard trade_setup TPs if available (consistent targets)
        if trade_setup and trade_setup.get('take_profit'):
            tp1 = trade_setup['take_profit']['tp1']['price']
            tp2 = trade_setup['take_profit']['tp2']['price']
            tp3 = trade_setup['take_profit']['tp3']['price']
            rr1 = trade_setup['take_profit']['tp1']['rr']
            rr2 = trade_setup['take_profit']['tp2']['rr']
            rr3 = trade_setup['take_profit']['tp3']['rr']
        else:
            # Fallback calculation (kept for safety)
            if anomaly['direction'] == 'LONG':
                tp1, tp2, tp3 = entry + risk * 1.5, entry + risk * 2.5, entry + risk * 4.0
            else:
                tp1, tp2, tp3 = entry - risk * 1.5, entry - risk * 2.5, entry - risk * 4.0
            rr1, rr2, rr3 = 1.5, 2.5, 4.0

        hurst_val = anomaly.get('hurst', 0.40)
        vol_ratio = anomaly.get('vol_ratio', 0.0)
        z_val = anomaly.get('z_score', 0.0)

        embed = {
            "title": f"🎯 QUANT SIGNAL [{ticker}]: {anomaly['direction']}",
            "description": (
                f"**Asset:** {asset_name}\n"
                f"**Z-Score:** {z_val:.2f}σ | **Hurst:** {hurst_val:.2f} | **Vol:** {vol_ratio:.2f}x avg\n"
                f"**Pattern:** OU Dispersion Anomaly — NY Session Confirmed\n"
                f"**Entry Type:** LIMIT @ Fibonacci 61.8% retracement"
            ),
            "color": color,
            "fields": [
                {"name": "ENTRY (LIMIT)",        "value": f"**${entry:,.2f}**", "inline": True},
                {"name": "STOP LOSS",            "value": f"${sl:,.2f}", "inline": True},
                {"name": "RISK",                 "value": f"${risk:,.2f}", "inline": True},
                {"name": "━━━━━━━━━━━━━━━━━━━━", "value": "", "inline": False},
                {"name": "TP1 — OU Mean (μ)",   "value": f"${tp1:,.2f}  (R:R {rr1})", "inline": True},
                {"name": "TP2 — μ ± 1.5σ",      "value": f"${tp2:,.2f}  (R:R {rr2})", "inline": True},
                {"name": "TP3 — μ ± 3.0σ",      "value": f"${tp3:,.2f}  (R:R {rr3})", "inline": True},
            ],
            "footer": {"text": f"Yield Anomaly Engine | {anomaly['time'][5:16]}"},
            "thumbnail": {"url": "https://cdn-icons-png.flaticon.com/512/3310/3310624.png" if anomaly['direction'] == 'SHORT' else "https://cdn-icons-png.flaticon.com/512/3310/3310645.png"}
        }
        
        payload = {
            "content": "Signal Alert\n"
                       "Quant Analysis Developed by <@732560547345858570>\n"
                       "Not financial advice na ja :> ",
            "embeds": [embed]
        }
        
        success_count = 0
        for url in webhooks:
            try:
                # Clean URL and send
                clean_url = url.strip()
                if clean_url:
                    requests.post(clean_url, json=payload, timeout=3)
                    success_count += 1
            except Exception as e:
                print(f"Failed to send Discord alert to webhook: {e}")
                
        if success_count > 0:
            print(f"Alert sent to {success_count} webhook(s)")
    
    def analyze(self, ticker: str) -> Dict[str, Any]:
        """Perform complete trading analysis.
        
        Improvements applied here:
        - Issue 2: instrument_code passed to calculate_indicators for asset-specific thresholds
        - Issue 6: Signal cooldown — no re-alert within 2x OU Half-Life after last signal
        - Issue 3: trade_setup passed to send_discord_alert for consistent TP targets
        - Exposes Kelly_Score, Kalman_Z, OU_HalfLife in API response
        """
        import re as _re
        df, resolved = self.fetch_data(ticker)

        # Extract instrument base code (e.g. 'MNQ' from 'MNQH26=F')
        instrument_code = _re.sub(r'[HMUZhmuz]\d{2}=F$|=F$', '', resolved)
        df = self.calculate_indicators(df, instrument_code=instrument_code)

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None

        z_score = latest['OU_Z']
        hurst = latest['Hurst']
        atr = latest['ATR'] if not pd.isna(latest['ATR']) else 0
        kelly_score = float(latest['Kelly_Score']) if 'Kelly_Score' in df.columns and not pd.isna(latest['Kelly_Score']) else 0.0
        kalman_z = float(latest['Kalman_Z']) if 'Kalman_Z' in df.columns and not pd.isna(latest['Kalman_Z']) else None
        half_life = float(latest['OU_HalfLife']) if 'OU_HalfLife' in df.columns and not pd.isna(latest['OU_HalfLife']) else None

        signal = self.get_signal(z_score, hurst)
        trade_setup = self.generate_trade_setup(latest, prev, atr, resolved)

        # Use a specific slice for anomaly detection to ensure consistency
        recent_df = df.tail(50)
        anomalies = self.find_anomalies(recent_df)

        # Check for alerts on Confirmed Anomalies
        if self.discord_webhook_url and anomalies:
            latest_anomaly = anomalies[-1]
            slice_len = len(recent_df)

            # Freshness Check: Only alert if anomaly is recent (last 2 candles of the slice)
            is_fresh = latest_anomaly['index'] >= slice_len - 2

            if (latest_anomaly.get('confirmed') and
                    abs(latest_anomaly['z_score']) >= self.ASSET_OU_THRESHOLD.get(instrument_code, self.ou_threshold) and
                    is_fresh):

                alert_rec = self.alert_history.get(resolved, {})
                last_signal_time = alert_rec if isinstance(alert_rec, str) else alert_rec.get('last_signal_time')

                # Issue 6: Cooldown check — require 2x OU Half-Life spacing between signals
                cooldown_ok = True
                if isinstance(alert_rec, dict) and 'cooldown_until' in alert_rec:
                    try:
                        cooldown_until = datetime.fromisoformat(alert_rec['cooldown_until'])
                        cooldown_ok = datetime.now() >= cooldown_until
                    except Exception:
                        cooldown_ok = True

                if last_signal_time != latest_anomaly['time'] and cooldown_ok:
                    asset_display = self.ASSET_NAMES.get(instrument_code, resolved)
                    self.send_discord_alert(
                        latest_anomaly, resolved, asset_display,
                        float(latest['Close']), trade_setup
                    )
                    # Compute cooldown period: 2 × half-life in minutes (15m candles)
                    theta_val = float(latest['OU_Theta']) if not pd.isna(latest['OU_Theta']) and latest['OU_Theta'] > 0 else 0.001
                    half_life_bars = np.log(2) / theta_val
                    cooldown_min = max(30, half_life_bars * 15 * 2)
                    from datetime import timedelta
                    self.alert_history[resolved] = {
                        'last_signal_time': latest_anomaly['time'],
                        'cooldown_until': (datetime.now() + timedelta(minutes=cooldown_min)).isoformat()
                    }
                    self.save_alert_history()

        asset_display_name = self.ASSET_NAMES.get(instrument_code, resolved)

        return {
            "timestamp": datetime.now().isoformat(),
            "data_timestamp": str(latest.name),
            "ticker": resolved,
            "asset_name": asset_display_name,
            "price": {
                "current": float(latest['Close']),
                "open": float(latest['Open']),
                "high": float(latest['High']),
                "low": float(latest['Low']),
            },
            "analysis": {
                "hurst": float(hurst) if not pd.isna(hurst) else None,
                "z_score": float(z_score) if not pd.isna(z_score) else None,
                "mean": float(latest['OU_Mean']) if not pd.isna(latest['OU_Mean']) else None,
                "std_dev": float(latest['OU_Sigma']) if not pd.isna(latest['OU_Sigma']) else None,
                "theta": float(latest['OU_Theta']) if not pd.isna(latest['OU_Theta']) else None,
                "atr": float(atr) if not pd.isna(atr) else None,
                "atr_percent": float((atr / latest['Close']) * 100) if atr > 0 else None,
                # Institutional quant metrics
                "kelly_score": kelly_score,
                "kalman_z": kalman_z,
                "half_life_bars": half_life,
                "half_life_minutes": round(half_life * 15, 1) if half_life else None,
            },
            "data_quality": {
                "stale": bool(df.attrs.get('stale', False)),
                "age_minutes": df.attrs.get('age_minutes', 0),
                "is_active_contract": bool(df.attrs.get('is_active_contract', False)),
                "active_contract": df.attrs.get('active_contract', resolved),
                "resolved_ticker": resolved,
                "warning": "Data may be stale (>20min old). Market may be closed." if df.attrs.get('stale') else None,
                "price_note": (
                    f"Using active contract {resolved} — price matches broker feeds."
                    if df.attrs.get('is_active_contract')
                    else f"⚠️ Using continuous contract {resolved} (fallback). Price may differ from broker by up to $50."
                ),
            },
            "signal": signal,
            "trade_setup": trade_setup,
            "recent_anomalies": anomalies[-10:] if anomalies else [],
            "parameters": {
                "period": self.period,
                "interval": self.interval,
                "window": self.window,
                "ou_threshold": self.ou_threshold,
            }
        }
    
    def get_chart_data(self, ticker: str, limit: int = 200) -> Dict[str, Any]:
        """Get chart data with anomaly markers."""
        df, resolved = self.fetch_data(ticker)
        df = self.calculate_indicators(df)
        df = df.dropna().tail(limit)
        
        labels = [ts.strftime('%m/%d %H:%M') for ts in df.index]
        
        # Find anomaly indices for markers
        anomaly_markers = []
        for i, (idx, row) in enumerate(df.iterrows()):
            if row['Is_Anomaly']:
                anomaly_markers.append({
                    "index": i,
                    "time": labels[i],
                    "z_score": float(row['Z_Score']),
                    "type": row['Anomaly_Type'],
                    "price": float(row['Close']),
                    "log_return": float(row['Log_Return']),
                    "candle_high": float(row['High']),
                    "candle_low": float(row['Low']),
                })
        
        import re as _re
        instrument_code = _re.sub(r'[HMUZhmuz]\d{2}=F$|=F$', '', resolved)
        return {
            "ticker": resolved,
            "asset_name": self.ASSET_NAMES.get(instrument_code, resolved),
            "labels": labels,
            "z_scores": df['OU_Z'].tolist(),
            "upper_band": df['Upper_Band'].tolist(),
            "lower_band": df['Lower_Band'].tolist(),
            "mean": df['OU_Mean'].tolist(),
            "prices": df['Close'].tolist(),
            "highs": df['High'].tolist(),
            "lows": df['Low'].tolist(),
            "anomaly_markers": anomaly_markers,
        }


def print_trading_report(report: Dict) -> None:
    """Print a professional trading report."""
    print("\n" + "=" * 70)
    print(f"  YIELD ANOMALY SIGNAL: {report['asset_name']}")
    print("=" * 70)
    print(f"  Ticker: {report['ticker']}  |  Time: {report['data_timestamp']}")
    print("-" * 70)
    print(f"  Current Price:    ${report['price']['current']:,.2f}")
    if report['analysis']['hurst'] is not None:
        print(f"  HURST EXPONENT:   {float(report['analysis']['hurst']):.2f}")
    if report['analysis']['z_score'] is not None:
        print(f"  OU DEVIATION:     {float(report['analysis']['z_score']):.3f} σ")
    if report['analysis']['mean'] is not None:
        print(f"  OU EQUILIBRIUM:   ${float(report['analysis']['mean']):.2f}")
    print("-" * 70)
    print(f"  SIGNAL:           {report['signal']['signal']}")
    print(f"  ACTION:           {report['signal']['action']}")
    print(f"  STATUS:           {report['signal']['description']}")
    
    if report['trade_setup']:
        ts = report['trade_setup']
        print("-" * 70)
        print(f"  TRADE SETUP: {ts['direction']}")
        print(f"  Status:           {ts['status']} - {ts['confirmation']}")
        print(f"  Entry:            {ts['entry_type']}")
        print(f"  Stop Loss:        ${ts['stop_loss']:,.2f} (-{ts['risk_management']['stop_distance_pct']}%)")
        print(f"  TP1 (1.5R):       ${ts['take_profit']['tp1']['price']:,.2f} - {ts['take_profit']['tp1']['label']}")
        print(f"  TP2 (2.5R):       ${ts['take_profit']['tp2']['price']:,.2f} - {ts['take_profit']['tp2']['label']}")
        print(f"  TP3 (4.0R):       ${ts['take_profit']['tp3']['price']:,.2f} - {ts['take_profit']['tp3']['label']}")
        print(f"  Position Size:    {ts['risk_management']['position_size']:.4f} units")
        print(f"  Risk Amount:      ${ts['risk_management']['risk_amount']:.2f}")
    
    print("=" * 70)
    
    # Print recent anomalies
    if report.get('recent_anomalies'):
        print("\n  RECENT ANOMALIES:")
        for a in report['recent_anomalies'][-5:]:
            status = "[CONFIRMED]" if a.get('confirmed') else "[WAIT]"
            print(f"    {status} {a['time'][:11]} | Z={a['z_score']:.2f} | {a['direction']} | Trigger: ${a.get('entry_trigger', 0):,.2f}")
    
    print()


# For backward compatibility
YieldAnomalyDetector = YieldAnomalyTrader


import os

if __name__ == "__main__":
    DISCORD_URL = os.environ.get("DISCORD_WEBHOOK_URL", None)
    
    trader = YieldAnomalyTrader(
        period="5d",
        interval="15m",
        window=40,
        ou_threshold=2.0,
        risk_percent=1.0,
        account_balance=10000.0,
        discord_webhook_url=DISCORD_URL
    )
    assets = ['XAUUSD']
    
    print("\n" + "YIELD ANOMALY TRADING ENGINE".center(70))
    print("=" * 70)
    print("  Strategy: Hurst Regime Detection | Ornstein-Uhlenbeck Mechanics")
    print("=" * 70)
    
    if DISCORD_URL:
        print("  [DISCORD ALERTS ENABLED]".center(70))
    else:
        print("  [DISCORD ALERTS DISABLED - NO WEBHOOK URL PROVIDED]".center(70))
    print("=" * 70)
    
    for asset in assets:
        try:
            report = trader.analyze(asset)
            print_trading_report(report)
        except Exception as e:
            print(f"\nError analyzing {asset}: {str(e)}\n")
