# Reglas de negocio → pruebas · treasuryforge

Ésta es la compuerta real del proyecto (más que el % de cobertura): cada regla del dominio tiene al menos una
prueba que falla si la regla se rompe. Formato `archivo::prueba`. Las pruebas parametrizadas cuentan una vez por
caso. Las marcadas **(nueva)** se agregaron en la revisión del 2026-11-19.

Además de estas pruebas, la puerta de mutación (`scripts/mutation.sh`, ≥ 85 % por componente, 42 componentes)
comprueba que las pruebas de cada módulo matan las mutaciones de su código.

## 1. Motor de políticas (`treasuryforge/policy.py`) — las 8 reglas duras

| # | Regla | Pruebas |
|---|---|---|
| — | Las 8 reglas se evalúan en el orden documentado; la primera violada nombra la negación | `tests/core/test_reglas_precedencia.py::test_the_8_rules_fire_in_their_documented_order` **(nueva)** · `tests/core/test_reglas_precedencia.py::test_each_rule_alone_denies_with_its_own_name` (8 casos) **(nueva)** |
| — | Toda negación empieza con `DENY:<regla>`; lo permitido es exactamente `ALLOW` | `tests/core/test_policy_mutation.py::test_every_denial_reason_starts_with_DENY_and_names_the_rule` · `tests/core/test_policy_mutation.py::test_allow_reason_is_exactly_ALLOW` |
| 1 | Interruptor de paro: niega todo | `tests/core/test_policy.py::test_kill_switch_denies_everything` |
| 2 | Freno por drawdown: se dispara bajo el piso y **se queda disparado** (transición inválida: disparado → libre) | `tests/core/test_policy.py::test_circuit_breaker_trips_and_stays_tripped` · `tests/core/test_policy_mutation.py::test_breaker_at_exactly_the_floor_does_not_trip` · `tests/core/test_policy_stateful.py::TestPolicyMachine` (invariante `breaker_is_latched`) · `tests/core/test_end_to_end.py::test_crash_trips_breaker_and_halts_trading` |
| 3 | Datos viejos: niega si la edad supera el presupuesto; inerte sin presupuesto o sin edad | `tests/core/test_policy_phase2.py::test_staleness_denies_old_data` · `tests/core/test_policy_phase2.py::test_staleness_allows_fresh_data` · `tests/core/test_policy_phase2.py::test_staleness_inert_without_age_or_budget` · `tests/core/test_policy_mutation.py::test_staleness_exactly_at_budget_is_allowed` |
| 4 | Lista de símbolos permitidos | `tests/core/test_policy.py::test_symbol_allowlist` |
| 5 | Tope por operación (y piso mínimo del exchange) | `tests/core/test_policy.py::test_per_tx_notional_cap` · `tests/core/test_policy_mutation.py::test_notional_exactly_at_cap_is_allowed` · `tests/core/test_policy_phase2.py::test_min_notional_floor_rejects_dust` · `tests/core/test_policy_phase2.py::test_min_notional_floor_allows_at_or_above` · `tests/core/test_policy_mutation.py::test_min_notional_epsilon_boundary_is_exact` |
| 6 | Límite de tasa por ventana móvil, que se recupera al pasar la ventana | `tests/core/test_policy.py::test_rate_limit_blocks_after_n_in_window` · `tests/core/test_policy.py::test_rate_limit_recovers_after_window_passes` · `tests/core/test_policy_mutation.py::test_prune_evicts_a_fill_exactly_at_the_window_cutoff` |
| 7 | Presupuesto de gasto por ventana (cierra el drenaje por goteo) | `tests/core/test_policy_phase2.py::test_spend_budget_blocks_drip_drain` · `tests/core/test_policy_phase2.py::test_spend_budget_recovers_after_window` · `tests/core/test_policy_mutation.py::test_spend_budget_epsilon_boundary_is_exact` |
| 8 | Solvencia: la compra paga comisión; la venta no excede lo que se tiene | `tests/core/test_policy.py::test_solvency_buy_needs_quote` · `tests/core/test_policy.py::test_solvency_sell_needs_base` · `tests/core/test_policy_mutation.py::test_solvency_buy_cost_includes_fee_multiplicatively` · `tests/core/test_policy_mutation.py::test_solvency_sell_exactly_at_holdings_is_allowed` |
| — | La configuración es inmutable (el agente no cambia sus límites) | `tests/core/test_policy_phase2.py::test_config_is_immutable` |
| — | Sólo lo ejecutado consume tasa y presupuesto; lo negado no | `tests/core/test_policy_phase2.py::test_spend_budget_only_debits_on_fills_not_denials` · `tests/core/test_reglas_precedencia.py::test_denied_intents_never_consume_the_rate_limit` **(nueva)** |
| — | Lo permitido nunca rompe tope, freno ni solvencia sobre historias arbitrarias | `tests/core/test_policy_stateful.py::TestPolicyMachine` (Hypothesis, 200 historias × 40 pasos) |

