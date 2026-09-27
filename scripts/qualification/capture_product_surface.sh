#!/usr/bin/env bash
# Capture HEVI's own product surface for the P5.2 product-video E2E.
#
# This is the *real* product: the prebuilt hevi-web production bundle served by
# Next.js, rendering against the real FastAPI backend and the real database, with
# data seeded through the same public API calls hevi-web/e2e/product.spec.ts
# makes. There are no mocks, and the product's own settings page reports
# "Mode REAL" plus a live latency, so a mocked surface would change the evidence.
#
# The E2E skips rather than substituting a mock when the frames are absent, so
# this script is what makes that path real. It does write test rows into the
# development database; point DATABASE_URL elsewhere if that matters.
#
#   HEVI_REPO   source checkout            (default /data/soffy/projects/hevi)
#   OUT         frame output directory     (default /tmp/opencode/frames)
#   WORK        scratch directory         (default /tmp/opencode/product-surface)
#   API_PORT    backend port              (default 8001)
#   WEB_PORT    frontend port             (default 3111)
set -euo pipefail

REPO="${HEVI_REPO:-/data/soffy/projects/hevi}"
OUT="${OUT:-/tmp/opencode/frames}"
WORK="${WORK:-/tmp/opencode/product-surface}"
API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-3111}"
API="http://127.0.0.1:${API_PORT}"
WEB="http://127.0.0.1:${WEB_PORT}"

mkdir -p "$OUT" "$WORK"

if [ ! -d "$REPO/hevi-web/node_modules/playwright-core" ]; then
  echo "playwright-core not installed in $REPO/hevi-web/node_modules" >&2
  exit 1
fi

cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "== backend (real hevi FastAPI) =="
( cd "$REPO" && \
  DATABASE_URL="${DATABASE_URL:-postgresql://hevi:hevi@127.0.0.1:5432/hevi}" \
  JWT_SECRET="${JWT_SECRET:-product-surface-capture-not-a-secret}" \
  CORS_ORIGINS="http://127.0.0.1:${WEB_PORT},http://127.0.0.1:3100" \
  exec .venv/bin/python -m uvicorn hevi.api.main:app \
    --host 127.0.0.1 --port "$API_PORT" --log-level warning ) \
  > "$WORK/api.log" 2>&1 &
API_PID=$!
for _ in $(seq 1 40); do
  sleep 3
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$API/api/health/live")" = 200 ] && break
done
echo "  health: $(curl -s -m 5 "$API/api/health/live")"

echo "== frontend (real prebuilt hevi-web) =="
( cd "$REPO/hevi-web" && exec npx next start -p "$WEB_PORT" ) > "$WORK/web.log" 2>&1 &
WEB_PID=$!
for _ in $(seq 1 40); do
  sleep 2
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$WEB/dashboard")" = 200 ] && break
done
echo "  dashboard: $(curl -s -m 5 -o /dev/null -w '%{http_code}' "$WEB/dashboard")"

echo "== seeding through the real public API =="
TOKEN=$(curl -s -m 20 -X POST "$API/api/auth/register" -H 'Content-Type: application/json' \
  -d '{"email":"p52-capture@hevi-video.com","password":"Capture-2026!","display_name":"林导演"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
if [ -z "$TOKEN" ]; then
  echo "  could not acquire a token; the frames will show an unauthenticated surface" >&2
fi
printf '%s' "$TOKEN" > "$WORK/token"

IDENTITY=$(curl -s -m 20 -X POST "$API/api/identities" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"canonical_name":"苏晚","voice_id":"v-suwan","canon_constraints":["苏晚永远穿红色风衣"]}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("identity_id",""))')
for project in hevi-demo-series-01 hevi-demo-series-02; do
  curl -s -m 20 -X POST "$API/api/identities/projects/$project/bindings" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"identity_id\":\"$IDENTITY\"}" -o /dev/null
done
curl -s -m 20 -X POST "$API/api/identities/$IDENTITY/appearances" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"appearance_id":"winter-coat","kind":"outfit"}' -o /dev/null
curl -s -m 20 -X POST "$API/api/incidents/open" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"production_run_id":"hevi-demo-series-01","node_key":"artifact.download",
       "failure":"DELIVERY_INTEGRITY",
       "evidence":{"signature":"download interrupted at 62%"}}' -o /dev/null
echo "  seeded identity=$IDENTITY"

echo "== capturing =="
cat > "$WORK/grab.cjs" <<EOF
const fs = require('fs');
const { chromium } = require('$REPO/hevi-web/node_modules/playwright-core');
const API = '$API', WEB = '$WEB', OUT = '$OUT';
const T = fs.readFileSync('$WORK/token', 'utf8').trim();
const SHOTS = [
  ['studio', '/studio', null, null],
  ['director', '/director', null, null],
  ['tongjian', '/tongjian', null, null],
  ['explainer', '/explainer', null, null],
  ['pricing', '/pricing', null, null],
  ['vi', '/video-intelligence', null, null],
  ['settings', '/settings', null, null],
  ['ws_chars', '/workspace', null, '角色库'],
  ['ws_issues', '/workspace', '当前项目 ID|hevi-demo-series-01', '制作问题'],
  ['ws_cont', '/workspace', '当前项目 ID|hevi-demo-series-01', '连续性'],
];
(async () => {
  const b = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  let ok = 0;
  for (const [name, route, fill, tab] of SHOTS) {
    const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
    await ctx.addInitScript(t => localStorage.setItem('hevi_token', t), T);
    const p = await ctx.newPage();
    // The prebuilt bundle is a production build whose API base is the public
    // host, which is unreachable from here. Fulfil both that origin and the dev
    // fallback from the local real API, which also sidesteps CORS.
    for (const origin of ['http://127.0.0.1:8000', 'https://api-prod.sxueji.com']) {
      await p.route(origin + '/**', async r => {
        const q = r.request(), u = new URL(q.url());
        try {
          const res = await fetch(API + u.pathname + u.search, {
            method: q.method(), headers: q.headers(),
            body: ['GET', 'HEAD'].includes(q.method()) ? undefined : q.postDataBuffer(),
          });
          const body = Buffer.from(await res.arrayBuffer()), headers = {};
          res.headers.forEach((v, k) => {
            if (!/^access-control|^content-encoding|^content-length|^transfer-encoding/i.test(k))
              headers[k] = v;
          });
          await r.fulfill({ status: res.status, headers, body });
        } catch {
          await r.fulfill({ status: 502, contentType: 'application/json', body: '{}' });
        }
      });
    }
    try {
      await p.goto(WEB + route, { waitUntil: 'networkidle', timeout: 35000 });
      await p.waitForTimeout(2500);
      if (fill) {
        const [label, value] = fill.split('|');
        await p.getByLabel(label).fill(value);
        await p.waitForTimeout(1500);
      }
      if (tab) { await p.getByRole('tab', { name: tab }).click(); await p.waitForTimeout(2500); }
      await p.screenshot({ path: OUT + '/' + name + '.png' });
      ok++;
      console.log('  ok   ' + name.padEnd(10) + route + ' ' + (tab || ''));
    } catch (e) {
      console.log('  FAIL ' + name.padEnd(10) + e.message.split('\n')[0]);
    }
    await ctx.close();
  }
  await b.close();
  console.log('captured ' + ok + '/' + SHOTS.length);
})();
EOF
node "$WORK/grab.cjs"
echo "== frames in $OUT =="
ls -la "$OUT"
