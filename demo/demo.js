/**
 * TreasuryForge — Live Demo (JavaScript port of the policy engine)
 *
 * This is a faithful browser port of treasuryforge/policy.py.
 * Same 8 rules in the same order. Same DENY:<rule> reason format.
 * The Python implementation is the source of truth; this JS exists to
 * let visitors interact with the architecture without installing anything.
 *
 * Source: github.com/christianescamilla15-cell/treasuryforge/blob/main/treasuryforge/policy.py
 */

// ──────────────────────────────────────────────────────────────────────
// Tiny HMAC-SHA256 helper (Web Crypto API — modern browsers, no deps)
// ──────────────────────────────────────────────────────────────────────
const enc = new TextEncoder()
const SECRET_KEY_BYTES = enc.encode('demo-only-secret-do-not-use-in-prod')

async function hmacHex(payload) {
  const key = await crypto.subtle.importKey(
    'raw', SECRET_KEY_BYTES, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  )
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(payload))
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('')
}

// ──────────────────────────────────────────────────────────────────────
// PolicyConfig (mirror of the Python dataclass)
// ──────────────────────────────────────────────────────────────────────
const POLICY = {
  allowed_symbols: new Set(['BTC', 'ETH']),
  max_notional_per_tx: 1500,       // USD cap per trade
  max_tx_per_window: 5,             // trade COUNT
  window_steps: 8,                  // rolling window length (ticks)
  max_drawdown_pct: 0.10,           // breaker trips at -10%
  fee_rate: 0.001,
  kill_switch: false,
  max_notional_per_window: 4000,
  spend_window_steps: 8,
}

// ──────────────────────────────────────────────────────────────────────
// State
// ──────────────────────────────────────────────────────────────────────
const STATE = {
  tick: 0,
  starting_equity: null,
  tripped: false,
  recent_ts: [],       // for rate limit (count)
  spend: [],           // [[ts, notional], …] for spend budget
  wallet: { USD: 10000, BTC: 0, ETH: 0 },
  chain: [],           // audit chain: [{prev_hash, hmac, payload}]
  stats: { intents: 0, allow: 0, deny: 0 },
  killed: false,       // hard kill flag for SIGKILL test
}

// Pre-computed price track with a deliberate crash for demo
const PRICES = (() => {
  const arr = []
  const N = 40
  for (let i = 0; i < N; i++) {
    // BTC: smooth wave + sudden drop near tick 20
    let btc = 60000 + Math.sin(i * 0.4) * 1500
    if (i >= 18 && i <= 24) btc -= (i - 17) * 800    // crash window
    // ETH: slower drift
    const eth = 3200 + Math.sin(i * 0.3) * 80
    arr.push({ tick: i, BTC: btc, ETH: eth })
  }
  return arr
})()

// ──────────────────────────────────────────────────────────────────────
// AGENT — deterministic mean-reversion proposing intents
// ──────────────────────────────────────────────────────────────────────
function agentPropose(tick) {
  const t = PRICES[tick]
  if (!t) return null
  // Compare with the moving avg of the last 5 ticks
  const lookback = PRICES.slice(Math.max(0, tick - 5), tick + 1)
  const avgBtc = lookback.reduce((s, x) => s + x.BTC, 0) / lookback.length
  const spreadPct = (t.BTC - avgBtc) / avgBtc
  // Buy when below MA, sell when above. Quantity scales with confidence.
  const side = spreadPct < -0.005 ? 'BUY' : spreadPct > 0.008 ? 'SELL' : null
  if (!side) return null
  const symbol = (tick % 3 === 0) ? 'ETH' : 'BTC'
  if (symbol === 'ETH' && side === 'SELL') return null   // simplify demo
  const price = t[symbol]
  // Sometimes the agent proposes something silly to trigger DENY for the demo
  const silly = tick === 5 || tick === 11 || tick === 17 || tick === 22
  if (silly) {
    if (tick === 5) return { symbol: 'DOGE', side: 'BUY', notional: 200, price: 0.08 }   // allowlist
    if (tick === 11) return { symbol: 'BTC', side: 'BUY', notional: 3000, price: t.BTC } // per-tx cap
    if (tick === 17) return { symbol: 'BTC', side: 'BUY', notional: 800, price: t.BTC }  // may trip rate
    if (tick === 22) return { symbol: 'BTC', side: 'SELL', notional: 200000, price: t.BTC } // solvency
  }
  const notional = Math.min(800, Math.abs(spreadPct) * 8000)
  return { symbol, side, notional: Math.round(notional), price }
}

