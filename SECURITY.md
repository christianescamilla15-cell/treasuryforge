# Seguridad

## Reportar una vulnerabilidad

Escribe a **christianescamilla15@gmail.com** con el asunto «Seguridad: treasuryforge». Respondo en 72 horas
hábiles y publico el arreglo con su aviso. Por favor no abras un issue público para vulnerabilidades.

## Qué revisa cada cambio

| Revisión | Herramienta | Dónde | Bloquea |
|---|---|---|---|
| Análisis estático | CodeQL (Python + JS de la demo) + Semgrep `p/default` (imagen 1.186.0 fijada por digest) | `seguridad.yml` | sí (Semgrep) |
| Análisis estático de Python | bandit `-ll` sobre `treasuryforge/` y `api/` | `ci.yml` | sí |
| Dependencias con versión exacta (lo que se despliega: `api/requirements.txt`) | Trivy fs | `seguridad.yml` | sí, en CRITICAL/HIGH con arreglo publicado |
| Dependencias por rango (`requirements-dev.txt`, `requirements-live.txt`) y las de la API | pip-audit, en 3.11 y 3.12 | `ci.yml` | sí |
| Configuración e IaC (`Dockerfile`, `api/Dockerfile`, `docker-compose.yml`) | Trivy config | `seguridad.yml` | sí, en CRITICAL/HIGH |
| Secretos en toda la historia | gitleaks v8.21.2 (imagen fija; el job exige ver «N commits scanned» en la bitácora) | `seguridad.yml` y pre-commit | sí |
| Datos de terceros | `herramientas/confidencialidad.py` | `seguridad.yml` y pre-commit | sí |
| Inventario de componentes | SBOM (syft, SPDX) | `seguridad.yml` | no: se publica con cada versión |

Cada revisión debe probar que analizó algo (archivos o paquetes > 0, `herramientas/verificar_reportes.py`); un
reporte vacío cuenta como fallo. Las acciones de GitHub van fijadas por SHA y Dependabot (con 7 días de espera)
propone las actualizaciones.

## Secretos del sistema en vivo

- Ninguna llave vive en el repositorio. En el VPS, las llaves de los exchanges están en
  `/etc/treasuryforge/*.env` (dueño root, `chmod 600`) y en el llavero del sistema (`keyring`) en la PC; ver
  `deploy/README.md` y `deploy/bitso.env.example`.
- La llave de Bitso es sólo de operación (sin retiro) y con lista de IP permitidas; la escalera de validación
  (`scripts/validate_live.py`) prueba que **no** puede retirar antes de cualquier orden.
- La llave HMAC `demo-api-key-not-for-prod` de `api/main.py` es pública a propósito: sólo firma la cadena de
  auditoría de la demo y nunca protege nada real.

## Excepciones vigentes (con motivo)

| Excepción | Motivo | Revisar |
|---|---|---|
| `# nosemgrep: dynamic-urllib-use-detected` en 48 llamadas de `scripts/` y `treasuryforge/marketlab/store.py` | todas usan una URL base `https://` fija en el código (verificado el 2026-11-19); ya estaban triadas para bandit con `# nosec B310` | si una URL pasa a venir de un argumento o archivo |
| `# nosemgrep: non-literal-import` en `exchanges/hyperliquid/signer.py` | `importlib` sólo recibe literales del propio módulo (dependencias en cuarentena del VPS) | si `_require` recibe datos externos |

Las excepciones de Trivy viven en `.trivyignore`, cada una con fecha de vencimiento y motivo (hoy: ninguna).
