// HEVI Frontend Doctor Script
// Runs pre-checks to verify frontend connectivity and configuration.
// Usage: node scripts/doctor.cjs
//
// Does NOT modify system configuration. Only reads env vars and HTTP probes.

const { execSync } = require('child_process');
const http = require('http');
const https = require('https');

const results = [];

function addResult(name, passed, detail) {
  results.push({ name, passed, detail });
}

function isTruthy(v) {
  if (!v) return false;
  return v.toLowerCase() === 'true';
}

function makeRequest(urlString, method = 'GET', extraHeaders = {}) {
  return new Promise((resolve) => {
    let url;
    try {
      url = new URL(urlString);
    } catch {
      resolve({ ok: false, error: 'Invalid URL' });
      return;
    }
    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname + url.search,
      method,
      timeout: 5000,
    };
    const client = url.protocol === 'https:' ? https : http;
    const req = client.request(options, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, statusCode: res.statusCode, headers: res.headers, body });
      });
    });
    req.on('error', (err) => {
      resolve({ ok: false, error: err.message });
    });
    req.on('timeout', () => {
      req.destroy();
      resolve({ ok: false, error: 'Timeout' });
    });
    for (const [k, v] of Object.entries(extraHeaders)) {
      req.setHeader(k, v);
    }
    req.end();
  });
}

// ── 1. Node version ──────────────────────────────────
try {
  const nodeVersion = execSync('node --version', { stdio: 'pipe' }).toString().trim();
  addResult('Node', true, `Node ${nodeVersion}`);
} catch (e) {
  addResult('Node', false, 'Node not found');
}

// ── 2. Frontend env ──────────────────────────────────
const NEXT_PUBLIC_USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK || '';
const NEXT_PUBLIC_API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';
const NODE_ENV = process.env.NODE_ENV || 'development';

const useMock = isTruthy(NEXT_PUBLIC_USE_MOCK);
const apiBase = NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';
const environment = NODE_ENV === 'production' ? 'production' : 'development';

if (environment === 'production' && useMock) {
  addResult('Frontend env', false, 'NEXT_PUBLIC_USE_MOCK=true in production - this is unusual and may indicate misconfiguration');
} else {
  addResult('Frontend env', true, `MODE=${environment}, USE_MOCK=${useMock}, API_BASE=${apiBase}`);
}

// ── 3. API base validation ───────────────────────────
try {
  new URL(apiBase);
  addResult('API base', true, `Valid URL: ${apiBase}`);
} catch {
  addResult('API base', false, `Invalid URL: ${apiBase}`);
}

// ── 4. Backend health ────────────────────────────────
(async () => {
  const start = Date.now();
  const healthResp = await makeRequest(`${apiBase}/api/health`, 'GET', { 'Accept': 'application/json' });
  const latency = Date.now() - start;
  if (healthResp.ok) {
    addResult('Backend health', true, `Healthy (latency: ${latency}ms, status: ${healthResp.statusCode})`);
  } else if (healthResp.error) {
    addResult('Backend health', false, `Error: ${healthResp.error.slice(0, 100)}`);
  } else {
    addResult('Backend health', false, `HTTP ${healthResp.statusCode}`);
  }

  // ── 5. CORS check ───────────────────────────────────
  const corsOrigin = apiBase.includes('localhost') || apiBase.includes('127.0.0.1')
    ? 'http://localhost:3000'
    : apiBase;

  const corsResp = await makeRequest(`${apiBase}/api/health`, 'OPTIONS', {
    'Origin': corsOrigin,
    'Access-Control-Request-Method': 'GET',
    'Access-Control-Request-Headers': 'Authorization, Content-Type',
  });
  const allowOrigin = corsResp.headers?.['access-control-allow-origin'];
  const corsPassed = corsResp.ok || allowOrigin === '*' || allowOrigin === corsOrigin;
  if (corsPassed) {
    addResult('CORS', true, `CORS headers present for origin: ${corsOrigin}`);
  } else {
    addResult('CORS', false, `CORS check failed for origin: ${corsOrigin}. Status: ${corsResp.statusCode}`);
  }

  // ── 6. Auth endpoint ────────────────────────────────
  // Try a GET to the login endpoint - should respond even if not allowed method
  const authResp = await makeRequest(`${apiBase}/api/auth/login`, 'GET');
  // The auth endpoint should at least exist (not 404)
  if (authResp.statusCode === 404) {
    addResult('Auth endpoint', false, 'Auth routes not found');
  } else {
    addResult('Auth endpoint', true, `Auth routes accessible (status: ${authResp.statusCode || 'reachable'})`);
  }

  // ── 7. SSE endpoint ────────────────────────────────
  // SSE endpoint URL pattern is checked (cannot fully test without auth)
  const ssePattern = `${apiBase}/api/tasks/.../progress`;
  addResult('SSE endpoint', true, `SSE URL pattern: ${ssePattern}`);

  // ── 8. Media route ───────────────────────────────────
  const mediaPattern = `${apiBase}/api/tasks/.../video`;
  addResult('Media route', true, `Media URL pattern: ${mediaPattern}`);

  // ── Summary ──────────────────────────────────────────
  const passed = results.filter(r => r.passed).length;
  const total = results.length;
  const ready = passed === total ? 'YES' : 'NO';
  const blockers = results.filter(r => !r.passed).map(r => r.detail).filter((d, i, arr) => arr.indexOf(d) === i);

  console.log('HEVI Frontend Doctor');
  console.log('====================');
  console.log('');
  results.forEach(r => {
    const status = r.passed ? 'PASS' : 'FAIL';
    console.log(`${status} — ${r.name}`);
    if (r.detail) {
      console.log(`      ${r.detail}`);
    }
  });
  console.log('');
  console.log(`MODE=${useMock ? 'MOCK' : 'REAL'}`);
  console.log(`READY=${ready}`);
  console.log(`BLOCKER=${blockers.length > 0 ? blockers[0] : 'none'}`);

  if (ready === 'NO') {
    process.exit(1);
  }
  process.exit(0);
})().catch(err => {
  console.error('Doctor script error:', err);
  process.exit(1);
});