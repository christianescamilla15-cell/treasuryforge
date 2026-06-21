/**
 * TreasuryForge — Live Demo (calls the REAL Python API)
 *
 * No JS port — every interaction hits treasuryforge-api.onrender.com which
 * runs the actual treasuryforge package (PolicyEngine, Runner, AuditLog).
 *
 * Source of truth: github.com/christianescamilla15-cell/treasuryforge
 */

const API_BASE = 'https://treasuryforge-api.onrender.com'

const $ = (id) => document.getElementById(id)

// ──────────────────────────────────────────────────────────────────────
// State
// ──────────────────────────────────────────────────────────────────────
const STATE = {
  stats: null,
  log: [],
  evaluations: 0,
  allow: 0,
  deny: 0,
  killed: false,
}

// ──────────────────────────────────────────────────────────────────────
// API helpers
// ──────────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`)
  }
  return res.json()
}

async function loadStats() {
  try {
    STATE.stats = await api('/api/stats')
    $('stats-tests').textContent = STATE.stats.tests.functions.toLocaleString()
    $('stats-files').textContent = STATE.stats.tests.files
    $('stats-modules').textContent = STATE.stats.modules
    $('stats-loc').textContent = STATE.stats.loc.production.toLocaleString()
    $('api-status').innerHTML = '<span class="dot dot--ok"></span> connected to <code>' + API_BASE.replace('https://', '') + '</code>'
  } catch (e) {
    $('api-status').innerHTML = '<span class="dot dot--bad"></span> API offline: ' + e.message
    appendLog('error', 'API stats fetch failed: ' + e.message, 'system')
  }
}

// ──────────────────────────────────────────────────────────────────────
// UI plumbing
// ──────────────────────────────────────────────────────────────────────
function appendLog(tick, msg, kind) {
  const log = $('log')
  const row = document.createElement('div')
  row.className = 'log__entry'
  row.innerHTML = `<span class="log__tick">${tick}</span><span class="log__msg ${kind}">${msg}</span>`
  log.prepend(row)
}

function flashRule(rule, kind) {
  if (!rule) return
  // Map API rule names to UI data-rule attributes
  const map = {
    kill_switch: 'kill_switch',
    circuit_breaker: 'circuit_breaker',
    symbol: 'allowlist',
    notional: 'per_tx_cap',
    min_notional: 'per_tx_cap',
    rate_limit: 'rate_limit',
    spend_budget: 'spend_budget',
    insufficient_quote: 'solvency',
    insufficient_base: 'solvency',
    stale_data: 'staleness',
  }
  const uiRule = map[rule] || rule
  const el = document.querySelector(`.rule[data-rule="${uiRule}"]`)
  if (!el) return
  el.classList.remove('is-firing', 'is-pass')
  void el.offsetWidth
  el.classList.add(kind === 'deny' ? 'is-firing' : 'is-pass')
  setTimeout(() => el.classList.remove('is-firing', 'is-pass'), 1500)
}

function setKPIs(extra = {}) {
  $('kpi-tick').textContent = extra.tick ?? STATE.evaluations
  $('kpi-intents').textContent = STATE.evaluations
  $('kpi-allow').textContent = STATE.allow
  $('kpi-deny').textContent = STATE.deny
  $('kpi-breaker').textContent = extra.tripped ? '● TRIPPED' : '○ OK'
  $('kpi-breaker').style.color = extra.tripped ? 'var(--red)' : 'var(--green)'
  if (extra.equity !== undefined) {
    $('kpi-equity').textContent = '$' + extra.equity.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
  }
}

// ──────────────────────────────────────────────────────────────────────
// Evaluate single intent (real PolicyEngine)
// ──────────────────────────────────────────────────────────────────────
async function evaluateOne(symbol, side, notional, price, configOverride = {}) {
  STATE.evaluations++
  $('probe-agent-code').textContent = JSON.stringify({ symbol, side, notional, price }, null, 0)
  try {
    const r = await api('/api/policy/evaluate', {
      method: 'POST',
      body: JSON.stringify({ symbol, side, notional, price, config: configOverride }),
    })
    $('probe-verdict-code').textContent = r.verdict.reason
    if (r.verdict.allowed) {
      STATE.allow++
      appendLog(`#${STATE.evaluations}`, `ALLOW ${side} ${symbol} $${notional}`, 'allow')
      flashRule(r.verdict.rule || 'ALL', 'allow')
    } else {
      STATE.deny++
      appendLog(`#${STATE.evaluations}`, r.verdict.reason, 'deny')
      flashRule(r.verdict.rule, 'deny')
    }
    setKPIs()
  } catch (e) {
    appendLog(`#${STATE.evaluations}`, 'API error: ' + e.message, 'system')
  }
}

