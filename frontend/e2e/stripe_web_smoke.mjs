#!/usr/bin/env node
// Smoke test: the Flutter web build loads Stripe.js lazily for provider=stripe.
//
// No backend and no real Stripe account: Supabase sign-in and every API call are
// answered by Playwright route interception from the captured fixtures in
// test/fixtures/api, with the payment provider switched to "stripe", a FAKE
// publishable key and a FAKE client secret. Stripe.js itself is fetched from
// https://js.stripe.com only if the network allows it; with a fake key Stripe
// cannot show a real card form, so this checks the integration up to that point:
//
//   1. Before the payment step: no Stripe.js script tag on the page.
//   2. On /orders/<id>/pay with provider=stripe: the app injects
//      <script id="helm-stripe-js" src="https://js.stripe.com/v3/">.
//   3. The page then shows either the Payment Element host (Stripe.js loaded) or
//      the explicit "Card payments are unavailable right now" state — never
//      "Payment confirmed" (nothing marks the order paid client-side).
//
// Usage:
//   (cd frontend && flutter build web --release --dart-define=API_BASE_URL=... ...)
//   node frontend/e2e/stripe_web_smoke.mjs
// Env: HELM_WEB_DIR (default frontend/build/web), HELM_API (the API_BASE_URL the
//      build was compiled with, default https://api.example.invalid/api/v1),
//      HELM_SUPABASE (default https://example.supabase.co), HELM_CSP=1 to serve
//      the page with the production Content-Security-Policy from
//      deploy/nginx/snippets/security-headers.conf (the API must then be
//      same-origin, e.g. HELM_API=http://localhost:<port>/api/v1 with HELM_PORT),
//      HELM_BLOCK_STRIPE=1 to abort js.stripe.com (expects the unavailable state).
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require('playwright');
} catch {
  playwright = require(process.env.PLAYWRIGHT_PATH || '/opt/node-tools/node_modules/playwright');
}
const { chromium } = playwright;

const HERE = path.dirname(new URL(import.meta.url).pathname);
const FRONTEND = path.resolve(HERE, '..');
const WEB_DIR = process.env.HELM_WEB_DIR || path.join(FRONTEND, 'build', 'web');
const API = (process.env.HELM_API || 'https://api.example.invalid/api/v1').replace(/\/$/, '');
const SUPABASE = (process.env.HELM_SUPABASE || 'https://example.supabase.co').replace(/\/$/, '');
const PORT = Number(process.env.HELM_PORT || 18533);
const WITH_CSP = process.env.HELM_CSP === '1';
// HELM_BLOCK_STRIPE=1 aborts every js.stripe.com request (offline / blocked).
const BLOCK_STRIPE = process.env.HELM_BLOCK_STRIPE === '1';

const fixture = (name) => JSON.parse(readFileSync(path.join(FRONTEND, 'test', 'fixtures', 'api', `${name}.json`), 'utf8'));

// ------------------------------------------------------------- fixtures
const me = fixture('auth_me');
const order = fixture('order_checkout_created');
const orderId = order.id;
const baseConfig = fixture('config_public');
const config = {
  ...baseConfig,
  payments: { ...baseConfig.payments, provider: 'stripe', stripe_publishable_key: 'pk_test_HELMSMOKEFAKEKEY', local_test_mode: false },
};
const intent = {
  ...fixture('payment_intent_local'),
  order_id: orderId,
  provider: 'stripe',
  payment_intent_id: 'pi_3HelmSmokeFake',
  client_secret: 'pi_3HelmSmokeFake_secret_HelmSmokeFake',
  publishable_key: 'pk_test_HELMSMOKEFAKEKEY',
  test_mode: false,
  expires_at: new Date(Date.now() + 25 * 60 * 1000).toISOString(),
};
order.expires_at = intent.expires_at;

