# Arquitectura · treasuryforge

Modelo C4: contexto → contenedores → componentes. Los diagramas son texto (Mermaid), se versionan con el código
y nombran módulos que existen (`treasuryforge/…`, `api/main.py`, `deploy/…`). Las decisiones están en
[`docs/adr/`](../adr/) y las reglas con sus pruebas en [`docs/reglas.md`](../reglas.md).

## 1. Contexto

```mermaid
C4Context
  title Contexto · treasuryforge
  Person(operador, "Operador (dueño)", "Configura límites, arma o desarma el agente, recibe reportes")
  Person(visitante, "Visitante", "Prueba la arquitectura en la demo del navegador")
  System(tf, "treasuryforge", "Agente de tesorería autónomo: el agente propone, la política dispone, la billetera ejecuta dentro de límites duros")
  System_Ext(bitso, "Bitso API", "Exchange: libros, saldo, órdenes firmadas con HMAC (llave sin retiro)")
  System_Ext(hl, "Hyperliquid API", "/info pública (velas, funding, libro) y /exchange con firma EIP-712 del agente")
  System_Ext(venues, "Otros exchanges (APIs públicas)", "Binance, OKX, Gate, Bybit, Bitget, MEXC, HTX, Coinbase: funding y precios para escaneo y backtest")
  System_Ext(tg, "Telegram Bot API", "Reportes de estado de sólo lectura")
  Rel(operador, tf, "Opera por systemd y scripts")
  Rel(visitante, tf, "Usa la demo", "HTTPS")
  Rel(tf, bitso, "Opera", "HTTPS")
  Rel(tf, hl, "Lee y opera", "HTTPS")
  Rel(tf, venues, "Lee datos públicos", "HTTPS")
  Rel(tf, tg, "Envía reportes", "HTTPS")
  Rel(tf, operador, "Notifica", "Telegram")
```

## 2. Contenedores

```mermaid
C4Container
  title Contenedores · treasuryforge
  Person(operador, "Operador")
  Person(visitante, "Visitante")
  System_Boundary(b, "treasuryforge") {
    Container(demo, "Demo web", "HTML + CSS + JS sin dependencias · Vercel", "demo/: dibuja las 8 reglas, el interruptor y la cadena de auditoría; llama a la API")
    Container(api, "API de la demo", "Python 3.11 · FastAPI · Docker en Render", "api/main.py: expone el motor REAL (evaluate, backtest, auditoría)")
    Container(nucleo, "Núcleo treasuryforge", "Python 3.11+ · sólo biblioteca estándar", "Agente, política, ejecutores, billetera, riesgo, protocolo de capital")
    Container(vivo, "Servicios en vivo", "systemd en un VPS", "run_live (fail-closed), run_autonomous (scalp), orquestador, sombra horaria, bitácora de spreads, reporte a Telegram")
    Container(scripts, "Scripts de investigación", "Python CLI", "scripts/: escaneos, backtests, validación en vivo por escalones")
    ContainerDb(estado, "Estado con cierre", "JSON en disco", "journal.py: WAL de una línea por evento + checkpoint atómico (os.replace)")
    ContainerDb(auditoria, "Bitácora de auditoría", "JSONL con cadena HMAC-SHA256", "audit.py: cualquier edición, borrado o reorden rompe la cadena")
    ContainerDb(mercado, "BD de mercado", "SQLite", "marketlab/store.py: velas y funding reales para reproducir sin red")
  }
  System_Ext(exchanges, "Exchanges", "Bitso, Hyperliquid y APIs públicas")
  System_Ext(tg, "Telegram")
  Rel(visitante, demo, "Usa", "HTTPS")
  Rel(demo, api, "Llama", "JSON/HTTPS · CORS limitado")
  Rel(api, nucleo, "Importa")
  Rel(vivo, nucleo, "Importa")
  Rel(scripts, nucleo, "Importa")
  Rel(operador, vivo, "systemctl / journalctl")
  Rel(nucleo, estado, "Lee y escribe")
  Rel(nucleo, auditoria, "Agrega")
  Rel(scripts, mercado, "Llena y reproduce")
  Rel(vivo, exchanges, "Lee y opera", "HTTPS")
  Rel(scripts, exchanges, "Lee", "HTTPS")
  Rel(vivo, tg, "Reporta", "HTTPS")
```

