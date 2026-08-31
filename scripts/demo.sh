#!/usr/bin/env bash
# Start the full stack. This is the demo-day command.
set -euo pipefail
cd "$(dirname "$0")/.."

API_PORT="${CYCLOPS_API_PORT:-8000}"
CONSOLE_PORT="${CYCLOPS_CONSOLE_PORT:-5180}"

echo "── CYCLOPS ────────────────────────────────────────────"

for f in models/nowcast_gbm.joblib models/cone_radii.json; do
  [ -f "$f" ] || { echo "missing $f — run 'make train' first"; exit 1; }
done
[ -f models/cyclops_intensity.pt ] || \
  echo "note: intensity model missing; classification panel will show an empty state"

pkill -f "uvicorn api.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

# Refuse to start on a port somebody else owns. Without this check a stray dev
# server from another project silently shadows the console and you demo the
# wrong app — which is exactly what happened once, so the check stays.
for p in "$API_PORT" "$CONSOLE_PORT"; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ERROR: port $p is already in use by:"
    lsof -nP -iTCP:"$p" -sTCP:LISTEN | tail -n +2 | sed 's/^/  /'
    echo "Free it, or set CYCLOPS_API_PORT / CYCLOPS_CONSOLE_PORT."
    exit 1
  fi
done

mkdir -p .run
PYTHONPATH=src .venv/bin/uvicorn api.main:app \
  --host 127.0.0.1 --port "$API_PORT" > .run/api.log 2>&1 &
echo "api starting (pid $!)…"

for i in $(seq 1 90); do
  curl -fsS "http://127.0.0.1:$API_PORT/v1/health" >/dev/null 2>&1 && break
  sleep 1
  [ "$i" -eq 90 ] && { echo "api failed to start:"; tail -30 .run/api.log; exit 1; }
done
echo "api ready      →  http://127.0.0.1:$API_PORT/docs"

(cd console && CYCLOPS_CONSOLE_PORT="$CONSOLE_PORT" CYCLOPS_API_PORT="$API_PORT" \
   npm run dev > ../.run/console.log 2>&1 &)
for i in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$CONSOLE_PORT" >/dev/null 2>&1 && break
  sleep 1
  [ "$i" -eq 60 ] && { echo "console failed to start:"; tail -20 .run/console.log; exit 1; }
done

# Prove the console we just started is ours, not a stray server on the same port.
if ! curl -fsS "http://127.0.0.1:$CONSOLE_PORT" | grep -q "CYCLOPS"; then
  echo "ERROR: something else is serving port $CONSOLE_PORT"; exit 1
fi

echo "console ready  →  http://127.0.0.1:$CONSOLE_PORT"
echo
echo "  stop with:  make stop"
echo "───────────────────────────────────────────────────────"
