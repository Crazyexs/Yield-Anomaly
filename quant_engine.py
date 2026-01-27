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


class YieldAnomalyTrader:
    """
    Professional trading signals from yield anomalies.
    
    Strategy Rules:
        1. Detect anomaly when |Z-Score| > 2.0
        2. Wait for candle close confirmation  
        3. Entry trigger: Break of anomaly candle high (long) or low (short)
        4. Stop Loss: Below anomaly low (long) or above anomaly high (short)
        5. Take Profit: When Z-Score returns to 0 (mean reversion complete)
    """
    
    ASSET_MAPPING = {
        'NDX': '^NDX',
        'NAS100': '^NDX',
        'NASDAQ': '^NDX',
        'XAU': 'GC=F',
        'XAUUSD': 'GC=F',
        'GOLD': 'GC=F',
        'SPX': '^GSPC',
        'SP500': '^GSPC',
        'BTC': 'BTC-USD',
        'BTCUSD': 'BTC-USD',
        'BITCOIN': 'BTC-USD',
    }
    
    ASSET_NAMES = {
        '^NDX': 'NASDAQ 100',
        'GC=F': 'Gold (XAU/USD)',
        '^GSPC': 'S&P 500',
        'BTC-USD': 'Bitcoin',
    }
    
    def __init__(
        self, 
        period: str = "5d", 
        interval: str = "15m", 
        window: int = 20,
        atr_period: int = 14,
        z_threshold: float = 2.0,
        z_critical: float = 2.5,
        risk_percent: float = 1.0,
        account_balance: float = 10000.0,
        discord_webhook_url: str = None
    ):
        self.period = period
        self.interval = interval
        self.window = window
        self.atr_period = atr_period
        self.z_threshold = z_threshold
        self.z_critical = z_critical
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
        df = yf.download(resolved, period=self.period, interval=self.interval, progress=False)
        
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
        """Calculate all technical indicators."""
        df = df.copy()
        
        # Log Returns
        df['Log_Return'] = np.log(df['Close'] / df['Close'].shift(1))
        
        # Rolling Statistics
        df['Mean'] = df['Log_Return'].rolling(window=self.window).mean()
        df['Std_Dev'] = df['Log_Return'].rolling(window=self.window).std()
        
        # Z-Score
        df['Z_Score'] = (df['Log_Return'] - df['Mean']) / df['Std_Dev']
        
        # ATR for sizing
        high, low, close = df['High'], df['Low'], df['Close']
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = df['TR'].rolling(window=self.atr_period).mean()
        
        # Dynamic thresholds for visualization
        df['Upper_Band'] = df['Mean'] + (self.z_threshold * df['Std_Dev'])
        df['Lower_Band'] = df['Mean'] - (self.z_threshold * df['Std_Dev'])
        
        # Mark anomalies
        df['Is_Anomaly'] = abs(df['Z_Score']) >= self.z_threshold
        df['Anomaly_Type'] = np.where(
            df['Z_Score'] <= -self.z_threshold, 'OVERSOLD',
            np.where(df['Z_Score'] >= self.z_threshold, 'OVERBOUGHT', 'NORMAL')
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
                        # For long: next candle should be green OR break high
                        is_green = next_row['Close'] > next_row['Open']
                        broke_high = next_row['High'] > row['High']
                        anomaly['confirmed'] = bool(is_green or broke_high)
                        anomaly['entry_trigger'] = float(row['High'])
                        anomaly['stop_loss'] = float(row['Low'])
                        anomaly['direction'] = 'LONG'
                    else:  # OVERBOUGHT
                        # For short: next candle should be red OR break low
                        is_red = next_row['Close'] < next_row['Open']
                        broke_low = next_row['Low'] < row['Low']
                        anomaly['confirmed'] = bool(is_red or broke_low)
                        anomaly['entry_trigger'] = float(row['Low'])
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
        """Generate trade setup from current anomaly."""
        z_score = latest['Z_Score']
        
        if pd.isna(z_score) or abs(z_score) < self.z_threshold:
            return None
        
        is_long = z_score <= -self.z_threshold
        price = float(latest['Close'])
        
        # For LONG: entry above anomaly high, SL below anomaly low
        # For SHORT: entry below anomaly low, SL above anomaly high
        anomaly_high = float(latest['High'])
        anomaly_low = float(latest['Low'])
        
        if is_long:
            direction = "LONG"
            entry_trigger = anomaly_high  # Enter when price breaks above
            stop_loss = anomaly_low - (atr * 0.5)  # Below low with buffer
            
            # Take profits based on mean reversion
            risk = entry_trigger - stop_loss
            tp1 = entry_trigger + (risk * 1.5)  # 1.5R
            tp2 = entry_trigger + (risk * 2.5)  # 2.5R (near mean)
            tp3 = entry_trigger + (risk * 4.0)  # 4R (full reversal)
        else:
            direction = "SHORT"
            entry_trigger = anomaly_low  # Enter when price breaks below
            stop_loss = anomaly_high + (atr * 0.5)  # Above high with buffer
            
            risk = stop_loss - entry_trigger
            tp1 = entry_trigger - (risk * 1.5)
            tp2 = entry_trigger - (risk * 2.5)
            tp3 = entry_trigger - (risk * 4.0)
        
        # Position sizing
        risk_amount = self.account_balance * (self.risk_percent / 100)
        stop_distance = abs(entry_trigger - stop_loss)
        position_size = risk_amount / stop_distance if stop_distance > 0 else 0
        
        # Confirmation check
        is_confirmed = False
        confirmation_msg = "WAIT - Candle not closed yet"
        
        if prev is not None and not pd.isna(prev['Z_Score']):
            if is_long:
                # For long: check if current candle is green
                is_green = latest['Close'] > latest['Open']
                is_confirmed = is_green
                confirmation_msg = "CONFIRMED - Green candle" if is_green else "WAIT for green candle"
            else:
                # For short: check if current candle is red
                is_red = latest['Close'] < latest['Open']
                is_confirmed = is_red
                confirmation_msg = "CONFIRMED - Red candle" if is_red else "WAIT for red candle"
        
        return {
            "direction": direction,
            "status": "READY" if is_confirmed else "PENDING",
            "confirmation": confirmation_msg,
            "is_confirmed": is_confirmed,
            "current_price": round(price, 2),
            "entry_trigger": round(entry_trigger, 2),
            "entry_type": f"BUY STOP @ {entry_trigger:.2f}" if is_long else f"SELL STOP @ {entry_trigger:.2f}",
            "stop_loss": round(stop_loss, 2),
            "take_profit": {
                "tp1": {"price": round(tp1, 2), "rr": 1.5, "label": "Safe (50% position)"},
                "tp2": {"price": round(tp2, 2), "rr": 2.5, "label": "Mean Reversion"},
                "tp3": {"price": round(tp3, 2), "rr": 4.0, "label": "Full Reversal"},
            },
            "risk_management": {
                "risk_amount": round(risk_amount, 2),
                "position_size": round(position_size, 4),
                "stop_distance": round(stop_distance, 2),
                "stop_distance_pct": round((stop_distance / price) * 100, 2),
            },
            "anomaly_candle": {
                "high": round(anomaly_high, 2),
                "low": round(anomaly_low, 2),
            }
        }
    
    def get_signal(self, z_score: float) -> Dict:
        """Generate trading signal from Z-Score."""
        if pd.isna(z_score):
            return {
                "signal": "NO_DATA",
                "action": "WAIT",
                "description": "Insufficient data",
                "severity": "neutral"
            }
        
        z_abs = abs(z_score)
        
        if z_score <= -self.z_critical:
            return {
                "signal": "STRONG_BUY",
                "action": "BUY_STOP",
                "description": f"OVERSOLD ANOMALY (Z={z_score:.2f}) - Wait for confirmation",
                "severity": "critical_long"
            }
        elif z_score >= self.z_critical:
            return {
                "signal": "STRONG_SELL",
                "action": "SELL_STOP",
                "description": f"OVERBOUGHT ANOMALY (Z={z_score:.2f}) - Wait for confirmation",
                "severity": "critical_short"
            }
        elif z_score <= -self.z_threshold:
            return {
                "signal": "BUY",
                "action": "BUY_STOP",
                "description": f"Oversold Zone (Z={z_score:.2f}) - Watch for entry",
                "severity": "long"
            }
        elif z_score >= self.z_threshold:
            return {
                "signal": "SELL",
                "action": "SELL_STOP",
                "description": f"Overbought Zone (Z={z_score:.2f}) - Watch for entry",
                "severity": "short"
            }
        elif z_abs >= 1.5:
            return {
                "signal": "WATCH",
                "action": "WAIT",
                "description": f"Approaching threshold (Z={z_score:.2f})",
                "severity": "watch"
            }
        else:
            return {
                "signal": "NEUTRAL",
                "action": "WAIT",
                "description": f"Normal range (Z={z_score:.2f})",
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
            "title": f"QUANT SIGNAL: {anomaly['direction']} {ticker}",
            "description": (
                f"**Asset:** {asset_name}\n"
                f"**Pattern:** Statistical Anomaly (Z-Score: {anomaly['z_score']:.2f})\n"
                f"**Status:** CONFIRMED ENTRY"
            ),
            "color": color,
            "fields": [
                {"name": "ENTRY PRICE", "value": f"**${entry:,.2f}**", "inline": True},
                {"name": "STOP LOSS", "value": f"${sl:,.2f}", "inline": True},
                {"name": "RISK (1R)", "value": f"${risk:,.2f}", "inline": True},
                
                {"name": "━━━━━━━━━━━━━━━━━━━━", "value": "", "inline": False},
                
                {"name": "TARGET 1 (1.5R)", "value": f"${tp1:,.2f}", "inline": True},
                {"name": "TARGET 2 (2.5R)", "value": f"${tp2:,.2f}", "inline": True},
                {"name": "TARGET 3 (4.0R)", "value": f"${tp3:,.2f}", "inline": True}
            ],
            "footer": {"text": f"Yield Anomaly Engine | {anomaly['time'][5:16]}"},
            "thumbnail": {"url": "https://cdn-icons-png.flaticon.com/512/3310/3310624.png" if anomaly['direction'] == 'SHORT' else "https://cdn-icons-png.flaticon.com/512/3310/3310645.png"}
        }
        
        payload = {
            "content": "Signal Alert - Yield Anomaly Engine\n"
                       "Quantitative Analysis Signal",
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
        
        z_score = latest['Z_Score']
        atr = latest['ATR'] if not pd.isna(latest['ATR']) else 0
        
        signal = self.get_signal(z_score)
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
            
            # Alert conditions: Confirmed AND Strong Signal (Z > 2.0 or < -2.0) AND Fresh
            if (latest_anomaly.get('confirmed') and 
                abs(latest_anomaly['z_score']) >= self.z_threshold and 
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
                "log_return": float(latest['Log_Return']) if not pd.isna(latest['Log_Return']) else None,
                "z_score": float(z_score) if not pd.isna(z_score) else None,
                "mean": float(latest['Mean']) if not pd.isna(latest['Mean']) else None,
                "std_dev": float(latest['Std_Dev']) if not pd.isna(latest['Std_Dev']) else None,
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
                "z_threshold": self.z_threshold,
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
            "log_returns": df['Log_Return'].tolist(),
            "z_scores": df['Z_Score'].tolist(),
            "upper_band": df['Upper_Band'].tolist(),
            "lower_band": df['Lower_Band'].tolist(),
            "mean": df['Mean'].tolist(),
            "prices": df['Close'].tolist(),
            "highs": df['High'].tolist(),
            "lows": df['Low'].tolist(),
            "anomaly_markers": anomaly_markers,
        }


def print_trading_report(report: Dict) -> None:
    """Print a professional trading report."""
    print("\n" + "=" * 70)
    print(f"  QUANT TRADING SIGNAL: {report['asset_name']}")
    print("=" * 70)
    print(f"  Ticker: {report['ticker']}  |  Time: {report['data_timestamp']}")
    print("-" * 70)
    print(f"  Current Price:    ${report['price']['current']:,.2f}")
    print(f"  Log Return:       {report['analysis']['log_return']:.6f}" if report['analysis']['log_return'] else "  Log Return:       N/A")
    print(f"  Z-SCORE:          {report['analysis']['z_score']:.3f}" if report['analysis']['z_score'] else "  Z-SCORE:          N/A")
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


if __name__ == "__main__":
    trader = YieldAnomalyTrader(
        period="5d",
        interval="15m",
        window=20,
        z_threshold=2.0,
        z_critical=2.5,
        risk_percent=1.0,
        account_balance=10000.0
    )
    
    assets = ['NDX', 'XAU', 'SPX', 'BTC']
    
    print("\n" + "YIELD ANOMALY TRADING ENGINE".center(70))
    print("=" * 70)
    print("  Strategy: Mean Reversion | Z-Score Anomalies | Candle Confirmation")
    print("=" * 70)
    
    for asset in assets:
        try:
            report = trader.analyze(asset)
            print_trading_report(report)
        except Exception as e:
            print(f"\nError analyzing {asset}: {str(e)}\n")