## 2. Estado a prueba de caídas y auditoría (`journal.py`, `audit.py`)

| Regla | Pruebas |
|---|---|
| El freno disparado sobrevive a un `kill -9` real del proceso | `tests/core/test_crash_safety.py::test_breaker_survives_a_hard_process_crash` |
| `snapshot/restore` conserva el freno y el ancla del drawdown | `tests/core/test_policy_phase2.py::test_snapshot_restore_preserves_tripped_breaker` · `tests/core/test_policy_phase2.py::test_snapshot_restore_preserves_drawdown_anchor` · `tests/core/test_policy_mutation.py::test_restore_repopulates_the_spend_window` |
| El checkpoint es atómico y el WAL tolera una última línea rota | `tests/core/test_crash_safety.py::test_checkpoint_is_atomic_valid_json` · `tests/core/test_crash_safety.py::test_ledger_tolerates_a_torn_final_line` |
| La cadena HMAC verifica intacta y detecta edición o borrado | `tests/core/test_crash_safety.py::test_audit_chain_verifies_when_intact` · `tests/core/test_crash_safety.py::test_audit_chain_detects_tampering` · `tests/core/test_crash_safety.py::test_audit_chain_detects_deletion` |

## 3. Órdenes idempotentes (`orders.py`) — máquina de estados

`PLACING → SUBMITTED → FILLED` · `PLACING → REJECTED` · `PLACING → UNKNOWN → FILLED | OPEN` · `FILLED` y `REJECTED` terminales.

| Regla / transición | Pruebas |
|---|---|
| Camino feliz: una sola colocación y llenado | `tests/core/test_orders_idempotency.py::test_happy_path_places_once_and_fills` |
| **Inválida** `FILLED → otra colocación`: reenviar reproduce el resultado | `tests/core/test_orders_idempotency.py::test_resubmit_replays_fill_without_a_second_place` |
| `UNKNOWN` (timeout) se **reconcilia antes de reintentar**; si llegó, no se duplica | `tests/core/test_orders_idempotency.py::test_indeterminate_then_reconcile_finds_the_fill` |
| Reintento seguro con el **mismo** `origin_id`, acotado a `max_attempts` | `tests/core/test_orders_idempotency.py::test_indeterminate_not_landed_retries_same_origin_id` · `tests/core/test_orders_idempotency.py::test_attempts_counts_and_max_attempts_default_is_three` |
| **Inválida** `REJECTED → reintento`, ni por reenvío ni por reinicio | `tests/core/test_orders_idempotency.py::test_non_retryable_is_rejected_and_not_retried` · `tests/core/test_orders_idempotency.py::test_fatal_auth_is_rejected` · `tests/core/test_reglas_precedencia.py::test_rejected_is_terminal_across_resubmit_and_restart` **(nueva)** |
| **Inválida** `OPEN → nueva colocación` (una orden en libro nunca se re-publica) | `tests/core/test_orders_idempotency.py::test_submitted_but_unfilled_is_open_and_not_reposted` |
| Al reiniciar sólo se reconcilia, nunca se coloca; se saltan las terminales | `tests/core/test_orders_idempotency.py::test_recover_reconciles_inflight_order_after_restart` · `tests/core/test_orders_idempotency.py::test_recover_skips_terminal_orders` · `tests/core/test_orders_idempotency.py::test_recover_processes_nonterminal_after_a_terminal` · `tests/core/test_orders_idempotency.py::test_recover_marks_resting_order_open_only_when_it_has_an_oid` |
| Cada transición queda en el journal | `tests/core/test_orders_idempotency.py::test_journal_records_each_transition_with_kind_and_event` |

## 4. Guardas de ejecución en vivo (`watchdog.py`, `preflight.py`, `staleness.py`, `service.py`, `live.py`)

