"""
Yield Anomaly Detection Engine
==============================
Mean reversion trading strategy using:
- Log Returns & Z-Score for anomaly detection
- Candle confirmation
- Entry triggers at anomaly candle high/low breakout
- Stop loss at anomaly candle extreme
- Take profit when Z-Score returns to mean (0)
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
    
    ASSET_MAPPING = {
        'MNQ': 'MNQ=F',
        'NASDAQ': 'MNQ=F',
        'MGC': 'MGC=F',
        'GOLD': 'MGC=F',
        'ES': 'ES=F',
        'SP500': 'ES=F',
    }
    
    ASSET_NAMES = {
        'MNQ=F': 'CME MNQ (Micro NASDAQ)',
        'MGC=F': 'COMEX MGC (Micro Gold)',
        'ES=F': 'CME ES (E-mini S&P 500)',
    }
    
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
        """Load alert history from disk."""
        try:
            if os.path.exists('alert_history.json'):
                with open('alert_history.json', 'r') as f:
                    self.alert_history = json.load(f)
        except Exception as e:
            print(f"Error loading alert history: {e}")

    def save_alert_history(self):
        """Save alert history to disk."""
        try:
            with open('alert_history.json', 'w') as f:
                json.dump(self.alert_history, f)
        except Exception as e:
            print(f"Error saving alert history: {e}")
    
    def fetch_data(self, ticker: str) -> Tuple[pd.DataFrame, str]:
        """Fetch OHLCV data from Yahoo Finance and standardize timezone."""
        resolved = self.ASSET_MAPPING.get(ticker.upper(), ticker)
        
        # yfinance limits 1m data to 7 days maximum. We use 5d by default, 
        # but sometimes weekends push it over limit depending on current time. 
        # Let's enforce a strict "5d" limit for 1m interval.
        fetch_period = self.period
        if self.interval == '1m' and fetch_period not in ['1d', '5d']:
             fetch_period = '5d'
        
        df = yf.download(resolved, period=fetch_period, interval=self.interval, progress=False)
        
        if df.empty:
            raise ValueError(f"No data for {ticker}")
            
        # Handle MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # Standardize Timezone to Asia/Bangkok (UTC+7)
        target_tz = pytz.timezone('Asia/Bangkok')
        if df.index.tz is None:
            df.index = df.index.tz_localize(pytz.utc)
        df.index = df.index.tz_convert(target_tz)
        
        return df, resolved
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate OHLCV technical and quantitative indicators (Hurst + OU)."""
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
        
        # Initialize OU / Hurst Columns
        df['Hurst'] = np.nan
        df['OU_Mean'] = np.nan
        df['OU_Theta'] = np.nan
        df['OU_Sigma'] = np.nan
        df['OU_Z'] = np.nan
        
        # Rolling Calibration for Hurst and OU (Needs minimum window)
        prices = df['Close'].values
        
        for i in range(self.window * 2, len(prices)):
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

        # Formatting bands for UI
        df['Upper_Band'] = df['OU_Mean'] + (self.ou_threshold * df['OU_Sigma'])
        df['Lower_Band'] = df['OU_Mean'] - (self.ou_threshold * df['OU_Sigma'])
        df['Mean'] = df['OU_Mean'] # For backward compat with app.js
        df['Z_Score'] = df['OU_Z'] # For backward compat with app.js
        
        # Mark anomalies
        # Anomaly threshold: 
        # 1. Math dictates OU_Z > ou_threshold (Price is vastly un-equilibrated)
        # 2. Regime dictates Hurst < 0.5 (We are in a mean-reverting regime, not a breakout trend)
        
        df['Is_Anomaly'] = (abs(df['OU_Z']) >= self.ou_threshold) & (df['Hurst'] < 0.5)
        df['Anomaly_Type'] = np.where(
            (df['OU_Z'] <= -self.ou_threshold) & (df['Hurst'] < 0.5), 'OVERSOLD',
            np.where((df['OU_Z'] >= self.ou_threshold) & (df['Hurst'] < 0.5), 'OVERBOUGHT', 'NORMAL')
        )
        
        return df
    
    def find_anomalies(self, df: pd.DataFrame) -> List[Dict]:
        """Find all anomaly points with their candle data."""
        anomalies = []
        
        for i in range(len(df)):
            row = df.iloc[i]
            if row['Is_Anomaly']:
                anomaly = {
                    'index': i,
                    'time': str(row.name),
                    'type': row['Anomaly_Type'],
                    'z_score': float(row['Z_Score']),
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
                    if row['Anomaly_Type'] == 'OVERSOLD':
                        # For long: next candle should be green AND close above its open AND break anomaly high
                        is_green = next_row['Close'] > next_row['Open']
                        broke_high = next_row['High'] > row['High']
                        anomaly['confirmed'] = bool(is_green and broke_high)
                        anomaly['entry_trigger'] = float(next_row['Close']) # Enter on confirmation candle close
                        anomaly['stop_loss'] = float(row['Low'])
                        anomaly['direction'] = 'LONG'
                    else:  # OVERBOUGHT
                        # For short: next candle should be red AND close below its open AND break anomaly low
                        is_red = next_row['Close'] < next_row['Open']
                        broke_low = next_row['Low'] < row['Low']
                        anomaly['confirmed'] = bool(is_red and broke_low)
                        anomaly['entry_trigger'] = float(next_row['Close']) # Enter on confirmation candle close
                        anomaly['stop_loss'] = float(row['High'])
                        anomaly['direction'] = 'SHORT'
                else:
                    anomaly['confirmed'] = False
                    anomaly['entry_trigger'] = None
                    anomaly['stop_loss'] = None
                    anomaly['direction'] = 'LONG' if row['Anomaly_Type'] == 'OVERSOLD' else 'SHORT'
                
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
            
            # Asymmetrical Take Profits based on OU Equlibrium
            tp1 = mean  # Mean Reversion Target (Equilibrium)
            tp2 = mean + (latest['OU_Sigma'] * 1.5)  # Momentum cascade
            tp3 = mean + (latest['OU_Sigma'] * 3.0)  # Extreme tail event
        else:
            direction = "SHORT"
            # Ultimate Sniper Matrix: Deep Golden Ratio 61.8% Limit Order inside the anomaly sweep
            pullback_target = anomaly_high - ((anomaly_high - anomaly_low) * 0.382) # 0.382 from top = 0.618 from bottom
            entry_trigger = pullback_target if is_confirmation_candle else anomaly_low
            
            # Micro Stop-Loss: Placed exactly at the absolute top of the anomaly with a 0.05 ATR noise filter
            stop_loss = anomaly_high + (atr * 0.05)  
            
            # Asymmetrical Take Profits based on OU Equlibrium
            tp1 = mean
            tp2 = mean - (latest['OU_Sigma'] * 1.5)
            tp3 = mean - (latest['OU_Sigma'] * 3.0)
        
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
                "tp2": {"price": round(tp2, 2), "rr": round(abs(tp2-entry_trigger)/risk, 1) if risk > 0 else 0, "label": "μ ± 1σ Momentum"},
                "tp3": {"price": round(tp3, 2), "rr": round(abs(tp3-entry_trigger)/risk, 1) if risk > 0 else 0, "label": "μ ± 2σ Extreme"},
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
    
    def send_discord_alert(self, anomaly: Dict, ticker: str, asset_name: str, current_price: float):
        """Send Rich Embed alert to Discord."""
        if not self.discord_webhook_url:
            return

        # Handle multiple webhooks
        webhooks = self.discord_webhook_url
        if isinstance(webhooks, str):
            webhooks = [webhooks]

        # Colors: Green (5763719) for Long, Red (15158332) for Short
        color = 5763719 if anomaly['direction'] == 'LONG' else 15158332
        
        # Calculate Risk/Reward Targets
        entry = anomaly.get('entry_trigger', 0)
        sl = anomaly.get('stop_loss', 0)
        risk = abs(entry - sl)
        
        if anomaly['direction'] == 'LONG':
            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 2.5)
            tp3 = entry + (risk * 4.0)
        else:
            tp1 = entry - (risk * 1.5)
            tp2 = entry - (risk * 2.5)
            tp3 = entry - (risk * 4.0)

        embed = {
            "title": f"QUANT SIGNAL [{ticker}]: {anomaly['direction']}",
            "description": (
                f"**Asset:** {asset_name}\n"
                f"**Pattern:** OU Dispersion Anomaly (Z-Score: {anomaly['z_score']:.2f})\n"
                f"**Regime:** Mean Reverting (Hurst: {anomaly.get('hurst', 0.40):.2f})\n"
                f"**Status:** CONFIRMED ENTRY (MARKET)"
            ),
            "color": color,
            "fields": [
                {"name": "ENTRY PRICE (MARKET)", "value": f"**${entry:,.2f}**", "inline": True},
                {"name": "STOP LOSS", "value": f"${sl:,.2f}", "inline": True},
                {"name": "RISK DISTANCE", "value": f"${risk:,.2f}", "inline": True},
                
                {"name": "━━━━━━━━━━━━━━━━━━━━", "value": "", "inline": False},
                
                {"name": "TARGET 1 (Mean TP)", "value": f"${tp1:,.2f}", "inline": True},
                {"name": "TARGET 2 (2.0 ATR)", "value": f"${tp2:,.2f}", "inline": True},
                {"name": "TARGET 3 (3.5 ATR)", "value": f"${tp3:,.2f}", "inline": True}
            ],
            "footer": {"text": f"Yield Anomaly Engine | {anomaly['time'][5:16]}"},
            "thumbnail": {"url": "https://cdn-icons-png.flaticon.com/512/3310/3310624.png" if anomaly['direction'] == 'SHORT' else "https://cdn-icons-png.flaticon.com/512/3310/3310645.png"}
        }
        
        payload = {
            "content": "Signal Alert\n"
                       "Quant Analysis Deverloped by <@732560547345858570>\n"
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
        """Perform complete trading analysis."""
        df, resolved = self.fetch_data(ticker)
        df = self.calculate_indicators(df)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        
        z_score = latest['OU_Z']
        hurst = latest['Hurst']
        atr = latest['ATR'] if not pd.isna(latest['ATR']) else 0
        
        signal = self.get_signal(z_score, hurst)
        trade_setup = self.generate_trade_setup(latest, prev, atr, resolved)
        
        # Use a specific slice for anomaly detection to ensure consistency
        recent_df = df.tail(50)
        anomalies = self.find_anomalies(recent_df)  # Last 50 candles
        
        # Check for alerts on Confirmed Anomalies
        if self.discord_webhook_url and anomalies:
            latest_anomaly = anomalies[-1]
            slice_len = len(recent_df)
            
            # Freshness Check: Only alert if anomaly is recent (last 2 candles of the slice)
            # This prevents alerting on old signals when switching charts or restarting
            is_fresh = latest_anomaly['index'] >= slice_len - 2
            
            # Alert conditions: Confirmed AND Strong Signal (Z > Threshold) AND Fresh AND Regimental
            if (latest_anomaly.get('confirmed') and 
                abs(latest_anomaly['z_score']) >= self.ou_threshold and 
                is_fresh):
                
                last_alert_time = self.alert_history.get(resolved)
                
                if last_alert_time != latest_anomaly['time']:
                    self.send_discord_alert(
                        latest_anomaly, 
                        resolved, 
                        self.ASSET_NAMES.get(resolved, resolved),
                        float(latest['Close'])
                    )
                    self.alert_history[resolved] = latest_anomaly['time']
                    self.save_alert_history()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "data_timestamp": str(latest.name),
            "ticker": resolved,
            "asset_name": self.ASSET_NAMES.get(resolved, resolved),
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
        
        return {
            "ticker": resolved,
            "asset_name": self.ASSET_NAMES.get(resolved, resolved),
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
    
    assets = ['MNQ', 'MGC', 'ES']
    
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
