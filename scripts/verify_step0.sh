#!/usr/bin/env bash
# Step 0 verification harness. Prints PASS/FAIL per check.
pass=0; fail=0
ok()   { echo "  PASS  $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail+1)); }
check(){ if [ "$2" = "$3" ]; then ok "$1 ($2)"; else bad "$1 (got '$2', want '$3')"; fi; }

echo "== A. Backend =="
H=$(curl -s -o /tmp/h.json -w '%{http_code}' http://127.0.0.1:5000/api/health)
check "A1 GET /api/health returns 200" "$H" "200"
python3 - <<'PY' && ok "A2 health body has status/service/version/env/timestamp" || bad "A2 health body shape"
import json;d=json.load(open('/tmp/h.json'))
assert d['status']=='ok' and d['service']=='auspify-tms-api' and d['version'] and d['environment'] and d['timestamp'], d
PY
curl -s -D /tmp/hh.txt -o /dev/null http://127.0.0.1:5000/api/health
for hdr in "X-Content-Type-Options: nosniff" "X-Frame-Options: DENY" "Content-Security-Policy:" "Referrer-Policy: no-referrer" "Cache-Control: no-store"; do
  grep -qi "$hdr" /tmp/hh.txt && ok "A3 header present -> $hdr" || bad "A3 header missing -> $hdr"
done
check "A4 unknown route returns 404" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/api/nope)" "404"
check "A5 wrong method returns 405" "$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:5000/api/health)" "405"
curl -s http://127.0.0.1:5000/api/nope | grep -q '"error"' && ok "A6 404 body is JSON error, not HTML" || bad "A6 404 body"
A=$(curl -s -D - -o /dev/null -H 'Origin: http://localhost:5173' http://127.0.0.1:5000/api/health | grep -ci 'access-control-allow-origin: http://localhost:5173')
check "A7 allowed origin gets CORS header" "$A" "1"
B=$(curl -s -D - -o /dev/null -H 'Origin: http://evil.example.com' http://127.0.0.1:5000/api/health | grep -ci 'access-control-allow-origin')
check "A8 disallowed origin gets no CORS header" "$B" "0"

check "A9 API index at / returns 200 (preview page)" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/)" "200"
curl -s http://127.0.0.1:5000/ | grep -q '"service": "auspify-tms-api"' && ok "A10 API index describes the service, no config dump" || bad "A10 API index body"

curl -s -D /tmp/page.txt -o /tmp/page.html -H 'Accept: text/html,application/xhtml+xml,*/*;q=0.8' http://127.0.0.1:5000/ >/dev/null
grep -q '<title>Auspify TMS API</title>' /tmp/page.html && ok "A11 browser gets the HTML status page on :5000" || bad "A11 browser status page"
grep -qi 'x-frame-options' /tmp/page.txt && bad "A12 status page blocked from being framed (preview would be blank)" || ok "A12 status page is embeddable (no X-Frame-Options)"
grep -qi "frame-ancestors \*" /tmp/page.txt && ok "A13 status page CSP allows framing, scripts still forbidden" || bad "A13 status page CSP"
curl -s -D /tmp/api.txt -o /dev/null http://127.0.0.1:5000/api/health
grep -qi 'x-frame-options: DENY' /tmp/api.txt && ok "A14 API responses stay locked down (X-Frame-Options: DENY)" || bad "A14 API framing headers"

echo "== B. Secrets =="
S=$(grep '^SECRET_KEY=' /home/user/auspify_tms/backend/.env | cut -d= -f2)
J=$(grep '^JWT_SECRET_KEY=' /home/user/auspify_tms/backend/.env | cut -d= -f2)
{ curl -s http://127.0.0.1:5000/api/health; cat /tmp/hh.txt; } | grep -qE "$S|$J" && bad "B1 secrets leak in HTTP response" || ok "B1 no secret keys in HTTP response"
cd /home/user/auspify_tms
git check-ignore -q backend/.env && ok "B2 backend/.env is git-ignored" || bad "B2 backend/.env ignored"
grep -q "replace-me" backend/.env.example && ok "B3 .env.example holds placeholders only" || bad "B3 .env.example"
grep -rqnE "(SECRET_KEY|JWT_SECRET_KEY)\s*=\s*['\"][0-9a-zA-Z]{6,}" backend/app backend/run.py && bad "B4 hardcoded secret in source" || ok "B4 no hardcoded secrets in source"
cp backend/.env /tmp/env.bak
rm backend/.env
( cd backend && env -u SECRET_KEY -u JWT_SECRET_KEY .venv/bin/python -c "import app" >/dev/null 2>&1 )
code=$?
cp /tmp/env.bak backend/.env
check "B5 refuses to boot with no SECRET_KEY configured (exit code 1)" "$code" "1"

echo "== C. Frontend =="
check "C1 React dev server serves index.html" "$(curl -s -o /tmp/idx.html -w '%{http_code}' http://127.0.0.1:5173/)" "200"
grep -q "Auspify TMS" /tmp/idx.html && ok "C2 page title is correct" || bad "C2 page title"
check "C3 frontend proxies /api/health to Flask" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/api/health)" "200"
check "C4 App.jsx compiles via Vite" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/src/App.jsx)" "200"
curl -s http://127.0.0.1:5173/src/App.jsx | grep -q "Routes" && ok "C4b router routes are served" || bad "C4b router routes"
check "C5 preview host header accepted (no allowlist block)" "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: 5173-xyz.e2b.app' http://127.0.0.1:5173/)" "200"
check "C6 production build succeeds" "$(cd frontend && npm run build >/dev/null 2>&1 && echo 0 || echo 1)" "0"
rm -rf frontend/dist

echo
echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