function b64url(obj) {
  return Buffer.from(JSON.stringify(obj)).toString('base64url');
}
const exp = Math.floor(Date.now() / 1000) + 3600;
const accessToken = `${b64url({ alg: 'HS256', typ: 'JWT' })}.${b64url({ sub: me.id, email: me.email, exp, aud: 'authenticated', role: 'authenticated' })}.c2ln`;
const session = {
  access_token: accessToken,
  token_type: 'bearer',
  expires_in: 3600,
  expires_at: exp,
  refresh_token: 'smoke-refresh',
  user: {
    id: me.id,
    aud: 'authenticated',
    role: 'authenticated',
    email: me.email,
    email_confirmed_at: '2026-01-01T00:00:00Z',
    app_metadata: { provider: 'email' },
    user_metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
};

// ------------------------------------------------------------- static server
const CSP = (() => {
  const conf = readFileSync(path.join(FRONTEND, '..', 'deploy', 'nginx', 'snippets', 'security-headers.conf'), 'utf8');
  const m = conf.match(/add_header Content-Security-Policy "([^"]+)"/);
  return m ? m[1] : null;
})();
const TYPES = { '.html': 'text/html', '.js': 'application/javascript', '.mjs': 'application/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.png': 'image/png', '.otf': 'font/otf', '.ttf': 'font/ttf', '.css': 'text/css', '.frag': 'text/plain', '.bin': 'application/octet-stream' };
const server = createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (p === '/') p = '/index.html';
  let file = path.join(WEB_DIR, p);
  if (!file.startsWith(WEB_DIR) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(WEB_DIR, 'index.html');
  const headers = { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' };
  if (WITH_CSP && CSP) headers['content-security-policy'] = CSP;
  res.writeHead(200, headers);
  res.end(readFileSync(file));
});

// ------------------------------------------------------------- run
const observations = [];
const note = (s) => {
  observations.push(s);
  console.log(`  - ${s}`);
};

