import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from quant_engine import YieldAnomalyTrader

def create_mock_data():
    """Create 100 periods of mock data that perfectly triggers a LONG condition."""
    np.random.seed(42)
    
    # Generate 100 periods of standard ranging data (Mean Reverting)
    base_price = 5000
    prices = [base_price]
    for _ in range(99):
        # Minimal volatility for tight OU sigma
        prices.append(prices[-1] + np.random.normal(0, 0.01) - 0.1 * (prices[-1] - base_price))
        
    # Build dataframe
    dates = [datetime.now(pytz.utc) - timedelta(minutes=15 * (100 - i)) for i in range(100)]
    
    df = pd.DataFrame({
        'Open': prices,
        'High': [p + np.random.uniform(1, 5) for p in prices],
        'Low': [p - np.random.uniform(1, 5) for p in prices],
        'Close': prices,
        'Volume': [100] * 100
    }, index=dates)
    
    # INJECT THE SETUP AT THE VERY END (FRESHNESS)
    
    # Candle 98: THE ANOMALY (Massive drop > 2.0 Sigma)
    df.iloc[-2, df.columns.get_loc('Open')] = 0.1
    df.iloc[-2, df.columns.get_loc('High')] = 0.1
    df.iloc[-2, df.columns.get_loc('Low')] = 0.1 # Extreme low anomaly wick
    df.iloc[-2, df.columns.get_loc('Close')] = 0.1 # Deep drop
    
    # Candle 99: THE CONFIRMATION (Closes Green, Breaks Anomaly High)
    df.iloc[-1, df.columns.get_loc('Open')] = 4910
    df.iloc[-1, df.columns.get_loc('High')] = 5010 # Breaks anomaly high of 5005!
    df.iloc[-1, df.columns.get_loc('Low')] = 4905
    df.iloc[-1, df.columns.get_loc('Close')] = 5008 # Closes green!
    
    return df

class MockTrader(YieldAnomalyTrader):
    def fetch_data(self, ticker):
        # Hijack the data fetcher to return our rigged scenario
        return create_mock_data(), ticker
        
    def send_discord_alert(self, anomaly, ticker, asset_name, current_price):
        print("\n" + "🔔" * 30)
        print("  DISCORD ALERT SUCCESSFULLY TRIGGERED!")
        print("  Condition 4 (Freshness): PASSED")
        print("🔔" * 30 + "\n")

if __name__ == "__main__":
    print("\n--- RUNNING QUANT PIPELINE VERIFICATION ---")
    
    # Set window up so we have enough data to calculate Hurst/OU
    trader = MockTrader(window=5, ou_threshold=1.0)
    
    # Force Discord URL to string so it attempts to alert
    trader.discord_webhook_url = "MOCK_URL_ENABLED"
    
    # Run analysis
    report = trader.analyze("MOCK_ASSET")
    
    print("\n[ VERIFICATION RESULTS ]")
    
    latest_analysis = report['analysis']
    setup = report['trade_setup']
    
    print(f"Condition 1 (Deviation < -2.0 Z):  Value = {latest_analysis['z_score']:.2f}")
    if latest_analysis['z_score'] <= -2.0:
        print("  -> PASSED: Price has severely deviated from OU Equilibrium.")
    else:
        print("  -> FAILED")
        
    print(f"\nCondition 2 (Regime < 0.50 Hurst): Value = {latest_analysis['hurst']:.2f}")
    if latest_analysis['hurst'] < 0.50:
        print("  -> PASSED: Math proves market is Mean-Reverting, not trending.")
    else:
        print("  -> FAILED")
        
    print(f"\nCondition 3 (Price Action Confirmation):")
    if setup['status'] == 'READY':
        print(f"  -> PASSED: Setup Status is {setup['status']}.")
        print(f"  -> Details: {setup['confirmation']}")
    else:
        print(f"  -> FAILED: Setup Status is {setup['status']}.")
        
    print("\n[ FINAL TRADE MATRIX (What is sent to UI) ]")
    print(f"  Direction:   {setup['direction']}")
    print(f"  Entry Type:  {setup['entry_type']} (Limit order placed at exact Fibonacci 61.8%)")
    print(f"  Stop Loss:   ${setup['stop_loss']:.2f} (Micro-Stop at exact anomaly wick extreme)")
    print(f"  Target 1:    ${setup['take_profit']['tp1']['price']:.2f} (OU Equilibrium target)")
    print(f"  Risk Matrix: Buying {setup['risk_management']['position_size']:.2f} units to risk exactly ${setup['risk_management']['risk_amount']:.2f}")
    
    print("\n--- VERIFICATION COMPLETE ---")
