#!/usr/bin/env bash
# Verify a running stack end to end. Run this before every demo.
set -euo pipefail
API=http://127.0.0.1:${CYCLOPS_API_PORT:-8000}

step() { printf "  %-46s" "$1"; }
ok()   { echo "OK"; }
fail() { echo "FAIL"; exit 1; }

echo "── smoke ──────────────────────────────────────────────"

step "health"
curl -fsS $API/v1/health | grep -q '"status":"ok"' && ok || fail

step "data status declares synthetic imagery"
curl -fsS $API/v1/health | grep -q 'SYNTHETIC' && ok || fail

step "cases listed"
CASE=$(curl -fsS $API/v1/cases | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')
[ -n "$CASE" ] && ok || fail

step "track loads ($CASE)"
TS=$(curl -fsS "$API/v1/cases/$CASE/track" | python3 -c \
  'import sys,json; o=json.load(sys.stdin)["observed"]; print(o[len(o)//2]["ts"])')
[ -n "$TS" ] && ok || fail

step "track honours until="
FULL=$(curl -fsS "$API/v1/cases/$CASE/track" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["observed"]))')
PART=$(curl -fsS "$API/v1/cases/$CASE/track?until=$TS" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["observed"]))')
[ "$PART" -lt "$FULL" ] && ok || fail

step "classify returns interval + CAM"
curl -fsS -X POST $API/v1/classify -H 'content-type: application/json' \
  -d "{\"case_id\":\"$CASE\",\"timestamp\":\"$TS\"}" \
  | python3 -c 'import sys,json; b=json.load(sys.stdin); assert len(b["wind_kt_ci"])==2; assert b["cam"]["data"]' && ok || fail

step "nowcast returns 4 leads with quantiles"
curl -fsS -X POST $API/v1/nowcast -H 'content-type: application/json' \
  -d "{\"case_id\":\"$CASE\",\"t0\":\"$TS\"}" \
  | python3 -c 'import sys,json; b=json.load(sys.stdin); assert [f["lead_h"] for f in b["forecasts"]]==[6,12,18,24]' && ok || fail

step "frame png renders"
curl -fsS "$API/v1/cases/$CASE/frames/$TS" -o /dev/null -w '%{content_type}' \
  | grep -q 'image/png' && ok || fail

step "baseline metrics exposed"
curl -fsS $API/v1/metrics/baselines | grep -q persistence && ok || fail

step "replay session starts"
SID=$(curl -fsS -X POST "$API/v1/replay/$CASE/start" -H 'content-type: application/json' \
  -d '{"speed":300}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
[ -n "$SID" ] && ok || fail
curl -fsS -X DELETE "$API/v1/replay/$SID" >/dev/null

echo "── all smoke checks passed ────────────────────────────"