| Regla | Pruebas |
|---|---|
| *Dead-man's switch*: dispara una vez al expirar, **queda con cierre** y rechaza latidos después (transición inválida: disparado → latiendo) | `tests/core/test_watchdog.py::test_supervise_trips_once_when_expired` · `tests/core/test_watchdog.py::test_beat_is_refused_after_trip` · `tests/core/test_watchdog.py::test_crash_mid_trip_refires` · `tests/core/test_watchdog.py::test_reset_clears_the_latch` |
| Preflight de arranque: cualquier verificación en rojo detiene (modo implícito, sin credenciales, topes en cero, reloj, datos viejos) | `tests/core/test_preflight.py::test_implicit_mode_halts` · `tests/core/test_preflight.py::test_missing_credentials_halts` · `tests/core/test_preflight.py::test_zero_caps_halts` · `tests/core/test_preflight.py::test_live_requires_spend_cap` · `tests/core/test_preflight.py::test_kill_switch_latched_halts` · `tests/core/test_preflight.py::test_stale_data_halts` · `tests/core/test_preflight.py::test_clock_skew_halts_live` |
| Datos frescos y reloj sano en cada paso (futuro, reloj hacia atrás, deriva) | `tests/core/test_staleness.py::test_stale_data_boundary_is_inclusive` · `tests/core/test_staleness.py::test_future_data_halts` · `tests/core/test_staleness.py::test_wall_clock_backward_halts` · `tests/core/test_staleness.py::test_clock_drift_halts` |
| El servicio es *fail-closed*: preflight en rojo nunca opera; reconcilia antes del ciclo; error inesperado detiene | `tests/core/test_service.py::test_safe_halted_on_bad_preflight_never_trades` · `tests/core/test_service.py::test_recovers_inflight_order_before_the_loop` · `tests/core/test_service.py::test_fails_closed_on_unexpected_exception` · `tests/core/test_run_live.py::test_main_safe_halts_without_explicit_mode` |
| En vivo, datos viejos o una negación de la política no colocan nada | `tests/core/test_live.py::test_stale_data_halts_and_places_nothing` · `tests/core/test_live.py::test_policy_denial_blocks_order` |
| Preflight de armado: autorización del agente (sin distinguir mayúsculas), colateral, relevo fresco, freno, nivel micro; sin las dependencias de firma **no arma** | `tests/core/test_preflight_arm.py::test_arm_preflight_success` · `tests/core/test_preflight_arm.py::test_arm_preflight_auth_is_case_insensitive` · `tests/core/test_preflight_arm.py::test_arm_preflight_unauthorized_agent` · `tests/core/test_preflight_arm.py::test_arm_preflight_low_collateral` · `tests/core/test_preflight_arm.py::test_arm_preflight_stale_relay` · `tests/core/test_preflight_arm.py::test_arm_preflight_tripped_breaker` · `tests/core/test_preflight_arm.py::test_arm_preflight_fails_closed_without_signing_deps` **(nueva)** |

## 5. Billetera y ciclo de simulación (`wallet.py`, `runner.py`)

| Regla | Pruebas |
|---|---|
| La billetera nunca queda negativa | `tests/core/test_wallet_executor.py::test_wallet_refuses_to_go_negative` · `tests/core/test_end_to_end.py::test_balances_never_go_negative_over_a_full_run` · `tests/core/test_policy_stateful.py::TestPolicyMachine` (invariante `balances_never_negative`) |
| Conservación: el sistema sólo pierde fricción, nunca crea valor | `tests/core/test_end_to_end.py::test_no_value_created_conservation` · `tests/core/test_wallet_executor.py::test_round_trip_only_loses_fees_and_slippage` |
| Determinismo: misma semilla, mismo resultado bit a bit | `tests/core/test_end_to_end.py::test_run_is_deterministic` |

## 6. Protocolo de capital (`maturity.py`, `promotion_gate.py`, `loss_limits.py`, `deployment_gate.py`)

