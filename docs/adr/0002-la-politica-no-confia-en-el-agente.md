# ADR 0002 · La política no confía en el agente: 8 reglas duras, en orden, fuera del agente

- Estado: aceptada (decisión de origen del proyecto; se registra el 2026-11-19) · Código: `treasuryforge/policy.py`

## Contexto
El agente (estrategia determinista hoy, un LLM mañana) puede equivocarse, alucinar o ser manipulado por los datos
de mercado. Si el agente también aplica sus propios límites, un error del agente es un error de los límites.

## Decisión
- El agente sólo **propone** un `Intent`; `PolicyEngine.evaluate` lo aprueba o lo niega y sólo un `ALLOW` llega
  al ejecutor. El agente nunca toca la billetera.
- Ocho reglas en orden fijo y la primera que se viola nombra la negación (`DENY:<regla>`): interruptor de paro →
  freno por drawdown (con cierre) → datos viejos → lista de símbolos → tope por operación (y piso mínimo) →
  límite de tasa → presupuesto de gasto por ventana → solvencia.
- `PolicyConfig` es `frozen`: el agente no puede cambiar sus límites. Los contadores se debitan sólo al
  ejecutar (`register_fill`), nunca al evaluar: una intención negada no consume presupuesto.

## Alternativas
- Límites dentro de cada estrategia: se duplican y un bug de la estrategia los anula.
- Sólo límites del exchange: llegan tarde (la orden ya salió) y no cubren datos viejos ni drawdown.

## Consecuencias
- El orden es contrato y está probado de punta a punta (`tests/core/test_reglas_precedencia.py`), además de una
  prueba con estado de Hypothesis sobre historias arbitrarias y la puerta de mutación del componente `policy`.
- El mismo patrón se extrajo como biblioteca genérica en *agentguard*.
