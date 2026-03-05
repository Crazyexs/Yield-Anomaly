# Yield Anomaly Detector

## Overview

The Yield Anomaly Detector is a highly advanced quantitative analysis tool designed to identify statistical anomalies in financial markets. It replaces basic moving averages and subjective technical analysis with rigorous stochastic mathematics, utilizing the **Hurst Exponent** and the **Ornstein-Uhlenbeck (OU) Stochastic Process**.

The system features a Flask-based backend for real-time tick-data processing and a React-style dashboard for visual quant strategy mapping.

## Methodology

The core strategy relies on the statistical properties of asset returns and regimes:

1.  **Hurst Exponent Regime Detection ($H$)**: Calculates the rolling Hurst Exponent to mathematically define the market regime.
    *   $H < 0.45$: Mean-Reverting Regime (Trades enabled)
    *   $0.45 \le H \le 0.55$: Random Walk
    *   $H > 0.55$: Trending Regime (Mean-reverting trades disabled)
2.  **Ornstein-Uhlenbeck Process**: Calibrates the exact SDE $dX = \theta(\mu - X)dt + \sigma dW$ against real-time data to find the absolute stochastic equilibrium.
3.  **Anomaly Detection**: Signals are generated when $H < 0.45$ and the price statically diverges from the OU Mean ($\mu \pm 2\sigma$).
4.  **Optimal Exits**: Take-profit targets are calculated based on the OU Mean equilibrium $\mu$, maximizing mathematically proven win-rates.

## Features

*   **Real-time Analysis**: Polling 1-minute to 15-minute interval data in real time via Yahoo Finance.
*   **Web Dashboard**: Visualizes the OU Model, Hurst Exponent, Volatility bands, and exact Entry/TP/SL limits.
*   **Discord Integration**: Sends alerts to configured webhooks upon confirming actionable signals in the underlying price action.

## Installation & Setup

### Prerequisites
*   Python 3.10 or higher
*   Git
*   Internet connection (Must allow traffic to `fc.yahoo.com` for `yfinance` data polling)

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/Crazyexs/Yield-Anomaly.git
    cd yield-anomaly
    ```

### Linux / macOS Setup

2.  **Set up the Virtual Environment & Install Dependencies**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    
    # Ensure advanced math libraries are installed
    pip install statsmodels hurst yfinance pandas flask requests
    
    # Install TradingView Datafeed (Required for true broker-matching prices)
    pip install git+https://github.com/rongardF/tvdatafeed.git
    ```

### Windows Setup

2.  **Set up the Virtual Environment & Install Dependencies**:
    ```cmd
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    
    # Ensure advanced math libraries are installed
    pip install statsmodels hurst yfinance pandas flask requests
    
    # Install TradingView Datafeed (Required for true broker-matching prices)
    pip install git+https://github.com/rongardF/tvdatafeed.git
    ```

## Usage

### Web Dashboard
Start the application server:
```bash
python server.py
```
Access the dashboard at `http://localhost:5001`.

### CLI Mode
Run the quantitative engine directly in the terminal for a text-based report:
```bash
python quant_engine.py
```

## Configuration

Key parameters can be adjusted in `server.py` and `quant_engine.py` or via the Dashboard API:
*   `window`: Rolling window size for OU calibration (default: `40`).
*   `ou_threshold`: Number of OU standard deviations ($\sigma$) required to trigger anomaly (default: `2.0`).
*   `risk_percent`: Risk per trade for position sizing defaults (default: `1.0%`).
*   `interval`: Tick frequency `15m` (Must respect Yahoo Finance API limits).

## Disclaimer

This software is for educational and research purposes only. It does not constitute financial advice. Trading financial markets involves significant risk.