| Regla | Pruebas |
|---|---|
| Niveles de capital en rampa; avanzar exige tiempo **y** volumen; el nivel tope no avanza; sólo se avanza al siguiente | `tests/core/test_capital_protocol.py::test_tier_caps_ramp` · `tests/core/test_capital_protocol.py::test_advance_needs_time_AND_volume` · `tests/core/test_capital_protocol.py::test_advance_boundary_inclusive` |
| Promoción sólo si pasan todas las compuertas; cualquiera veta; vivo peor que la sombra veta | `tests/core/test_capital_protocol.py::test_promotion_passes_only_when_all_gates_pass` · `tests/core/test_capital_protocol.py::test_each_gate_can_veto` · `tests/core/test_capital_protocol.py::test_live_worse_than_shadow_vetoes` · `tests/core/test_capital_protocol.py::test_empty_decision_not_promoted` |
| Frenos por pérdida diaria, semanal, mensual, errores y brecha con la sombra | `tests/core/test_capital_protocol.py::test_each_breaker_trips` · `tests/core/test_capital_protocol.py::test_breaker_boundaries_inclusive` · `tests/core/test_capital_protocol.py::test_breakers_clear_when_healthy` |
| Despliegue sólo con DSR, APR y días suficientes; bloqueada, la estrategia ni consulta su señal | `tests/core/test_deployment_gate.py::test_dsr_gate_isolated` · `tests/core/test_deployment_gate.py::test_apr_gate_isolated` · `tests/core/test_deployment_gate.py::test_days_gate_isolated` · `tests/core/test_deployment_gate.py::test_gated_strategy_stays_hold_and_never_consults_signal_when_blocked` |

## 7. Riesgo (`risk/*`)

| Regla | Pruebas |
|---|---|
| Escalera de etapas: KILL > DEMOTE > PROMOTE > HOLD | `tests/risk/test_stages.py::test_kill_beats_everything_else` · `tests/risk/test_stages.py::test_demote_on_edge_retention` · `tests/risk/test_stages.py::test_promote_when_all_criteria_met` · `tests/risk/test_stages.py::test_hold_on_mixed_metrics` |
| **Transiciones inválidas** de la escalera: no salta peldaños, sólo KILL llega a DEAD, DEAD es absorbente, no hay promoción más allá del tope ni degradación bajo PAPER_LIVE, el capital sigue al peldaño | `tests/core/test_reglas_precedencia.py::test_stage_ladder_never_makes_an_invalid_transition` (6 etapas × 5 perfiles) **(nueva)** · `tests/risk/test_stages.py::test_dead_stays_dead` · `tests/risk/test_stages.py::test_cannot_promote_past_capped` · `tests/risk/test_stages.py::test_demote_floor_is_paper_live` |
| Brecha backtest → vivo: datos insuficientes, sin ventaja, ventaja extinta, brecha grande o fuga por deslizamiento rechazan | `tests/risk/test_live_gap.py::test_insufficient_live_data` · `tests/risk/test_live_gap.py::test_no_backtest_edge` · `tests/risk/test_live_gap.py::test_edge_decayed_when_live_negative` · `tests/risk/test_live_gap.py::test_backtest_live_gap_when_degraded` · `tests/risk/test_live_gap.py::test_execution_edge_leak_on_slippage` · `tests/risk/test_live_gap.py::test_approve_stage_1_when_survives` |
| Riesgo de ruina: compuertas estrictas (ventaja, crecimiento, Kelly, ruina, drawdown esperado) | `tests/risk/test_risk_of_ruin.py::test_policy_rejects_full_kelly_on_ruin` · `tests/risk/test_risk_of_ruin.py::test_policy_rejects_negative_edge` · `tests/risk/test_ruin_mutation.py::test_edge_gate_is_strict` · `tests/risk/test_ruin_mutation.py::test_expected_drawdown_gate_is_strict` · `tests/risk/test_ruin_mutation.py::test_risk_of_ruin_gate_is_strict` |
| Los estadísticos dan lo mismo en Python 3.11 y 3.12 (serie constante ⇒ Sharpe 0) | `tests/backtest/test_sizing_backtest.py::test_sharpe_sign_and_zero` (en la matriz 3.11 + 3.12 del CI) |

## 8. API de la demo (`api/main.py`) — job `api` del CI

| Regla | Pruebas |
|---|---|
| Las negaciones vienen del motor real y nombran la regla | `api/tests/test_api.py::test_evaluate_allows_a_normal_trade` · `api/tests/test_api.py::test_evaluate_denials_name_the_rule` (4 casos) |
| Entrada inválida no llega al motor (422) y una configuración inválida responde 400 | `api/tests/test_api.py::test_evaluate_rejects_invalid_input` · `api/tests/test_api.py::test_evaluate_rejects_a_malformed_config` · `api/tests/test_api.py::test_backtest_rejects_out_of_range_ticks` |
| El escenario de caída dispara el freno y la cadena de auditoría verifica | `api/tests/test_api.py::test_backtest_crash_trips_the_breaker_and_the_audit_chain_verifies` · `api/tests/test_api.py::test_audit_sample_is_a_verified_chain_and_clamps_n` |
