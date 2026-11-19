# ADR 0003 · Estado con cierre a prueba de caídas y auditoría encadenada

- Estado: aceptada (Fase 2; se registra el 2026-11-19) · Código: `treasuryforge/journal.py`, `audit.py`, `orders.py`

## Contexto
La investigación de la Fase 2 encontró un bug con dinero de por medio: el interruptor y el ancla del drawdown
vivían en memoria, así que un reinicio después de una caída **des-disparaba** el freno y re-anclaba el piso a la
equidad ya perdida. Además, un *timeout* al enviar una orden puede esconder una orden que sí llegó.

## Decisión
- El estado con cierre (`PolicyEngine.snapshot/restore`, órdenes, *watchdog*) se persiste con un WAL de una línea
  JSON por evento (tolera una última línea rota) más un checkpoint atómico con `os.replace`.
- Cada orden lógica tiene un `origin_id` estable; ante resultado incierto se **reconcilia antes de reintentar** y
  el reintento reutiliza el mismo id. `FILLED` y `REJECTED` son terminales; al arrancar sólo se reconcilia, nunca
  se coloca una orden nueva.
- Cada decisión queda en una bitácora JSONL encadenada con HMAC-SHA256 (`prev_hash` + JSON canónico); editar,
  insertar, borrar o reordenar rompe `verify_chain`.

## Alternativas
- Base de datos: más dependencias y otro proceso que se puede caer; el volumen no lo pide.
- Firma asimétrica en la bitácora: daría no repudio, pero el alcance honesto es *evidencia de manipulación*.

## Consecuencias
- Una prueba mata el proceso con `os._exit(1)` y comprueba que el freno sigue disparado al reiniciar.
- La misma llave firma y verifica: la llave y la bitácora deben vivir fuera del alcance de escritura del agente.