async function main() {
  if (!existsSync(path.join(WEB_DIR, 'main.dart.js'))) throw new Error(`no web build at ${WEB_DIR}`);
  await new Promise((r) => server.listen(PORT, '127.0.0.1', r));
  const WEB = `http://localhost:${PORT}`;
  console.log(`Serving ${WEB_DIR} at ${WEB}${WITH_CSP ? ' with the production CSP' : ''}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1100, height: 1400 } });
  const page = await context.newPage();
  const apiCalls = [];
  const stripeRequests = [];
  const consoleErrors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300));
  });
  page.on('request', (r) => {
    if (/stripe\.(com|network)/.test(r.url())) stripeRequests.push(r.url());
  });
  page.on('requestfailed', (r) => {
    if (/stripe\.(com|network)/.test(r.url())) stripeRequests.push(`FAILED ${r.url()} (${r.failure()?.errorText})`);
  });

  const cors = {
    'access-control-allow-origin': '*',
    'access-control-allow-headers': '*',
    'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
  };
  const json = (route, status, body) =>
    route.fulfill({ status, headers: { ...cors, 'content-type': 'application/json' }, body: JSON.stringify(body) });

  if (BLOCK_STRIPE) await page.route('https://js.stripe.com/**', (route) => route.abort('blockedbyclient'));
  await page.route(`${SUPABASE}/**`, (route) => {
    const req = route.request();
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const url = new URL(req.url());
    if (url.pathname.endsWith('/auth/v1/token')) return json(route, 200, session);
    if (url.pathname.endsWith('/auth/v1/user')) return json(route, 200, session.user);
    if (url.pathname.endsWith('/auth/v1/logout')) return route.fulfill({ status: 204, headers: cors });
    return json(route, 404, { message: 'not stubbed' });
  });
  await page.route(`${API}/**`, (route) => {
    const req = route.request();
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const p = new URL(req.url()).pathname.replace(new URL(API).pathname, '');
    apiCalls.push(`${req.method()} ${p}`);
    const key = `${req.method()} ${p}`;
    if (key === 'POST /auth/provision') return json(route, 200, fixture('provision_existing'));
    if (key === 'GET /auth/me') return json(route, 200, me);
    if (key === 'GET /config/public') return json(route, 200, config);
    if (key === `GET /orders/${orderId}`) return json(route, 200, order);
    if (key === `POST /payments/orders/${orderId}/intent`) return json(route, 200, intent);
    if (key === 'GET /cart/') return json(route, 200, fixture('cart_empty'));
    if (key === 'GET /vessels/') return json(route, 200, fixture('vessels_list'));
    return json(route, 404, { detail: 'Not Found', code: 'not_found' });
  });

  const scriptTag = () =>
    page.evaluate(() => {
      const s = document.getElementById('helm-stripe-js');
      return s ? s.getAttribute('src') : null;
    });

  // Sign in (stubbed GoTrue) through the real login form.
  await page.goto(`${WEB}/#/login`);
  const email = page.getByRole('textbox', { name: 'Email' }).first();
  await email.waitFor({ state: 'visible', timeout: 60000 });
  for (const [label, value] of [['Email', me.email], ['Password', 'smoke-password']]) {
    const box = page.getByRole('textbox', { name: label }).first();
    for (let i = 0; i < 4; i++) {
      await box.click();
      await box.fill(value);
      await page.waitForTimeout(150);
      if ((await box.inputValue().catch(() => '')) === value) break;
    }
  }
  await page.getByRole('button', { name: 'Sign In' }).first().click();
  await page.waitForURL((u) => !/login|provisioning/.test(u.hash), { timeout: 45000 });
  note(`signed in (stubbed Supabase); now at ${new URL(page.url()).hash}`);
  const before = await scriptTag();
  note(`before the payment step: Stripe.js script tag ${before ? `PRESENT (${before})` : 'absent'}`);
  if (before) throw new Error('Stripe.js was injected before the payment step');

  await page.goto(`${WEB}/#/orders/${orderId}/pay`);
  await page.waitForFunction(() => !!document.getElementById('helm-stripe-js'), null, { timeout: 45000 });
  const src = await scriptTag();
  note(`payment step (provider=stripe): script tag injected with src=${src}`);
  if (src !== 'https://js.stripe.com/v3/') throw new Error(`unexpected Stripe.js src ${src}`);

  // Wait for the outcome: element host, or the explicit unavailable state.
  const deadline = Date.now() + 60000;
  let outcome = null;
  let maxHostIframes = 0;
  while (Date.now() < deadline && !outcome) {
    const state = await page.evaluate(() => ({
      stripeGlobal: typeof window.Stripe === 'function',
      host: !!document.querySelector('[id^="helm-stripe-host-"]'),
      iframes: Array.from(document.querySelectorAll('[id^="helm-stripe-host-"] iframe')).map((f) => f.getAttribute('src')?.slice(0, 80)),
      text: document.body.innerText + ' ' + Array.from(document.querySelectorAll('[aria-label]')).map((e) => e.getAttribute('aria-label')).join(' '),
    }));
    maxHostIframes = Math.max(maxHostIframes, state.iframes.length);
    if (/Card payments are unavailable right now/.test(state.text)) outcome = { kind: 'unavailable', ...state };
    else if (/Payment confirmed/.test(state.text)) outcome = { kind: 'PAID-CLIENT-SIDE', ...state };
    else if (state.host && state.iframes.length && /Pay \$/.test(state.text) && !/Loading the secure card form/.test(state.text)) outcome = { kind: 'element', ...state };
    else await page.waitForTimeout(100);
  }
  if (!outcome) throw new Error('neither the card form nor the unavailable state appeared within 60s');
  note(`window.Stripe defined: ${outcome.stripeGlobal}`);
  note(`payment element host present: ${outcome.host}; iframes in host: ${JSON.stringify(outcome.iframes)}`);
  note(`Stripe iframes seen inside the HtmlElementView host while mounting: ${maxHostIframes}`);
  const reason = outcome.text.match(/Card payments are unavailable right now\s*([^\n]*?Nothing was charged)/);
  note(`outcome: ${outcome.kind}${reason ? ` — "${reason[1].slice(0, 200)}"` : ''}`);
  if (outcome.kind === 'PAID-CLIENT-SIDE') throw new Error('order shown as paid without the server');
  if (BLOCK_STRIPE && outcome.kind !== 'unavailable') throw new Error('Stripe.js was blocked but no unavailable state');
  note(`"Payment confirmed" shown: ${/Payment confirmed/.test(outcome.text)}`);
  note(`API calls: ${JSON.stringify([...new Set(apiCalls)])}`);
  note(`Stripe network requests (${stripeRequests.length}): ${JSON.stringify(stripeRequests.slice(0, 8))}`);
  const cspErrors = consoleErrors.filter((e) => /Content Security Policy|Refused to/.test(e));
  note(`CSP violations in console: ${cspErrors.length ? JSON.stringify(cspErrors) : 'none'}`);
  await page.screenshot({ path: process.env.SMOKE_SCREENSHOT || path.join(process.cwd(), 'stripe-web-smoke.png'), fullPage: true });
  await browser.close();
  server.close();
  console.log('[PASS] Stripe.js is injected lazily on the stripe payment step; no client-side "paid"');
}

main().catch((e) => {
  console.log(`[FAIL] ${e.message}`);
  console.log(observations.join('\n'));
  server.close();
  process.exit(1);
});
