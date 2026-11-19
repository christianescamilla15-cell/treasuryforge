# Runbook · treasuryforge

Hay tres cosas desplegadas y cada una se despliega distinto. Estado verificado el 2026-11-19.

| Qué | Dónde | Cómo se despliega hoy | Humo |
|---|---|---|---|
| Demo estática (`demo/`) | Vercel, proyecto `treasuryforge` → https://treasuryforge.vercel.app | `vercel deploy --prod` desde la raíz (origen «cli»; el proyecto **no** está conectado a Git). Último despliegue a producción: 21-jun-2026 | `herramientas/humo.sh demo https://treasuryforge.vercel.app` → OK el 2026-11-19 |
| API de la demo (`api/`) | Render, servicio Docker con `api/Dockerfile` → https://treasuryforge-api.onrender.com | build de Render desde el repo; la configuración vive en el tablero de Render (no hay `render.yaml`) | `herramientas/humo.sh api https://treasuryforge-api.onrender.com` → **no verificable** desde la red de esta revisión (todo `*.onrender.com` corta el TLS) |
| Agente en vivo | VPS propio con systemd (`deploy/*.service`, `deploy/*.timer`) | copia manual (`scp`) + `deploy/setup_on_vps.sh`; ver `deploy/README.md` | `systemctl status treasuryforge*` y `journalctl -u <unidad>` |

Hay un segundo proyecto de Vercel, `ch-demo-treasuryforge`, con protección SSO de Vercel; no se despliega desde
este repo.

## Desplegar

### Regla general

1. Todo cambio entra por PR a `main` con los checks requeridos en verde (`ci`, `seguridad`). Un check
   «skipped» cuenta como rojo: ningún job del CI se salta en un PR.
2. El CI ya prueba que la imagen de la API **arranca** y responde (job `api`: `docker build` + `humo.sh api`).

### Demo (Vercel)

```bash
vercel deploy                                   # preview: imprime la URL de la vista previa
herramientas/humo.sh demo <url-de-la-preview>   # debe salir con 0
vercel promote <url-de-la-preview>              # pasa la preview a producción
herramientas/humo.sh demo https://treasuryforge.vercel.app
```

### API (Render)

Render construye `api/Dockerfile` (Python 3.11, usuario sin privilegios, versiones exactas de
`api/requirements.txt`). Después de cada despliegue:

```bash
herramientas/humo.sh api https://treasuryforge-api.onrender.com   # el plan gratuito duerme: el humo reintenta 30 veces
```

### Agente en vivo (VPS)

Sigue `deploy/README.md` (copiar, `setup_on_vps.sh` corre la suite y la escalera en papel, secretos en
`/etc/treasuryforge/*.env` con `chmod 600`, unidades de systemd). El servicio principal
(`python -m treasuryforge.run_live`) es *fail-closed*: sin `TF_MODE` explícito o sin preflight en verde sale con
`SAFE_HALTED` y no opera.

## Revertir

> **Ninguna reversa está ensayada todavía.** Esta revisión no despliega nada (regla del programa); el primer
> ensayo queda pendiente y se anotará aquí con su fecha.

| Qué | Reversa |
|---|---|
| Demo | `vercel rollback` (vuelve al despliegue de producción anterior) o `vercel promote <url-anterior>`; luego `herramientas/humo.sh demo https://treasuryforge.vercel.app` |
| API | en Render: *Rollback* al despliegue anterior; luego `herramientas/humo.sh api …` |
| Agente en vivo | detener primero, investigar después: `systemctl stop treasuryforge-scalp treasuryforge` (el estado con cierre —interruptor, ventanas, órdenes en vuelo— queda en `state/` y se reconcilia al arrancar). Para volver a papel: quitar `--arm` y el `EnvironmentFile` de la unidad `treasuryforge-scalp.service`, como indica su comentario |

## Diagnóstico

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| La demo dice «API offline» | la API de Render está dormida (plan gratuito) o caída | esperar ~1 min y recargar; si sigue, `humo.sh api` y revisar el tablero de Render |
| `run_live` sale con `SAFE_HALTED` | preflight en rojo: falta `TF_MODE`/`TF_VENUE`, credenciales, reloj o datos viejos | `journalctl -u treasuryforge` lista las verificaciones fallidas; corregir y reiniciar |
| Sale con `DEAD_MAN` | el ciclo dejó de latir y el *dead-man's switch* disparó (queda con cierre) | no reiniciar en bucle: revisar la causa; el cierre se limpia a mano con `Watchdog.reset()` |
| `preflight_arm` falla en «Agent Key authorization» | la llave del agente no está autorizada para la cuenta maestra, o faltan `eth-account`/SDK en el VPS | autorizar el agente en el exchange o instalar las dependencias en cuarentena (`pip install hyperliquid-python-sdk eth-account`) |
| CI: «mutación (fragmento k/6)» en rojo con `NO-RUN` | mutmut no corrió (su corrida base de pruebas falló) | correr `bash scripts/mutation.sh <componente>` en local y arreglar la prueba |
| CI: un componente < 85 % | una prueba dejó de matar mutantes | `scripts/_show_survivors.sh` muestra los sobrevivientes; reforzar la prueba |