## 3. Componentes del núcleo

```mermaid
C4Component
  title Componentes · núcleo treasuryforge (ciclo propone → dispone → ejecuta)
  Container_Boundary(n, "treasuryforge") {
    Component(agente, "Agente / estrategias", "agent.py, signals/*", "Sólo PROPONE un Intent; puede equivocarse o ser manipulado")
    Component(politica, "PolicyEngine", "policy.py", "8 reglas duras en orden; configuración congelada; no confía en el agente")
    Component(ejecutor, "Ejecutores", "executor.py, exchanges/bitso, exchanges/hyperliquid", "Sim / Bitso / Hyperliquid; sólo reciben intents aprobados")
    Component(billetera, "SimWallet", "wallet.py", "Nunca negativa, nunca crea valor")
    Component(runner, "Runner", "runner.py", "Ciclo de simulación: decide en t, llena en t+1, todo al ledger")
    Component(supervisor, "LiveSupervisor + Service", "live.py, service.py, run_live.py", "Ciclo en vivo fail-closed: preflight, reconciliación al arrancar, salida SAFE_HALTED / DEAD_MAN")
    Component(ordenes, "IdempotentOrderManager", "orders.py", "Máquina de estados por origin_id: a lo más una orden por intención; reconcilia antes de reintentar")
    Component(guardas, "Guardas de ejecución", "watchdog.py, preflight.py, staleness.py", "Dead-man's switch con cierre, preflight de arranque, datos frescos y reloj sano")
    Component(capital, "Protocolo de capital", "maturity.py, promotion_gate.py, loss_limits.py, deployment_gate.py", "Niveles de capital, compuerta de promoción, frenos por pérdida, DSR mínimo")
    Component(riesgo, "Riesgo", "risk/ruin.py, risk/stages.py, risk/live_gap.py, risk/drift.py, risk/graveyard.py", "Riesgo de ruina, escalera de etapas, brecha backtest-vivo, deriva")
    Component(backtest, "Backtest honesto", "backtest/*", "Modelo de costos compartido, Sharpe deflactado, CV purgada")
    Component(journal, "Journal", "journal.py", "WAL + checkpoint atómico")
    Component(audit, "AuditLog", "audit.py", "Cadena HMAC verificable")
  }
  Rel(agente, politica, "Intent")
  Rel(politica, ejecutor, "Sólo si ALLOW")
  Rel(ejecutor, billetera, "Fill")
  Rel(runner, agente, "decide")
  Rel(runner, politica, "evaluate / register_fill")
  Rel(supervisor, guardas, "late, verifica")
  Rel(supervisor, ordenes, "submit / recover")
  Rel(ordenes, ejecutor, "place_order / reconcile")
  Rel(politica, journal, "snapshot / restore")
  Rel(ordenes, journal, "cada transición")
  Rel(runner, audit, "cada decisión")
  Rel(capital, riesgo, "usa")
  Rel(capital, backtest, "usa")
```

## 4. Componentes de la API de la demo

```mermaid
C4Component
  title Componentes · API de la demo (api/main.py)
  Container_Boundary(a, "API de la demo") {
    Component(salud, "GET /api/health · GET /", "FastAPI", "Salud y lista de rutas")
    Component(stats, "GET /api/stats", "FastAPI", "Conteos calculados al importar + las 8 reglas")
    Component(evaluar, "POST /api/policy/evaluate", "FastAPI + pydantic", "Un Intent contra el PolicyEngine real; 422 si la entrada es inválida, 400 si la configuración lo es")
    Component(bt, "POST /api/backtest/run", "FastAPI", "Runner real 10-300 ticks, escenario normal o caída; verifica la cadena HMAC")
    Component(aud, "GET /api/audit/sample", "FastAPI", "Cadena HMAC nueva de 1-20 entradas, verificada")
  }
  Container(nucleo, "Núcleo treasuryforge", "Python")
  Rel(evaluar, nucleo, "PolicyEngine.evaluate")
  Rel(bt, nucleo, "Runner.run + verify_chain")
  Rel(aud, nucleo, "AuditLog + verify_chain")
```

## 5. Despliegue

Demo en Vercel, API en Render (Docker) y servicios en vivo en un VPS con systemd: el detalle, la reversa y el
diagnóstico están en [`RUNBOOK.md`](../../RUNBOOK.md).
