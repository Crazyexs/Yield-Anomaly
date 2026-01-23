/**
 * Yield Anomaly Detection - Frontend Application (Pro Edition)
 * =============================================================
 * Handles API communication, chart rendering, trade setup display
 */

// Configuration
const API_BASE = 'http://localhost:5001/api';
const REFRESH_INTERVAL = 30000; // 30 seconds

// State
let currentTicker = 'NDX';
let logReturnChart = null;
let zScoreChart = null;
let refreshTimer = null;

// DOM Elements
const elements = {
    statusIndicator: document.getElementById('statusIndicator'),
    lastUpdate: document.getElementById('lastUpdate'),
    assetTitle: document.getElementById('assetTitle'),
    signalCard: document.getElementById('signalCard'),
    signalBadge: document.getElementById('signalBadge'),
    signalIcon: document.getElementById('signalIcon'),
    signalDescription: document.getElementById('signalDescription'),
    currentPrice: document.getElementById('currentPrice'),
    logReturn: document.getElementById('logReturn'),
    zScore: document.getElementById('zScore'),
    atrValue: document.getElementById('atrValue'),
    volumeRatio: document.getElementById('volumeRatio'),
    // Confidence elements
    confidenceValue: document.getElementById('confidenceValue'),
    confidenceFill: document.getElementById('confidenceFill'),
    confidenceFactors: document.getElementById('confidenceFactors'),
    // Trade setup elements
    noTradeMessage: document.getElementById('noTradeMessage'),
    tradeSetupContent: document.getElementById('tradeSetupContent'),
    tradeDirection: document.getElementById('tradeDirection'),
    entryPrice: document.getElementById('entryPrice'),
    stopLoss: document.getElementById('stopLoss'),
    slPercent: document.getElementById('slPercent'),
    tp1Price: document.getElementById('tp1Price'),
    tp1RR: document.getElementById('tp1RR'),
    tp2Price: document.getElementById('tp2Price'),
    tp2RR: document.getElementById('tp2RR'),
    tp3Price: document.getElementById('tp3Price'),
    tp3RR: document.getElementById('tp3RR'),
    // Risk management
    riskSection: document.getElementById('riskSection'),
    positionSize: document.getElementById('positionSize'),
    riskAmount: document.getElementById('riskAmount'),
    riskPercent: document.getElementById('riskPercent'),
    stopDistance: document.getElementById('stopDistance'),
};

// Chart.js Configuration
Chart.defaults.color = '#9ca3af';
Chart.defaults.borderColor = 'rgba(75, 85, 99, 0.3)';
Chart.defaults.font.family = "'Inter', sans-serif";

/**
 * Initialize the application
 */
function init() {
    setupAssetButtons();
    initCharts();
    loadData(currentTicker);
    startAutoRefresh();
}

/**
 * Setup asset selection buttons
 */
function setupAssetButtons() {
    const buttons = document.querySelectorAll('.asset-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTicker = btn.dataset.ticker;
            loadData(currentTicker);
        });
    });
}

/**
 * Initialize Chart.js charts
 */
