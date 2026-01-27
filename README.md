# Yield Anomaly Detector

## Overview

The Yield Anomaly Detector is a quantitative analysis tool designed to identify statistical anomalies in financial markets. By calculating real-time Z-Scores of log returns across multiple assets (NASDAQ 100, Gold, S&P 500, Bitcoin), the system detects overbought and oversold conditions based on mean reversion principles.

The system features a Flask-based backend for data processing and a real-time web dashboard for visualization.

## Methodology

The core strategy relies on the statistical properties of asset returns:

1.  **Log Returns**: Calculates the natural logarithm of price changes to normalize volatility.
2.  **Rolling Statistics**: Computes the mean and standard deviation over a defined window (default: 20 periods).
3.  **Z-Score Calculation**: Measures the distance of the current return from the historical mean in units of standard deviation.
    *   $$Z = \frac{R_t - \mu}{\sigma}$$
4.  **Anomaly Detection**: Signals are generated when the Z-Score exceeds defined thresholds (default: ±2.0σ), indicating a statistically significant deviation.

## Features

*   **Real-time Analysis**: Fetches and processes live market data.
*   **Web Dashboard**: Visualizes Z-Scores, Bollinger Bands, and price action.
*   **Trade Setup Generation**: Automatically calculates entry, stop-loss, and take-profit levels based on ATR (Average True Range).
*   **Discord Integration**: Sends alerts to configured webhooks upon confirming actionable signals.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository_url>
    cd yield-anomaly
    ```

2.  **Set up a virtual environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
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

Key parameters can be adjusted in `quant_engine.py` or via the API:
*   `window`: Rolling window size for statistics (default: 20).
*   `z_threshold`: Z-Score trigger level (default: 2.0).
*   `risk_percent`: Risk per trade for position sizing (default: 1.0%).

## Disclaimer

This software is for educational and research purposes only. It does not constitute financial advice. Trading financial markets involves significant risk.