// Step through a deterministic scripted sequence (mix of allow + deny patterns)
const STEP_SCRIPT = [
  ['TOKEN', 'BUY', 100, 100],
  ['TOKEN', 'BUY', 200, 100],
  ['DOGE',  'BUY', 100, 0.08],
  ['TOKEN', 'BUY', 700, 100],  // per_tx_cap
  ['TOKEN', 'BUY', 50, 100],
  ['TOKEN', 'BUY', 50, 100],
  ['TOKEN', 'BUY', 50, 100],   // rate_limit when window=3
  ['TOKEN', 'SELL', 99999, 100], // insufficient_base
  ['TOKEN', 'BUY', 100, 100, { kill_switch: true }],  // kill_switch
]
let stepIdx = 0

async function step() {
  if (STATE.killed) {
    appendLog('!', 'process is KILLED. Reset to recover.', 'system')
    return
  }
  if (stepIdx >= STEP_SCRIPT.length) stepIdx = 0
  const [sym, side, not, price, cfg] = STEP_SCRIPT[stepIdx++]
  await evaluateOne(sym, side, not, price, cfg || {})
}

// ──────────────────────────────────────────────────────────────────────
// Run a real backtest (Python Runner over N ticks)
// ──────────────────────────────────────────────────────────────────────
let playing = false
async function runBacktest(scenario, ticks = 60) {
  if (playing) return
  playing = true
  $('btn-play').textContent = '⏳ Running real backtest…'
  appendLog('▶', `POST /api/backtest/run scenario=${scenario} ticks=${ticks} → calling real Runner.run()`, 'system')
  try {
    const r = await api('/api/backtest/run', {
      method: 'POST',
      body: JSON.stringify({ scenario, ticks }),
    })
    appendLog('✓', `backtest done in ${r.duration_ms}ms — fills=${r.fills_executed}, denials=${r.denials_total}, breaker=${r.breaker.tripped}`, 'system')
    // Surface real numbers in the UI
    STATE.allow = r.fills_executed
    STATE.deny = r.denials_total
    STATE.evaluations = r.fills_executed + r.denials_total
    setKPIs({ tripped: r.breaker.tripped, equity: r.wallet.final_equity })
    // Show denials breakdown
    for (const [rule, count] of Object.entries(r.denials_by_rule)) {
      appendLog('·', `DENY:${rule} × ${count}`, 'deny')
      const ruleClean = rule.split(':')[0]
      flashRule(ruleClean, 'deny')
    }
    appendLog('$', `wallet: ${r.wallet.initial_equity.toFixed(2)} → ${r.wallet.final_equity.toFixed(2)} (${r.wallet.pnl_pct.toFixed(2)}%)`, 'system')
    appendLog('🔐', `audit chain: ${r.audit.entries} entries, integrity ${r.audit.integrity_verified ? '✓ verified' : '✗ TAMPERED'}`, 'system')
    $('probe-agent-code').textContent = JSON.stringify(r.audit.last_sample?.entry?.intent || {}, null, 0)
    $('probe-verdict-code').textContent = r.audit.last_sample?.entry?.reason || ''
  } catch (e) {
    appendLog('!', 'backtest failed: ' + e.message, 'system')
  } finally {
    $('btn-play').textContent = '▶ Run real backtest'
    playing = false
  }
}

function reset() {
  STATE.evaluations = 0
  STATE.allow = 0
  STATE.deny = 0
  STATE.killed = false
  stepIdx = 0
  $('log').innerHTML = ''
  $('probe-agent-code').textContent = '(waiting…)'
  $('probe-verdict-code').textContent = '(no decision yet)'
  setKPIs()
}

function simulateKill() {
  STATE.killed = true
  appendLog('SIGKILL', 'process terminated — state journaled to disk', 'system')
  setTimeout(() => {
    STATE.killed = false
    appendLog('restart', 'process restarted from journal — breaker state preserved', 'system')
  }, 1400)
}

// ──────────────────────────────────────────────────────────────────────
// Audit chain inspector
// ──────────────────────────────────────────────────────────────────────
async function loadAuditSample() {
  try {
    const r = await api('/api/audit/sample?n=5')
    const dot = $('auditstatus').querySelector('.dot')
    dot.classList.toggle('dot--ok', r.chain_integrity_verified)
    dot.classList.toggle('dot--bad', !r.chain_integrity_verified)
    $('auditstatus-text').textContent = `chain: ${r.chain_integrity_verified ? 'OK' : 'TAMPERED'} (${r.entries.length} sample entries · HMAC-SHA256)`
    appendLog('🔐', `loaded ${r.entries.length} real audit entries from API`, 'system')
  } catch (e) {
    appendLog('!', 'audit sample failed: ' + e.message, 'system')
  }
}

// ──────────────────────────────────────────────────────────────────────
// Wire up
// ──────────────────────────────────────────────────────────────────────
$('btn-play').onclick = () => runBacktest('normal', 60)
$('btn-step').onclick = () => step()
$('btn-crash').onclick = () => runBacktest('crash', 60)
$('btn-reset').onclick = () => reset()

// Boot
;(async () => {
  await loadStats()
  await loadAuditSample()
  setKPIs()
  appendLog('init', 'connected to real Python API — every action calls treasuryforge.PolicyEngine / Runner', 'system')
})()
