# Yield Anomaly Detection System

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)](https://flask.palletsprojects.com/)

A quantitative analysis platform for detecting statistical anomalies in financial assets using **Logarithmic Returns** and **Z-Score** methodology.

![Dashboard Preview](https://img.shields.io/badge/Status-Active-brightgreen)

## 📊 Supported Assets

| Asset | Ticker | Symbol |
|-------|--------|--------|
| NASDAQ 100 | ^NDX | 📊 |
| Gold | GC=F | 🥇 |
| S&P 500 | ^GSPC | 📈 |
| Bitcoin | BTC-USD | ₿ |

---

## 🚀 Quick Start

### Installation

<details>
<summary><b>🍎 macOS / Linux</b></summary>

```bash
cd /path/to/Yield\ Anomaly
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Start the server:**
```bash
source venv/bin/activate
python server.py
```

</details>

<details>
<summary><b>🪟 Windows 11</b></summary>

1. **Install Python 3.10+** from [python.org](https://www.python.org/downloads/windows/)
   - ✅ Check "Add Python to PATH" during installation

2. **Open PowerShell or Command Prompt:**

```powershell
cd C:\path\to\Yield Anomaly
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

**Start the server:**
```powershell
.\venv\Scripts\activate
python server.py
```

> **Note:** If you get an execution policy error, run:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

</details>

<details>
<summary><b>🍓 Raspberry Pi (Dedicated Device)</b></summary>

Perfect for a 24/7 market monitor screen.

1. **Update System & Install Dependencies:**
   ```bash
   sudo apt update
   sudo apt install -y python3-venv python3-pip libatlas-base-dev chromium-browser
   ```

2. **Setup Project:**
   ```bash
   mkdir -p ~/yield-anomaly
   cd ~/yield-anomaly
   # (Copy files via SCP or Git Clone)
   
   python3 -m venv venv --system-site-packages
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Start Server:**
   ```bash
   source venv/bin/activate
   python server.py
   ```

4. **Launch Kiosk Mode (Full Screen Dashboard):**
   ```bash
   chromium-browser --kiosk --app=http://localhost:5001/chart
   ```
   *For the main dashboard, use `http://localhost:5001` instead.*

</details>

### 2. Open the Dashboard

Open **http://localhost:5001** in your browser.

### 3. Run Quant Engine (CLI Only)

```bash
# macOS/Linux
python quant_engine.py

# Windows
python quant_engine.py
```

Prints a console report for all 4 assets.

---

## 🔬 Methodology

### Logarithmic Returns
```
R_t = ln(P_t / P_{t-1})
```

### Z-Score (Anomaly Factor)
```
Z = (R_t - μ) / σ
```
Where μ = 20-period rolling mean, σ = 20-period rolling standard deviation.

### Signal Thresholds

| Z-Score | Signal | Description |
|---------|--------|-------------|
| Z < -2.5 | 🟢 CRITICAL BUY | Statistical Oversold - Mean Reversion Likely |
| Z < -2.0 | 📈 BUY | Oversold Zone - Consider Long Position |
| -1.5 < Z < 1.5 | ⚪ NEUTRAL | Within Normal Range - No Action |
| Z > +2.0 | 📉 SELL | Overbought Zone - Consider Short Position |
| Z > +2.5 | ⚠️ CRITICAL SELL | Statistical Overbought - Mean Reversion Likely |

---

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyze/<ticker>` | GET | Full analysis for a single asset |
| `/api/chart-data/<ticker>` | GET | Time-series data for charting |
| `/api/analyze-all` | GET | Analysis for all 4 assets |
| `/api/config` | GET/POST | View or update configuration |

### Example Request

```bash
curl http://localhost:5001/api/analyze/BTC
```

### Example Response

```json
{
  "success": true,
  "data": {
    "ticker": "BTC-USD",
    "asset_name": "Bitcoin",
    "price": { "current": 89200.87 },
    "analysis": {
      "log_return": 0.000264,
      "z_score": 0.355,
      "upper_threshold": 0.002145,
      "lower_threshold": -0.002429
    },
    "signal": {
      "signal": "NEUTRAL",
      "description": "⚪ Within Normal Range - No Action"
    }
  }
}
```

---

## 📁 Project Structure

```
Yield Anomaly/
├── quant_engine.py    # Core quantitative analysis engine
├── server.py          # Flask API server
├── index.html         # Dashboard UI
├── style.css          # Premium dark-mode styling
├── app.js             # Frontend logic & Chart.js
├── requirements.txt   # Python dependencies
└── venv/              # Virtual environment
```

---

## ⚙️ Configuration

Default parameters (can be modified in `quant_engine.py` or via API):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `period` | 5d | Data period to fetch |
| `interval` | 15m | Candle interval |
| `window` | 20 | Rolling window size |
| `threshold` | 2.0 | Z-Score for standard signals |
| `critical_threshold` | 2.5 | Z-Score for critical signals |

---

## ⚠️ Disclaimer

**For educational purposes only.** This is not financial advice. Statistical anomalies do not guarantee future returns. Always conduct your own research and consider consulting a financial advisor before making investment decisions.

---

## 📜 License

MIT License - Feel free to use and modify.
