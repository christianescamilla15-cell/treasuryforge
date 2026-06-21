# treasuryforge — Roadmap "Carry Engine"

**Reframe rector:** dejar de pensarlo como *trading bot* y construirlo como **motor de
carry + plataforma de validación/control de riesgo**. El cuello de botella NO es el riel
de ejecución (probado, $0.02 round-trip) — es el **edge neto validado en vivo**.

**Regla del roadmap:** cada feature es una *hipótesis con gate de falsación*. Se construye
para **probarla y descartarla**, no para creerle. Nada gana capital real sin pasar el gate.

**Estado (2026-06-17):** decidido arrancar por **Track A completo (medición)**; **Track F (B2B)
parqueado** hasta tener edge demostrable. En curso: A1.

---

# ROADMAP v2 (2026-06-18) — "Cross-venue carry engine"

**Reframe confirmado:** el sistema es un **motor de carry cross-venue de BAJA FRECUENCIA**
(holds horas-semanas), monolito modular hexagonal — **NO un bot HFT**. Sub-125ms es irrelevante
(el funding se paga por hora) y perseguirlo = el callejón retail-HFT que ya matamos. El cuello de
botella es el **EDGE**, no la velocidad. Métrica reina nueva: **`net_apr_on_total_locked_capital`**
(NO el gross spread). Cada punto pasa por validación; la validación misma se endurece.

**Single-venue carry queda DEGRADADO a research** (sin edge desplegable, confirmado con datos).
**Basis = oportunista** (duerme hasta contango). **Cross-venue = foco principal.**

## Fase 1 — SOLO MEDICIÓN (≈7 días, cero capital)
| # | Punto | Build | GATE de validación |
|---|-------|-------|--------------------|
| P1 | Economía cross-venue real | `cross_venue_economics.py`: `net_apr_on_total_locked_capital` = spread − fees − slippage(2 venues) − hedge-rebalance − idle-collateral-drag − liq-buffer − transfer-friction − orphan-leg-premium | el net APR sobre capital TOTAL (2×) debe ser >0 tras todos los costos |
| P6 | Opportunity duty cycle | `% del mes con spread NETO positivo` (7d/30d) | duty_cycle alto + net>0; "30% APR 4h/mes" = inútil |
| P4 | Shadow alta-frecuencia | medición cross-venue **cada 5-15 min** (sin llaves, sin órdenes) | capturar velocidad de colapso + horas activas |
| P2 | Dataset de supervivencia del spread | features + target `area_under_spread_next_24h_after_costs>0` | dataset listo para el modelo |

## Fase 2 — MODELO DE PERSISTENCIA + ECONOMÍA DUAL (2-4 semanas)
| # | Punto | Build | GATE |
|---|-------|-------|------|
| P3 | Modelo de supervivencia simple | logistic / isotonic / hazard (NO deep learning, NO LLM para señales) | debe superar baseline OOS (purged walk-forward) |
| P2b | Gate de entrada por persistencia | ENTER solo si: spread>break-even·margen ∧ percentil_30d>p90 ∧ age≥min ∧ P(survive_24h)≥θ ∧ area_under_spread>costos+buffer ∧ ambos líquidos ∧ liq_distance>floor | reemplaza el gate de spread absoluto |
| P5 | Simulador de riesgo 2-exchanges | `cross_venue_legger.py`: orphan-leg, partial-fill, venue-timeout, stale, price-drift-entre-legs, margin-call-un-lado, funding-un-lado | el edge debe sobrevivir los fallos simulados |
| P9 | Gate de min-hold económico | hard: `cost/gross < 25-40%`; `cost/gross>100%` = cadáver, ni candidato | mata el fee-bleed por churn |
| P10 | Allocator por independencia | `carry_portfolio_allocator.py`: caps por coin/venue/strategy/cluster-de-correlación; `marginal_risk_contribution` | varios spreads del mismo venue-outlier = UNA apuesta, no N |

