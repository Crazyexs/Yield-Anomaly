"""
Yield Anomaly Detection - Flask API Server
===========================================
RESTful API serving quantitative analysis data with trade setup.
"""

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from quant_engine import YieldAnomalyDetector
import os

app = Flask(__name__, static_folder='.')
CORS(app)
# Configuration
# Paste your Discord Webhook URL here or use environment variable
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1464301870804631614/rK3vDjuhGfn6rv1i6Q-X_XZgadLRruQ6odHo8dFRoi4pOOt-cbYE6GyPfpbRgueNlzxB","https://discord.com/api/webhooks/1464314703332376578/cufrj6UWVv1rWa-Io3wRskz2A2FxrwmbhJHUZ6QVuUt_0hJ32YBDb-Kb1015VkCfghPg"

# Initialize the trading engine
detector = YieldAnomalyDetector(
    period="5d",
    interval="15m",
    window=20,
    atr_period=14,
    z_threshold=2.0,
    z_critical=2.5,
    risk_percent=1.0,
    account_balance=10000.0,
    discord_webhook_url=DISCORD_WEBHOOK_URL
)


@app.route('/')
def index():
    """Serve the main dashboard."""
    return send_from_directory('.', 'index.html')


@app.route('/chart')
def chart_page():
    """Serve the anomaly chart page."""
    return send_from_directory('.', 'anomaly_chart.html')


@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files (CSS, JS)."""
    return send_from_directory('.', filename)


@app.route('/api/analyze/<ticker>')
def analyze(ticker):
    """
    Get full analysis for a specific ticker.
    
    Params:
        ticker: Asset identifier (NDX, XAU, SPX, BTC or direct ticker)
    
    Returns:
        JSON with complete quant analysis report
    """
    try:
        report = detector.analyze(ticker)
        return jsonify({
            "success": True,
            "data": report
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route('/api/chart-data/<ticker>')
def chart_data(ticker):
    """
    Get time-series data for charting.
    
    Params:
        ticker: Asset identifier
        limit: Number of data points (default: 100)
    
    Returns:
        JSON with labels, log_returns, thresholds for Chart.js
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        data = detector.get_chart_data(ticker, limit=limit)
        return jsonify({
            "success": True,
            "data": data
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route('/api/analyze-all')
def analyze_all():
    """
    Get analysis for all supported assets.
    
    Returns:
        JSON with analysis for NDX, XAU, SPX, BTC
    """
    results = {}
    assets = ['NDX', 'XAU', 'SPX', 'BTC']
    
    for asset in assets:
        try:
            results[asset] = detector.analyze(asset)
        except Exception as e:
            results[asset] = {"error": str(e)}
    
    return jsonify({
        "success": True,
        "data": results
    })


@app.route('/api/config', methods=['GET', 'POST'])
def config():
    """Get or update detector configuration."""
    global detector
    
    if request.method == 'POST':
        data = request.json
        old_history = detector.alert_history
        detector = YieldAnomalyDetector(
            period=data.get('period', '5d'),
            interval=data.get('interval', '15m'),
            window=data.get('window', 20),
            atr_period=data.get('atr_period', 14),
            z_threshold=data.get('z_threshold', 2.0),
            z_critical=data.get('z_critical', 2.5),
            risk_percent=data.get('risk_percent', 1.0),
            account_balance=data.get('account_balance', 10000.0),
            discord_webhook_url=data.get('discord_webhook_url', detector.discord_webhook_url)
        )
        detector.alert_history = old_history
        return jsonify({"success": True, "message": "Configuration updated"})
    
    return jsonify({
        "success": True,
        "config": {
            "period": detector.period,
            "interval": detector.interval,
            "window": detector.window,
            "atr_period": detector.atr_period,
            "z_threshold": detector.z_threshold,
            "z_critical": detector.z_critical,
            "risk_percent": detector.risk_percent,
            "account_balance": detector.account_balance,
            "discord_webhook_url": detector.discord_webhook_url
        }
    })


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  🚀 YIELD ANOMALY DETECTION API SERVER")
    print("=" * 60)
    print("  Dashboard: http://localhost:5001")
    print("  API Endpoints:")
    print("    GET /api/analyze/<ticker>     - Full analysis")
    print("    GET /api/chart-data/<ticker>  - Chart data")
    print("    GET /api/analyze-all          - All assets")
    print("    GET/POST /api/config          - Configuration")
    print("=" * 60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
