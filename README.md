# Yield Anomaly Detector 

I built this tool because I wanted a mathematically grounded way to find trading setups, rather than just staring at charts all day.

It's a **mean reversion** system that watches for "statistical glitches" in the market—moments where the price moves so aggressively that it's statistically likely to snap back (or at least pause).

## What it actually does

1.  **Watches the Market**: It pulls live data for **Bitcoin**, **Gold**, **NASDAQ**, and **S&P 500**.
2.  **Calculates Z-Scores**: It measures how "abnormal" the current price move is compared to the last 20 periods.
3.  **Signals Anomalies**:
    *   **Z-Score > 2.0**: Overbought. (Look for shorts).
    *   **Z-Score < -2.0**: Oversold. (Look for longs).
4.  **Validates Entries**: It doesn't just blindly buy. It waits for the next candle to confirm the reversal (e.g., a green candle after a crash) or a breakout of the anomaly candle.

## How to run it

You need Python installed. If you have that, just do this:

1.  **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the web server**
    ```bash
    python server.py
    ```

3.  **Open your browser**
    Go to [http://localhost:5001](http://localhost:5001). You'll see the dashboard with live charts.

### Or runs in functionality mode (CLI)
If you prefer the terminal like me, runs the engine directly to get a text report of all assets:

```bash
python quant_engine.py
```

## Features

*   **Web Dashboard**: A clean, dark-mode UI to visualize the Bollinger Bands and Anomaly points.
*   **Discord Alerts**: I added a webhook integration so it can ping a Discord channel when a confirmed setup appears (check `server.py` to add your own webhook URL).
*   **Trade Setups**: The system suggests specific **Entry Prices**, **Stop Losses**, and **Take Profit** targets based on volatility (ATR).

## The Math (Simple Version)

It computes the `Log Return` of the price, then finds the standard deviation over a rolling window (default 20 candles).
*   **Z-Score = (Current Return - Average Return) / Standard Deviation**

If the Z-Score is **±2.5**, that's a rare event (statistical anomaly). That's where the money is.

---
*Disclaimer: This is code, not financial advice. I use this to help me make decisions, but markets are crazy. Use at your own risk.*