## Fase 3 — MICROCAPITAL CONDICIONADO (solo si pasa todo)
- Escalera más conservadora que el MICRO actual: **MICRO_0 = 0.25-0.5%** → MICRO_1 1% → SMALL 3% → NORMAL 8%.
- **Condiciones mínimas (TODAS):** 30+ días de forward-shadow · net APR positivo sobre capital total ·
  orphan-leg simulator aprobado · venue-outage tests aprobados · liquidation stress aprobado ·
  DSR live ≥0.60 · cost/gross sano.

**Tareas de fondo:** (a) terminar el grind de mutación de los 6 componentes de analítica restantes a ≥85%
(money-path ya ≥85%); (b) P7/P8 degradar single-venue carry a research + basis a screener oportunista.

**Descartado explícitamente (no invertir más sin evidencia NUEVA):**
- **MR_SCALP** — enterrado (COSTS_EAT_EDGE + muestra chica). 
- **Pairs stat-arb** — Sharpe alto era artefacto de selección; regime-gating confirmó DSR ≤0.21.
- **Cross-venue carry** — diferido hasta que el carry single-venue pase gates (mete riesgo de
  exchange, colateral, latencia, liquidación cruzada).

---

## TRACK A — Infraestructura de medición (PRIMERO: hace honesto todo lo demás)

Sin esto, todo backtest/shadow sobre-estima edge. Es lo más barato y de mayor ROI.

### A1 · `pnl_decomposition.py`
- **Hipótesis:** podemos separar el PnL del shadow en sus fuentes reales.
- **Build:** descomponer cada intervalo en `funding_cobrado / convergencia_premium / fees /
  slippage_modelado / drift_del_hedge / costo_salida`. Wire al status board.
- **Test:** las partes deben reconciliar al total dentro de ε; aplicar a los 10 ledgers actuales.
- **GATE:** si tras descomponer el net real viene de fees/drift y no de funding/convergencia →
  la estrategia no tiene edge, se castiga. (Saber *de dónde* viene el PnL.)

### A2 · Fill-model realista (`fills` extendido)
- **Hipótesis:** una orden maker solo se llena si el precio cruza tu nivel antes de moverse en contra.
- **Build:** `maker_fill_probability` simple primero (¿el low/high de la barra cruzó mi nivel?),
  + `cost_to_gross_edge`, + `adverse_selection_score`. Sin queue-position aún.
- **Test:** re-correr backtests con el fill-model; comparar vs fills perfectos.
- **GATE:** matar cualquier señal donde `fees + slippage > 25-35%` del edge bruto, o que solo
  sea rentable con fill perfecto.

### A3 · `carry_screener.py`
- **Hipótesis:** podemos rankear oportunidades por **edge neto esperado**, no APR bruto.
- **Build:** `score = E[funding_next_N] + E[convergencia_premium] − entry_fee − exit_fee −
  slippage − adverse_selection − liquidation_buffer`. Veredictos:
  `NO_TRADE / WATCH / PAPER / MICRO_ELIGIBLE / LIVE_ELIGIBLE`.
- **Test:** correr sobre el universo; el ranking debe ser estable día a día (no rotar al azar).
- **GATE:** el DSR del screener debe usar `n_trials = tamaño_del_universo` (honestidad de
  selection-bias). Si el "mejor" coin rota cada día, el ranking es ruido → no opera nada.

---

## TRACK B — Shadow de mayor resolución + universo

### B1 · Expandir universo (5 → universo líquido permitido, gradual)
- **Build:** parametrizar los runners para el set líquido (empezar 5 → 15 → todos).
- **GATE (anti-selection-bias):** rankear por edge NETO, no APR bruto; el DSR penaliza el
  universo. Más coins = más "ganadores" espurios — el gate lo absorbe o no expandimos.