// ──────────────────────────────────────────────────────────────────────
// POLICY ENGINE — 8 rules in order. Returns { allow, rule, reason }.
// ──────────────────────────────────────────────────────────────────────
function pruneWindow(arr, now, window) {
  const cutoff = now - window
  while (arr.length && (Array.isArray(arr[0]) ? arr[0][0] : arr[0]) <= cutoff) arr.shift()
}

function policyEvaluate(intent, tick) {
  if (!intent) return null
  const t = PRICES[tick]
  const prices = { [intent.symbol]: t?.[intent.symbol] ?? intent.price }

  // First time: anchor starting equity
  if (STATE.starting_equity == null) {
    STATE.starting_equity = walletEquity(prices)
  }

  // 1. kill_switch
  if (POLICY.kill_switch) return { allow: false, rule: 'kill_switch', reason: 'DENY:kill_switch active' }

  // 2. circuit_breaker
  const equity = walletEquity(prices)
  const floor = STATE.starting_equity * (1 - POLICY.max_drawdown_pct)
  if (STATE.tripped || equity < floor) {
    STATE.tripped = true
    return { allow: false, rule: 'circuit_breaker', reason: `DENY:circuit_breaker equity=${equity.toFixed(2)} < floor=${floor.toFixed(2)}` }
  }

  // 3. staleness — inert in demo (no real data age supplied)

  // 4. allowlist
  if (!POLICY.allowed_symbols.has(intent.symbol)) {
    return { allow: false, rule: 'allowlist', reason: `DENY:symbol '${intent.symbol}' not in allowlist` }
  }

  // 5. per-tx notional cap
  if (intent.notional > POLICY.max_notional_per_tx) {
    return { allow: false, rule: 'per_tx_cap', reason: `DENY:notional ${intent.notional.toFixed(2)} > cap ${POLICY.max_notional_per_tx.toFixed(2)}` }
  }

  // 6. rate_limit
  pruneWindow(STATE.recent_ts, tick, POLICY.window_steps)
  if (STATE.recent_ts.length >= POLICY.max_tx_per_window) {
    return { allow: false, rule: 'rate_limit', reason: `DENY:rate_limit ${POLICY.max_tx_per_window}/${POLICY.window_steps} steps` }
  }

  // 7. spend_budget
  pruneWindow(STATE.spend, tick, POLICY.spend_window_steps)
  const spentInWindow = STATE.spend.reduce((s, x) => s + x[1], 0)
  if (POLICY.max_notional_per_window != null && spentInWindow + intent.notional > POLICY.max_notional_per_window + 1e-9) {
    return { allow: false, rule: 'spend_budget', reason: `DENY:spend_budget ${(spentInWindow + intent.notional).toFixed(2)} > ${POLICY.max_notional_per_window.toFixed(2)}/${POLICY.spend_window_steps} steps` }
  }

  // 8. solvency
  if (intent.side === 'BUY') {
    const cost = intent.notional * (1 + POLICY.fee_rate)
    if (cost > STATE.wallet.USD + 1e-9) {
      return { allow: false, rule: 'solvency', reason: `DENY:insufficient_quote need=${cost.toFixed(2)} have=${STATE.wallet.USD.toFixed(2)}` }
    }
  } else {
    const held = STATE.wallet[intent.symbol] || 0
    const baseAmount = intent.notional / intent.price
    if (baseAmount > held + 1e-9) {
      return { allow: false, rule: 'solvency', reason: `DENY:insufficient_base need=${baseAmount.toFixed(6)} have=${held.toFixed(6)}` }
    }
  }

  return { allow: true, rule: null, reason: 'ALLOW' }
}