function initCharts() {
    // Log Return Chart
    const logReturnCtx = document.getElementById('logReturnChart').getContext('2d');
    logReturnChart = new Chart(logReturnCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Log Return',
                    data: [],
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
                {
                    label: 'Upper (+2σ)',
                    data: [],
                    borderColor: '#ef4444',
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    fill: false,
                    pointRadius: 0,
                },
                {
                    label: 'Lower (-2σ)',
                    data: [],
                    borderColor: '#10b981',
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    fill: false,
                    pointRadius: 0,
                },
                {
                    label: 'Mean',
                    data: [],
                    borderColor: '#6b7280',
                    borderWidth: 1,
                    borderDash: [2, 2],
                    fill: false,
                    pointRadius: 0,
                },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { boxWidth: 12, padding: 15, font: { size: 11 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    padding: 12,
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(6)}`
                    }
                }
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8, font: { size: 10 } } },
                y: { grid: { color: 'rgba(75, 85, 99, 0.2)' }, ticks: { callback: v => v.toFixed(4), font: { size: 10 } } }
            }
        }
    });

    // Z-Score Chart
    const zScoreCtx = document.getElementById('zScoreChart').getContext('2d');
    zScoreChart = new Chart(zScoreCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Z-Score',
                data: [],
                backgroundColor: [],
                borderColor: [],
                borderWidth: 1,
                borderRadius: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    padding: 12,
                    callbacks: { label: ctx => `Z-Score: ${ctx.parsed.y.toFixed(3)}` }
                }
            },
            scales: {
                x: { grid: { display: false }, ticks: { maxTicksLimit: 8, font: { size: 10 } } },
                y: { grid: { color: 'rgba(75, 85, 99, 0.2)' }, min: -4, max: 4, ticks: { stepSize: 1, font: { size: 10 } } }
            }
        }
    });
}

/**
 * Load data from API
 */
async function loadData(ticker) {
    updateStatus('loading');

    try {
        const [analysisRes, chartRes] = await Promise.all([
            fetch(`${API_BASE}/analyze/${ticker}`),
            fetch(`${API_BASE}/chart-data/${ticker}?limit=80`)
        ]);

        const analysisData = await analysisRes.json();
        const chartData = await chartRes.json();

        if (!analysisData.success || !chartData.success) {
            throw new Error(analysisData.error || chartData.error || 'Unknown error');
        }

        updateUI(analysisData.data);
        updateCharts(chartData.data);
        updateStatus('connected');

    } catch (error) {
        console.error('Error loading data:', error);
        updateStatus('error', error.message);
    }
}

/**
 * Update UI with analysis data
 */
function updateUI(data) {
    // Update title
    elements.assetTitle.textContent = data.asset_name;

    // Update signal card
    const signalClass = getSignalClass(data.signal.severity);
    elements.signalCard.className = `signal-card ${signalClass}`;
    elements.signalBadge.textContent = data.signal.signal.replace('_', ' ');
    elements.signalBadge.className = `signal-badge ${signalClass}`;
    elements.signalIcon.textContent = getSignalIcon(data.signal.severity);
    elements.signalDescription.textContent = data.signal.description;

    // Update quant report
    elements.currentPrice.textContent = formatPrice(data.price.current, data.ticker);

    if (data.analysis.log_return !== null) {
        elements.logReturn.textContent = formatDecimal(data.analysis.log_return, 6);
        elements.logReturn.className = `report-value mono ${data.analysis.log_return >= 0 ? 'positive' : 'negative'}`;
    } else {
        elements.logReturn.textContent = '--';
    }

    if (data.analysis.z_score !== null) {
        elements.zScore.textContent = formatDecimal(data.analysis.z_score, 3);
        elements.zScore.className = `report-value mono ${getZScoreClass(data.analysis.z_score)}`;
    } else {
        elements.zScore.textContent = '--';
    }

    // ATR and Volume
    if (data.analysis.atr !== null) {
        elements.atrValue.textContent = `${formatDecimal(data.analysis.atr, 2)} (${formatDecimal(data.analysis.atr_percent, 2)}%)`;
    } else {
        elements.atrValue.textContent = '--';
    }

    // STUB: Volume Ratio (Not present in current quant engine)
    elements.volumeRatio.textContent = '--';

    // Update confidence (if available)
    if (data.confidence) {
        updateConfidence(data.confidence);
    } else {
        // Clear confidence if not available
        elements.confidenceValue.textContent = '--';
        elements.confidenceFill.style.width = '0%';
    }

    // Update trade setup
    updateTradeSetup(data.trade_setup);

    // Update timestamp
    elements.lastUpdate.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
}

/**
 * Update confidence display
 */
function updateConfidence(confidence) {
    if (!confidence || confidence.score === 0) {
        elements.confidenceValue.textContent = '--';
        elements.confidenceFill.style.width = '0%';
        return;
    }

    elements.confidenceValue.textContent = `${confidence.score}% (${confidence.level})`;
    elements.confidenceValue.style.color = confidence.color;
    elements.confidenceFill.style.width = `${confidence.score}%`;

    // Set fill color class
    elements.confidenceFill.className = 'confidence-fill';
    if (confidence.level === 'HIGH') {
        elements.confidenceFill.classList.add('high');
    } else if (confidence.level === 'MEDIUM') {
        elements.confidenceFill.classList.add('medium');
    } else {
        elements.confidenceFill.classList.add('low');
    }

    // Update factors
    if (confidence.factors) {
        const f = confidence.factors;
        elements.confidenceFactors.innerHTML = `
            <span class="factor">Z: ${f.z_score_strength.points}/${f.z_score_strength.max}</span>
            <span class="factor">Vol: ${f.volume_confirmation.points}/${f.volume_confirmation.max}</span>
            <span class="factor">Trend: ${f.trend_alignment.points}/${f.trend_alignment.max}</span>
            <span class="factor">ATR: ${f.volatility_suitability.points}/${f.volatility_suitability.max}</span>
        `;
    }
}

/**
 * Update trade setup display
 */
function updateTradeSetup(tradeSetup) {
    if (!tradeSetup) {
        elements.noTradeMessage.style.display = 'flex';
        elements.tradeSetupContent.style.display = 'none';
        elements.riskSection.style.display = 'none';
        return;
    }

    elements.noTradeMessage.style.display = 'none';
    elements.tradeSetupContent.style.display = 'flex';
    elements.riskSection.style.display = 'block';

    // Direction badge
    const isLong = tradeSetup.direction === 'LONG';
    elements.tradeDirection.innerHTML = `
        <span class="direction-badge ${isLong ? 'long' : 'short'}">${tradeSetup.direction}</span>
    `;

    // Price levels
    elements.entryPrice.textContent = `$${tradeSetup.entry_price.toLocaleString()}`;
    elements.stopLoss.textContent = `$${tradeSetup.stop_loss.toLocaleString()}`;
    elements.slPercent.textContent = `-${tradeSetup.risk_management.stop_distance_percent}%`;

    // Take profits
    elements.tp1Price.textContent = `$${tradeSetup.take_profit.tp1.price.toLocaleString()}`;
    elements.tp1RR.textContent = `R:R ${tradeSetup.take_profit.tp1.rr_ratio}`;

    elements.tp2Price.textContent = `$${tradeSetup.take_profit.tp2.price.toLocaleString()}`;
    elements.tp2RR.textContent = `R:R ${tradeSetup.take_profit.tp2.rr_ratio}`;

    elements.tp3Price.textContent = `$${tradeSetup.take_profit.tp3.price.toLocaleString()}`;
    elements.tp3RR.textContent = `R:R ${tradeSetup.take_profit.tp3.rr_ratio}`;

    // Risk management
    elements.positionSize.textContent = `${tradeSetup.risk_management.position_size.toFixed(4)} units`;
    elements.riskAmount.textContent = `$${tradeSetup.risk_management.risk_amount.toFixed(2)}`;
    elements.riskPercent.textContent = `${tradeSetup.risk_management.risk_percent}%`;
    elements.stopDistance.textContent = `$${tradeSetup.risk_management.stop_distance.toFixed(2)}`;
}

/**
 * Update charts with new data
 */
function updateCharts(data) {
    // Update Log Return Chart
    logReturnChart.data.labels = data.labels;
    logReturnChart.data.datasets[0].data = data.log_returns;
    logReturnChart.data.datasets[1].data = data.upper_threshold;
    logReturnChart.data.datasets[2].data = data.lower_threshold;
    logReturnChart.data.datasets[3].data = data.mean;
    logReturnChart.update('none');

    // Update Z-Score Chart
    const colors = data.z_scores.map(z => getZScoreColor(z));
    zScoreChart.data.labels = data.labels;
    zScoreChart.data.datasets[0].data = data.z_scores;
    zScoreChart.data.datasets[0].backgroundColor = colors.map(c => c + '80');
    zScoreChart.data.datasets[0].borderColor = colors;
    zScoreChart.update('none');
}

/**
 * Update connection status
 */
function updateStatus(status, message = '') {
    const pulse = elements.statusIndicator.querySelector('.pulse');
    const text = elements.statusIndicator.querySelector('.status-text');

    switch (status) {
        case 'loading':
            pulse.style.background = '#eab308';
            text.textContent = 'Loading...';
            break;
        case 'connected':
            pulse.style.background = '#10b981';
            text.textContent = 'Connected';
            break;
        case 'error':
            pulse.className = 'pulse error';
            text.textContent = `Error: ${message}`;
            break;
    }
}

/**
 * Start auto-refresh
 */
function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => loadData(currentTicker), REFRESH_INTERVAL);
}

// Utility Functions
function formatPrice(price, ticker) {
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDecimal(value, decimals = 6) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    return Number(value).toFixed(decimals);
}

function getSignalClass(severity) {
    const map = {
        'critical_long': 'critical-buy',
        'long': 'buy',
        'neutral': 'neutral',
        'watch': 'watch',
        'short': 'sell',
        'critical_short': 'critical-sell',
    };
    return map[severity] || 'neutral';
}

function getSignalIcon(severity) {
    const map = {
        'critical_long': '🟢',
        'long': '📈',
        'neutral': '⚪',
        'watch': '👁️',
        'short': '📉',
        'critical_short': '⚠️',
    };
    return map[severity] || '⏳';
}

function getZScoreClass(z) {
    if (z < -2) return 'positive';
    if (z > 2) return 'negative';
    return '';
}

function getZScoreColor(z) {
    if (z < -2.5) return '#10b981';
    if (z < -2) return '#22c55e';
    if (z > 2.5) return '#ef4444';
    if (z > 2) return '#f97316';
    if (Math.abs(z) > 1.5) return '#eab308';
    return '#6366f1';
}

// Initialize
document.addEventListener('DOMContentLoaded', init);