### B2 · Snapshots finos (1-5 min) para FEATURES, no para PnL
- **Build:** un segundo timer (5 min) que guarda `premium/oracle/mark/funding/OI/vol` para el
  predictor; el cobro de funding del shadow **sigue siendo horario**.
- **GATE:** no conflar resolución de features con cadencia de pago (el funding se paga por hora).

### B3 · Decomposición wired al board
- Integrar A1 en `shadow_status.py`: el board muestra funding/convergencia/fees/drift por coin.

---

## TRACK C — Predicción de funding/basis (alto valor, ALTO riesgo de overfitting)

> El ítem más valioso y el más peligroso. Disciplina o no se hace.

### C1 · Pipeline de features
- **Build:** `funding_current, premium_zscore, premium_slope_5m/15m/1h, OI_change, vol_change,
  mark_oracle_spread, realized_vol, funding_regime_duration, time_to_next_funding`.

### C2 · Predictor — baseline simple PRIMERO
- **Hipótesis:** el funding de los próximos 3-8 pagos es predecible mejor que "el actual persiste".
- **Build:** baseline = persistencia del funding / z-score del premium. SOLO si supera el baseline
  OOS, considerar algo más complejo.
- **Test:** purged/embargoed CV; comparar contra el baseline naive.
- **GATE:** si NO supera "el funding actual persiste" en OOS → descartado. **Cero ML complejo
  hasta que lo simple gane.** DSR ≥ 0.60 sobre la señal predictiva.

### C3 · `premium_regime.py`
- Clasificación de régimen (contango/backwardation/persistencia) para gatear el basis engine.

---

## TRACK D — Sizing por cartera (no por estrategia aislada)

### D1 · `portfolio.py` — allocator
- **Hipótesis:** señales bajo el mismo régimen ("bull + perps caros") son UNA apuesta, no N.
- **Build:** `max_total_carry_exposure, max_per_asset, max_per_regime, correlation_adjusted_kelly,
  drawdown_budget_per_strategy, drawdown_budget_global`.
- **GATE:** exposición agregada correlacionada tratada como una sola apuesta; si la correlación
  entre señales > umbral, se suman como una.

### D2 · Leverage = output del modelo, nunca input
- **Build:** `leverage = min(hard_cap, DSR_adjusted_fractional_kelly, liquidation_distance_cap,
  stressed_ruin_cap, live_gap_cap)`.
- **GATE:** `leverage = 0` mientras ninguna estrategia pase gates. Nunca "quiero 2x".

---

## TRACK E — Micro-live condicionado (solo después de gates)

### E1 · Criterio de promoción a MICRO
- **GATE (TODOS):** `DSR ≥ 0.60` ∧ `expectancy_neta > 0` ∧ `live_gap estable` ∧
  `slippage_real ≤ slippage_modelado` ∧ `maxDD en banda` ∧ `funding_retention aceptable` ∧
  `≥ 30 días de shadow`.
- **Objetivo:** capital simbólico; la meta NO es ganar — es **validar que el live se parece al
  shadow** (cerrar el live-gap), reusando el riel ya probado.

---

## TRACK F — Productización B2B (paralelo; posiblemente la vía de mayor EV)

> Honestidad: como bot retail el retorno es modesto (~3-4% APR carry; 15-20% mensual = fraude).
> Como **producto**, la ventaja real no es alpha — es **seguridad + honestidad + auditabilidad**.