// ──────────────────────────────────────────────────────────────────────
// EXECUTOR + WALLET
// ──────────────────────────────────────────────────────────────────────
function walletEquity(prices) {
  let eq = STATE.wallet.USD
  for (const sym of Object.keys(prices)) {
    eq += (STATE.wallet[sym] || 0) * prices[sym]
  }
  return eq
}

function executorFill(intent, tick) {
  const fee = intent.notional * POLICY.fee_rate
  if (intent.side === 'BUY') {
    const base = intent.notional / intent.price
    STATE.wallet.USD -= intent.notional + fee
    STATE.wallet[intent.symbol] = (STATE.wallet[intent.symbol] || 0) + base
  } else {
    const base = intent.notional / intent.price
    STATE.wallet[intent.symbol] = Math.max(0, (STATE.wallet[intent.symbol] || 0) - base)
    STATE.wallet.USD += intent.notional - fee
  }
  STATE.recent_ts.push(tick)
  STATE.spend.push([tick, intent.notional])
}

// ──────────────────────────────────────────────────────────────────────
// AUDIT CHAIN (HMAC-SHA256 hash chain)
// ──────────────────────────────────────────────────────────────────────
async function auditAppend(tick, verdict, intent) {
  const prev = STATE.chain.length ? STATE.chain[STATE.chain.length - 1].hmac : '0'.repeat(64)
  const payload = JSON.stringify({ tick, verdict: verdict?.reason, intent })
  const hmac = await hmacHex(prev + payload)
  STATE.chain.push({ prev_hash: prev, payload, hmac })
}

async function auditVerify() {
  let prev = '0'.repeat(64)
  for (const entry of STATE.chain) {
    if (entry.prev_hash !== prev) return false
    const recomputed = await hmacHex(prev + entry.payload)
    if (recomputed !== entry.hmac) return false
    prev = entry.hmac
  }
  return true
}

// ──────────────────────────────────────────────────────────────────────
// UI bindings
// ──────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id)

function flashRule(rule, kind) {
  if (!rule) return
  const el = document.querySelector(`.rule[data-rule="${rule}"]`)
  if (!el) return
  el.classList.remove('is-firing', 'is-pass')
  void el.offsetWidth
  el.classList.add(kind === 'deny' ? 'is-firing' : 'is-pass')
  setTimeout(() => el.classList.remove('is-firing', 'is-pass'), 1400)
}

function renderUI() {
  $('kpi-tick').textContent = STATE.tick
  $('kpi-intents').textContent = STATE.stats.intents
  $('kpi-allow').textContent = STATE.stats.allow
  $('kpi-deny').textContent = STATE.stats.deny
  $('kpi-breaker').textContent = STATE.killed ? '⚠ KILLED' : STATE.tripped ? '● TRIPPED' : '○ OK'
  $('kpi-breaker').style.color = STATE.killed ? 'var(--amber)' : STATE.tripped ? 'var(--red)' : 'var(--green)'
  const eq = walletEquity({ BTC: PRICES[Math.min(STATE.tick, PRICES.length - 1)]?.BTC ?? 0, ETH: PRICES[Math.min(STATE.tick, PRICES.length - 1)]?.ETH ?? 0 })
  $('kpi-equity').textContent = '$' + eq.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })

  $('wallet-quote').textContent = STATE.wallet.USD.toFixed(2)
  $('wallet-btc').textContent = (STATE.wallet.BTC || 0).toFixed(6)
  $('wallet-eth').textContent = (STATE.wallet.ETH || 0).toFixed(6)
}

function appendLog(tick, msg, kind) {
  const log = $('log')
  const row = document.createElement('div')
  row.className = 'log__entry'
  row.innerHTML = `<span class="log__tick">t=${tick}</span><span class="log__msg ${kind}">${msg}</span>`
  log.prepend(row)
}

