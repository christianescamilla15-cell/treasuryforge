# ADR 0004 · Núcleo sólo con la biblioteca estándar; dependencias de firma en cuarentena

- Estado: aceptada (se registra y amplía el 2026-11-19) · Código: `pyproject.toml`, `exchanges/hyperliquid/signer.py`

## Contexto
El núcleo decide sobre dinero y debe poder auditarse y probarse sin red ni llaves. El SDK del exchange y
`eth-account` sólo hacen falta para firmar en el VPS. En junio de 2026 el CI quedó en rojo por dos motivos que
rompían esta frontera o su reproducibilidad:
1. `scripts/preflight_arm.py` y su prueba importaban `eth_account` al cargar el módulo, así que pytest no podía
   ni recolectar la suite sin una dependencia que no está (ni debe estar) en `requirements`.
2. Los promedios usaban `sum()`, que en Python 3.12 pasó a suma compensada: en 3.11 una serie constante tenía
   varianza 1e-19 y las compuertas estrictas cambiaban de lado según la versión del intérprete.

## Decisión
- El paquete `treasuryforge` no tiene dependencias de ejecución. Las de firma se importan de forma perezosa con
  `signer._require`, que falla en voz alta con la instrucción de instalación; el código que las necesita recibe
  la función de firma o de derivación inyectada, y las pruebas usan valores dorados.
- Los estadísticos que alimentan compuertas (media, varianza, momentos) usan `math.fsum`, correctamente
  redondeado e idéntico en todas las versiones. El CI corre 3.11 y 3.12 sin `fail-fast`.

## Consecuencias
- La suite completa corre sin red, sin llaves y sin dependencias del VPS en ambas versiones.
- Sin el SDK, el preflight de armado reporta «no armar» (falla cerrada) en lugar de romperse.
