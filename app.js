/**
 * Yield Anomaly Detection - Frontend Application
 * ==============================================
 * Handles API communication, chart rendering, trade setup display
 */

// Configuration
const API_BASE = '/api';
const REFRESH_INTERVAL = 5000; // 5 seconds (Real-Time Polling)

// State
let currentTicker = 'XAUUSD';
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
    hurstValue: document.getElementById('hurstValue'),
    zScore: document.getElementById('zScore'),
    ouMean: document.getElementById('ouMean'),
    atrValue: document.getElementById('atrValue'),
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
// Chart.js Configuration - Terminal Style
Chart.defaults.color = '#888888';
Chart.defaults.borderColor = '#222222';
Chart.defaults.font.family = "'Consolas', monospace";
Chart.defaults.font.size = 11;

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
                    borderColor: '#ff9900', // Bloomberg Amber
                    backgroundColor: 'rgba(255, 153, 0, 0.1)',
                    borderWidth: 1,
                    fill: false,
                    tension: 0,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                },
                {
                    label: 'Upper (+2σ)',
                    data: [],
                    borderColor: '#ff0000', // Red
                    borderWidth: 1,
                    borderDash: [2, 2],
                    fill: false,
                    pointRadius: 0,
                },
                {
                    label: 'Lower (-2σ)',
                    data: [],
                    borderColor: '#00ff00', // Green
                    borderWidth: 1,
                    borderDash: [2, 2],
                    fill: false,
                    pointRadius: 0,
                },
                {
                    label: 'Mean',
                    data: [],
                    borderColor: '#444444', // Dark Gray
                    borderWidth: 1,
                    borderDash: [1, 1],
                    fill: false,
                    pointRadius: 0,
                },
            ]
        },
        options: {
            animation: false, // No animation for terminal feel
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
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}`
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
        // Only show error if status indicator exists
        if (elements.statusIndicator) updateStatus('error', error.message);
    }
}

/**
 * Update UI with analysis data
 */
// SAFELY UPDATE UI ELEMENTS
function set(idOrElement, value, className = null) {
    const el = typeof idOrElement === 'string' ? elements[idOrElement] : idOrElement;
    if (el) {
        el.textContent = value;
        if (className) el.className = className;
    }
}

function updateUI(data) {
    // Update title
    set('assetTitle', data.asset_name);

    // Update signal card
    const signalClass = getSignalClass(data.signal.severity);
    if (elements.signalCard) elements.signalCard.className = `signal-card ${signalClass}`;
    set('signalBadge', data.signal.signal.replace('_', ' '), `signal-badge ${signalClass}`);
    set('signalIcon', getSignalIcon(data.signal.severity));
    set('signalDescription', data.signal.description);

    // Update quant report
    set('currentPrice', formatPrice(data.price.current, data.ticker));

    if (data.analysis.hurst !== null) {
        const cls = `report-value mono ${data.analysis.hurst > 0.55 ? 'positive' : (data.analysis.hurst < 0.45 ? 'negative' : '')}`;
        set('hurstValue', formatDecimal(data.analysis.hurst, 3), cls);
    } else {
        set('hurstValue', '--');
    }

    if (data.analysis.z_score !== null) {
        const cls = `report-value mono ${getZScoreClass(data.analysis.z_score)}`;
        set('zScore', formatDecimal(data.analysis.z_score, 3), cls);
    } else {
        set('zScore', '--');
    }

    if (data.analysis.mean !== null) {
        set('ouMean', formatDecimal(data.analysis.mean, 2));
    } else {
        set('ouMean', '--');
    }

    // ATR and Volume
    if (data.analysis.atr !== null) {
        set('atrValue', `${formatDecimal(data.analysis.atr, 2)} (${formatDecimal(data.analysis.atr_percent, 2)}%)`);
    } else {
        set('atrValue', '--');
    }

    set('volumeRatio', '--');

    // Update confidence/factors (always display factors even if confidence ML is missing)
    updateConfidence(data);

    // Update trade setup
    updateTradeSetup(data.trade_setup);

    // Update timestamp
    set('lastUpdate', `UPDATED: ${new Date().toLocaleTimeString().toUpperCase()}`);
}

/**
 * Update confidence display
 */
function updateConfidence(data) {
    const confidence = data.confidence;

    if (!confidence || confidence.score === 0) {
        if (elements.confidenceValue) elements.confidenceValue.textContent = '--';
        if (elements.confidenceFill) elements.confidenceFill.style.width = '0%';
    } else {
        if (elements.confidenceValue) {
            elements.confidenceValue.textContent = `${confidence.score}% (${confidence.level})`;
            elements.confidenceValue.style.color = confidence.color;
        }
        if (elements.confidenceFill) {
            elements.confidenceFill.style.width = `${confidence.score}%`;
            elements.confidenceFill.className = 'confidence-fill';
            if (confidence.level === 'HIGH') {
                elements.confidenceFill.classList.add('high');
            } else if (confidence.level === 'MEDIUM') {
                elements.confidenceFill.classList.add('medium');
            } else {
                elements.confidenceFill.classList.add('low');
            }
        }
    }

    // Update factors if confidence object exists, otherwise display basic quant stats
    if (confidence && confidence.factors) {
        const f = confidence.factors;
        elements.confidenceFactors.innerHTML = `
            <span class="factor">HURST: ${formatDecimal(data.analysis.hurst, 2)}</span>
            <span class="factor">OU_THETA: ${formatDecimal(data.analysis.theta, 4)}</span>
            <span class="factor">OU_SIGMA: ${formatDecimal(data.analysis.std_dev, 2)}</span>
            <span class="factor">ATR: ${formatDecimal(data.analysis.atr, 2)}</span>
        `;
    } else if (elements.confidenceFactors && data.analysis) {
        // Fallback to show quant stats directly in the factors area if no ML confidence returned
        elements.confidenceFactors.innerHTML = `
            <span class="factor">HURST: ${formatDecimal(data.analysis.hurst, 2)}</span>
            <span class="factor">OU_THETA: ${formatDecimal(data.analysis.theta, 4)}</span>
            <span class="factor">OU_SIGMA: ${formatDecimal(data.analysis.std_dev, 2)}</span>
            <span class="factor">ATR: ${formatDecimal(data.analysis.atr, 2)}</span>
        `;
    }
}

/**
 * Update trade setup display
 */
function updateTradeSetup(tradeSetup) {
    if (!elements.noTradeMessage) return; // Guard clause

    if (!tradeSetup) {
        if (elements.noTradeMessage) elements.noTradeMessage.style.display = 'flex';
        if (elements.tradeSetupContent) elements.tradeSetupContent.style.display = 'none';
        if (elements.riskSection) elements.riskSection.style.display = 'none';
        return;
    }

    if (elements.noTradeMessage) elements.noTradeMessage.style.display = 'none';
    if (elements.tradeSetupContent) elements.tradeSetupContent.style.display = 'flex';
    if (elements.riskSection) elements.riskSection.style.display = 'block';

    // Direction badge
    const isLong = tradeSetup.direction === 'LONG';
    if (elements.tradeDirection) {
        elements.tradeDirection.innerHTML = `
            <span class="direction-badge ${isLong ? 'long' : 'short'}">${tradeSetup.direction}</span>
        `;
    }

    // Price levels
    set('entryPrice', `$${tradeSetup.entry_trigger.toLocaleString()}`);
    set('stopLoss', `$${tradeSetup.stop_loss.toLocaleString()}`);
    set('slPercent', `-${tradeSetup.risk_management.stop_distance_pct}%`);

    // Take profits
    set('tp1Price', `$${tradeSetup.take_profit.tp1.price.toLocaleString()}`);
    set('tp1RR', `R:R ${tradeSetup.take_profit.tp1.rr}`);

    set('tp2Price', `$${tradeSetup.take_profit.tp2.price.toLocaleString()}`);
    set('tp2RR', `R:R ${tradeSetup.take_profit.tp2.rr}`);

    set('tp3Price', `$${tradeSetup.take_profit.tp3.price.toLocaleString()}`);
    set('tp3RR', `R:R ${tradeSetup.take_profit.tp3.rr}`);

    // Risk management
    set('positionSize', `${tradeSetup.risk_management.position_size.toFixed(4)} units`);
    set('riskAmount', `$${tradeSetup.risk_management.risk_amount.toFixed(2)}`);
    set('riskPercent', `${tradeSetup.risk_management.risk_percent}%`);
    set('stopDistance', `$${tradeSetup.risk_management.stop_distance.toFixed(2)}`);
}

/**
 * Update charts with new data
 */
function updateCharts(data) {
    // Update OU Price Chart
    logReturnChart.data.labels = data.labels;
    logReturnChart.data.datasets[0].data = data.prices; // Plot price directly against bands
    logReturnChart.data.datasets[1].data = data.upper_band;
    logReturnChart.data.datasets[2].data = data.lower_band;
    logReturnChart.data.datasets[3].data = data.mean;
    logReturnChart.data.datasets[0].label = 'Price';
    logReturnChart.options.plugins.tooltip.callbacks.label = ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}`;
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
    const el = elements.statusIndicator;
    switch (status) {
        case 'loading':
            el.textContent = 'Status: Loading data...';
            el.style.color = '#bcbd22';
            break;
        case 'connected':
            el.textContent = 'Status: Connected (Real-Time)';
            el.style.color = '#2ca02c';
            break;
        case 'error':
            el.textContent = `Status: Error (${message})`;
            el.style.color = '#d62728';
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
    // Return text codes instead of emojis for scientific look
    const map = {
        'critical_long': '[CRIT BUY]',
        'long': '[BUY]',
        'neutral': '[NEUTRAL]',
        'watch': '[WATCH]',
        'short': '[SELL]',
        'critical_short': '[CRIT SELL]',
    };
    return map[severity] || '[WAIT]';
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