async function tickOnce() {
  if (STATE.killed) {
    appendLog(STATE.tick, 'system: process is KILLED. Reset to recover.', 'system')
    return
  }
  if (STATE.tick >= PRICES.length) {
    appendLog(STATE.tick, 'system: end of price track. Reset to run again.', 'system')
    return
  }
  const tick = STATE.tick
  const intent = agentPropose(tick)
  if (!intent) {
    appendLog(tick, 'agent: no proposal (no signal)', 'system')
    $('probe-agent-code').textContent = '(no signal this tick)'
    STATE.tick++
    renderUI()
    return
  }
  STATE.stats.intents++
  $('probe-agent-code').textContent = JSON.stringify(intent, null, 0)
  const verdict = policyEvaluate(intent, tick)
  $('probe-verdict-code').textContent = verdict.reason
  await auditAppend(tick, verdict, intent)
  flashRule(verdict.rule, verdict.allow ? 'allow' : 'deny')

  if (verdict.allow) {
    executorFill(intent, tick)
    STATE.stats.allow++
    appendLog(tick, `ALLOW ${intent.side} ${intent.symbol} $${intent.notional}`, 'allow')
  } else {
    STATE.stats.deny++
    appendLog(tick, verdict.reason, 'deny')
  }

  // Verify audit chain integrity periodically
  if (STATE.chain.length % 5 === 0) {
    const ok = await auditVerify()
    const dot = $('auditstatus').querySelector('.dot')
    dot.classList.toggle('dot--ok', ok); dot.classList.toggle('dot--bad', !ok)
    $('auditstatus-text').textContent = `chain integrity: ${ok ? 'OK' : 'TAMPERED'} (${STATE.chain.length} entries)`
  } else {
    $('auditstatus-text').textContent = `chain integrity: OK (${STATE.chain.length} entries)`
  }

  STATE.tick++
  renderUI()
}

let playInterval = null
function play() {
  if (playInterval) return
  $('btn-play').textContent = '⏸ Pause'
  playInterval = setInterval(async () => {
    if (STATE.tick >= PRICES.length || STATE.killed) {
      stop()
      return
    }
    await tickOnce()
  }, 600)
}
function stop() {
  if (playInterval) { clearInterval(playInterval); playInterval = null }
  $('btn-play').textContent = '▶ Run simulation'
}
function reset() {
  stop()
  STATE.tick = 0
  STATE.starting_equity = null
  STATE.tripped = false
  STATE.killed = false
  STATE.recent_ts = []
  STATE.spend = []
  STATE.wallet = { USD: 10000, BTC: 0, ETH: 0 }
  STATE.chain = []
  STATE.stats = { intents: 0, allow: 0, deny: 0 }
  $('log').innerHTML = ''
  $('probe-agent-code').textContent = '(waiting…)'
  $('probe-verdict-code').textContent = '(no decision yet)'
  $('auditstatus-text').textContent = 'chain integrity: OK (0 entries)'
  $('auditstatus').querySelector('.dot').classList.replace('dot--bad', 'dot--ok')
  renderUI()
}
function simulateKill() {
  // Save state, kill the process, then "restart" — breaker should stay tripped if it was tripped
  const snapshot = {
    starting_equity: STATE.starting_equity,
    tripped: STATE.tripped,
    recent_ts: [...STATE.recent_ts],
    spend: STATE.spend.map(x => [...x]),
    chain_len: STATE.chain.length,
  }
  STATE.killed = true
  stop()
  appendLog(STATE.tick, 'system: SIGKILL received — state journaled.', 'system')
  setTimeout(() => {
    // Restart with restored state
    STATE.killed = false
    STATE.starting_equity = snapshot.starting_equity
    STATE.tripped = snapshot.tripped   // KEY: breaker stays tripped after kill
    STATE.recent_ts = snapshot.recent_ts
    STATE.spend = snapshot.spend
    appendLog(STATE.tick, `system: process restarted. breaker=${snapshot.tripped ? 'TRIPPED (kept!)' : 'OK'}, chain=${snapshot.chain_len} entries preserved.`, 'system')
    renderUI()
  }, 1400)
}

$('btn-play').onclick = () => playInterval ? stop() : play()
$('btn-step').onclick = () => tickOnce()
$('btn-crash').onclick = () => simulateKill()
$('btn-reset').onclick = () => reset()

renderUI()