- **Opciones:** dashboard SaaS de treasury/risk · bot local licenciado · servicio de monitoreo
  funding/basis · **auditoría de estrategias** ("te digo si tu bot es basura antes de meter
  dinero") · infra white-label para fondos chicos/prop traders.
- **GATE (validar demanda ANTES de construir):** hablar con 3-5 usuarios potenciales o una landing
  con lista de espera. Si nadie lo quiere, no se construye. Decisión de NEGOCIO, no técnica.

---

## Secuencia recomendada (por ROI, no por orden de la lista)

| Fase | Foco | Entregables | Por qué primero |
|------|------|-------------|-----------------|
| **1** | Medición (Track A) | A1 pnl_decomp · A2 fill-model · A3 screener | Hace honesto TODO lo demás; lo más barato |
| **2** | Shadow+universo (B) | B1 universo · B2 snapshots · B3 board | Más evidencia/hora a costo cero |
| **3** | Predicción (C) | C1 features · C2 baseline · C3 regime | El edge real vive aquí — con gates estrictos |
| **4** | Cartera (D) | D1 allocator · D2 leverage-output | Antes de cualquier capital real |
| **5** | Micro-live (E) | E1 promoción condicionada | Solo si 1-4 pasan; valida live≈shadow |
| **F** | B2B (paralelo) | validación de demanda | Vía de monetización; decisión de negocio |

**Veredicto:** el sistema no necesita más agresividad — necesita **más edge neto medido**. La
mejora más rentable probablemente no es que el bot opere más, sino convertir treasuryforge en un
motor profesional de validación/control, con el trading real como capa pequeña, conservadora, y
activa solo cuando el edge sobreviva en vivo.

---

## Bitácora de validación — Momentum V1 (2026-06-19)

**Hipótesis:** `MOMENTUM_IGNITION_V1` — pump direccional (ignición X%/1m + confirmación) →
long → salida por trailing/stop. Una pata, hold de horas; el costo no lo mata (a diferencia
del spike cross-venue, que es −90× por el round-trip de 4 patas).

**Gate profundo:** 3.84M barras 1-min reales (29 monedas × 3 meses, data.binance.vision),
sweep de 48 configs, con DSR + estabilidad sub-período + desglose por moneda.

**Resultado:** top-line seductor (+95%, PF 1.88) DEMOLIDO por robustez:
- **DSR = 0.507** (gate >0.95) → sesgo de selección, no edge.
- Estabilidad: mar +1.56% · abr +2.87% · **may −1.34%** (se voltea a pérdida).
- Por moneda: **ORDI +104% (19/64 trades)**, el resto ~0 → una sola moneda.

**Veredicto: RECHAZADO.** El gate funcionó — protegió de un curve-fit que perdía en mayo.

**No enterrado → V2:** la señal vive en alta-vol (moneda/régimen). Hipótesis V2 = momentum
**vol-condicionado/TSMOM** (Sharpe ~0.65 en literatura), mismo rigor. Si V2 no sobrevive el
DSR, se entierra con evidencia. Módulos: `signals/momentum.py`, `momentum_backtest.py`,
`scripts/momentum_validate.py` (11 tests).

## Bitácora de validación — Momentum V2 / TSMOM (2026-06-19)

**Hipótesis V2:** `TSMOM_VOLSCALED_V2` — dirección = signo del retorno trailing (lookback),
tamaño = target_vol / vol_realizada (posición continua, barras horarias). La forma con
respaldo en literatura (Moskowitz-Ooi-Pedersen, ~0.65 Sharpe).

**Gate:** 30 monedas × 3 meses → horario, sweep de 48 configs, DSR + estabilidad sub-período.

**Resultado: RECHAZADO, más decisivo que V1.**
- **DSR = 0.083** (gate >0.95) vs V1 0.507.
- Mejor config: Sharpe_ann 0.28, **totNet −3%** (pierde).
- Long/short peor (−24% a −29%); shortear la tendencia cripto castiga.
- Sub-período: mar −0.27 · abr +0.58 · may +2.34 (mejora pero el agregado pierde).

**Veredicto final momentum:** ni V1 (cruda) ni V2 (vol-escalada) cruzan el DSR. El ~0.65
Sharpe de TSMOM es multi-año/multi-activo; 3 meses de perps cripto no lo reproducen. **No
merece capital.** Revisitar solo con años de historia (BTC/ETH) a horizonte diario.
Módulos: `signals/momentum.py`, `signals/tsmom.py`, backtests + validators, 19 tests.
