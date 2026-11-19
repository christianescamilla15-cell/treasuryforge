#!/usr/bin/env bash
# Prueba de humo post-despliegue (y de arranque del contenedor en CI). Sale con 0 sólo si responde
# lo que la demo necesita, no sólo un 200.
#
#   herramientas/humo.sh demo https://treasuryforge.vercel.app
#   herramientas/humo.sh api  https://treasuryforge-api.onrender.com
#   herramientas/humo.sh api  http://127.0.0.1:8000          # contenedor local / CI
set -euo pipefail
tipo=${1:?uso: humo.sh demo|api <url>}
url=${2:?falta la url}
url=${url%/}
INTENTOS=${INTENTOS:-30}     # Render duerme el servicio gratuito: el primer arranque tarda

obtener() {  # obtener <ruta> [cuerpo-json] -> imprime el cuerpo; reintenta mientras arranca
  local ruta=$1 cuerpo=${2:-} i
  for ((i = 1; i <= INTENTOS; i++)); do
    if [ -n "$cuerpo" ]; then
      curl -fsS -m 20 -H 'content-type: application/json' -d "$cuerpo" "$url$ruta" && return 0
    else
      curl -fsS -m 20 "$url$ruta" && return 0
    fi
    sleep 2
  done
  echo "humo: $url$ruta no respondió tras $INTENTOS intentos" >&2
  return 1
}

exige() {  # exige <texto> <cuerpo> <qué>
  if ! grep -q -- "$1" <<< "$2"; then
    echo "humo: FALLA · $3 (no aparece «$1»)" >&2
    exit 1
  fi
  echo "humo: ok · $3"
}

case "$tipo" in
  demo)
    html=$(obtener /)
    exige "<title>TreasuryForge" "$html" "la página de la demo carga"
    exige "demo.js" "$html" "la página referencia su script"
    ;;
  api)
    exige '"status":"ok"' "$(obtener /api/health)" "salud de la API"
    exige '"id":"kill_switch"' "$(obtener /api/stats)" "las 8 reglas publicadas"
    exige '"reason":"ALLOW"' \
      "$(obtener /api/policy/evaluate '{"symbol":"TOKEN","side":"BUY","notional":200,"price":100}')" \
      "una operación normal se permite con el motor real"
    exige '"rule":"symbol"' \
      "$(obtener /api/policy/evaluate '{"symbol":"SCAM","side":"BUY","notional":200,"price":100}')" \
      "un símbolo fuera de la lista se niega"
    ;;
  *)
    echo "uso: humo.sh demo|api <url>" >&2
    exit 2
    ;;
esac
echo "humo: $tipo en $url · TODO OK"
