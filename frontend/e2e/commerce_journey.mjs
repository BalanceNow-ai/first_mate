#!/usr/bin/env node
// Browser journey for checkout, payments, orders, Helm Dash tracking and dispatch.
//
// Drives the Flutter web build (served on HELM_WEB, default http://localhost:18432)
// against the REAL local stack (scripts/local_stack.sh up + seed): confirmation-
// required sign-up through GoTrue with the Mailpit link, server-priced courier and
// Helm Dash quotes, the local TEST MODE payment provider (signed webhook path),
// a dispatcher and an operator in separate browser contexts, staff roles granted
// with the audited grant-role CLI, and an operator profile created and activated
// through the admin API.
//
// The operator's position is a REAL reading from the browser geolocation API:
// Playwright grants the permission and supplies mocked device coordinates; the
// app reads them via navigator.geolocation only after the explicit "Share" action.
//
// Usage:
//   node frontend/e2e/commerce_journey.mjs
// Env: HELM_WEB, HELM_STACK (http://localhost:18080), HELM_MAILPIT (http://localhost:18025),
//      HELM_STACK_ROOT (checkout whose scripts/local_stack.sh runs the stack), HEADFUL=1,
//      E2E_ARTIFACTS (screenshots directory).
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require('playwright');
} catch {
  playwright = require(process.env.PLAYWRIGHT_PATH || '/opt/node-tools/node_modules/playwright');
}
const { chromium } = playwright;

const WEB = process.env.HELM_WEB || 'http://localhost:18432';
const STACK = process.env.HELM_STACK || 'http://localhost:18080';
const MAILPIT = process.env.HELM_MAILPIT || 'http://localhost:18025';
const STACK_ROOT = process.env.HELM_STACK_ROOT || path.resolve(new URL('../..', import.meta.url).pathname);
const ARTIFACTS = process.env.E2E_ARTIFACTS || path.join(process.cwd(), 'e2e-artifacts');
const RUN = randomUUID().slice(0, 8);
const PASSWORD = process.env.E2E_PASSWORD || `Pw-${randomUUID()}`;
// Inside the seeded Hauraki Gulf (local demo) area.
const PIN = { lat: '-36.80000', lng: '174.85000' };
// Mocked device coordinates handed to the browser geolocation API.
const DEVICE = { latitude: -36.8215, longitude: 174.8042, accuracy: 15 };

const steps = [];
let anonKey = null;
function pass(name, detail = '') {
  steps.push([name, true]);
  console.log(`[PASS] ${name}${detail ? ' — ' + detail : ''}`);
}
async function fail(name, err, pages) {
  steps.push([name, false]);
  console.log(`[FAIL] ${name} — ${err?.message || err}`);
  mkdirSync(ARTIFACTS, { recursive: true });
  for (const [label, p] of Object.entries(pages)) {
    try {
      await p.screenshot({ path: path.join(ARTIFACTS, `fail-${label}.png`), fullPage: true });
      console.log(`       screenshot: ${path.join(ARTIFACTS, `fail-${label}.png`)}`);
      if (process.env.E2E_DUMP) {
        const buttons = await p.locator('[role=button], button').evaluateAll((els) =>
          els.map((e) => `${e.tagName}:${e.getAttribute('aria-label') || e.textContent}`.slice(0, 80)));
        console.log(`       ${label} buttons: ${JSON.stringify(buttons)}`);
      }
    } catch {}
  }
}

// ------------------------------------------------------------------ helpers
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function json(url, init = {}) {
  const r = await fetch(url, init);
  const text = await r.text();
  let body = null;
  try { body = JSON.parse(text); } catch { body = text; }
  return { status: r.status, body };
}

function grantRole(email, role) {
  const out = execFileSync(path.join(STACK_ROOT, 'scripts', 'local_stack.sh'), ['cli', 'grant-role', email, role], {
    cwd: STACK_ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  return out.trim().split('\n').pop();
}

async function confirmationLink(email, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { body } = await json(`${MAILPIT}/api/v1/search?query=${encodeURIComponent('to:' + email)}`);
    for (const m of body?.messages || []) {
      const msg = await json(`${MAILPIT}/api/v1/message/${m.ID}`);
      const all = `${msg.body.Text || ''}${msg.body.HTML || ''}`;
      const link = all.match(/https?:\/\/[^\s"'<>]+\/verify\?[^\s"'<>]+/);
      if (link) return link[0].replace(/&amp;/g, '&');
    }
    await sleep(1000);
  }
  throw new Error(`no confirmation email for ${email}`);
}

/** The anon key the web build was compiled with (read from its main.dart.js is not
 *  needed): GoTrue sign-in for API-only steps uses the same public key the app uses. */
async function gotrueToken(email) {
  const r = await json(`${STACK}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', apikey: anonKey, authorization: `Bearer ${anonKey}` },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  if (r.status !== 200) throw new Error(`GoTrue sign-in ${email}: ${r.status} ${JSON.stringify(r.body)}`);
  return r.body.access_token;
}

function api(method, p, token, body, headers = {}) {
  return json(`${STACK}/api/v1${p}`, {
    method,
    headers: { 'content-type': 'application/json', authorization: `Bearer ${token}`, ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

// Flutter web (semantics enabled) helpers.
async function open(page, route) {
  await page.goto(`${WEB}/#${route}`);
  await page.waitForLoadState('domcontentloaded');
}
function byText(page, text) {
  // Flutter merges the texts of a semantics container into its aria-label.
  const quoted = text.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  return page.getByText(text, { exact: false }).or(page.locator(`[aria-label*="${quoted}"]`)).first();
}
async function see(page, text, timeout = 30000) {
  await byText(page, text).waitFor({ state: 'visible', timeout });
}
async function click(page, name, { exact = false, timeout = 30000 } = {}) {
  const btn = page
    .getByRole('button', { name, exact })
    .or(page.getByRole('menuitem', { name, exact }))
    .or(page.getByRole('switch', { name, exact }))
    .first();
  try {
    await btn.waitFor({ state: 'visible', timeout: Math.min(timeout, 8000) });
    // Disabled Flutter buttons (e.g. while a request is in flight) ignore taps.
    const deadline = Date.now() + timeout;
    while ((await btn.getAttribute('aria-disabled')) === 'true' && Date.now() < deadline) await sleep(200);
    await btn.click();
    return;
  } catch {}
  const el = exact ? page.getByText(name, { exact }).first() : byText(page, name);
  await el.waitFor({ state: 'visible', timeout });
  await el.click();
}
async function fill(page, label, value) {
  const box = page.getByRole('textbox', { name: label }).first();
  await box.waitFor({ state: 'visible', timeout: 30000 });
  // Flutter re-creates its DOM input when focus moves; retry until the value sticks.
  for (let attempt = 0; attempt < 4; attempt++) {
    await box.click();
    // Type real key events (as a person would): Flutter's controller sometimes misses a
    // programmatic DOM value change under load, leaving the field empty in the form state.
    await box.fill('');
    await box.pressSequentially(value, { delay: 15 });
    await sleep(150);
    try {
      if ((await box.inputValue({ timeout: 2000 })) === value) return;
    } catch {}
  }
  throw new Error(`could not enter "${label}"`);
}
// Flutter web can re-create an earlier input's DOM node while a later field gains focus,
// dropping its value; fill a group, then re-check every field and refill any that lost it.
async function fillAll(page, pairs) {
  for (const [label, value] of pairs) await fill(page, label, value);
  for (let round = 0; round < 3; round++) {
    let lost = false;
    for (const [label, value] of pairs) {
      const box = page.getByRole('textbox', { name: label }).first();
      if ((await box.inputValue({ timeout: 2000 }).catch(() => '')) !== value) {
        lost = true;
        await fill(page, label, value);
      }
    }
    if (!lost) return;
  }
  throw new Error('form values did not stick');
}

async function signupConfirmSignIn(page, email, name) {
  await open(page, '/signup');
  await fill(page, 'Full name', name);
  await fill(page, 'Email', email);
  await fill(page, 'Password', PASSWORD);
  await fill(page, 'Confirm password', PASSWORD);
  await click(page, 'Create Account');
  await page.waitForURL(/check-email/, { timeout: 30000 });
  const link = await confirmationLink(email);
  const r = await fetch(link, { redirect: 'manual' });
  if (![302, 303].includes(r.status)) throw new Error(`confirmation link answered ${r.status}`);
  await click(page, 'Back to sign in');
  await page.waitForURL(/login/, { timeout: 30000 });
  await fill(page, 'Email', email);
  await fill(page, 'Password', PASSWORD);
  await click(page, 'Sign In');
  await page.waitForURL((u) => !/login|check-email|provisioning/.test(u.hash), { timeout: 45000 });
}

async function addToCart(page, productId) {
  await open(page, `/products/${productId}`);
  await click(page, 'Add to cart');
  await see(page, 'to your cart');
}

/** Clicks [name] until [expectText] shows. Flutter does not expose a button's
 *  disabled state (e.g. while the previous request is still settling), so a
 *  tap can land on a momentarily disabled button. */
async function clickUntil(page, name, expectText, attempts = 5) {
  for (let i = 0; i < attempts; i++) {
    await click(page, name);
    try {
      await see(page, expectText, 4000);
      return;
    } catch {}
  }
  throw new Error(`"${expectText}" did not appear after clicking "${name}"`);
}

async function payTestMode(page, { declineFirst }) {
  await see(page, 'TEST MODE — no real charge');
  if (declineFirst) {
    await click(page, 'Simulate decline');
    await see(page, 'Payment declined');
    await clickUntil(page, 'Try again', 'Simulate success');
  }
  await click(page, 'Simulate success');
  await see(page, 'Payment confirmed', 45000);
}

// ------------------------------------------------------------------ journey
async function main() {
  console.log(`commerce journey ${RUN}: web ${WEB}, stack ${STACK}, stack root ${STACK_ROOT}`);
  const cfg = await json(`${STACK}/api/v1/config/public`);
  if (!cfg.body?.payments?.local_test_mode) throw new Error('stack is not in local test payment mode');
  // The public anon key is the one compiled into the build; extract it from the bundle.
  const js = await (await fetch(`${WEB}/main.dart.js`)).text();
  anonKey = (js.match(/eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/) || [])[0];
  if (!anonKey) throw new Error('could not find the public anon key in the web bundle');

  const products = (await json(`${STACK}/api/v1/products/?limit=100`)).body.items;
  const product = products.find((p) => p.sku === 'SYN-ZIP-TIES' && p.stock_quantity >= 3)
    || products.find((p) => !p.dangerous_goods && p.stock_quantity >= 3 && p.effective_price_cents < 5000);
  if (!product) throw new Error('no in-stock synthetic product');

  const browser = await chromium.launch({ headless: !process.env.HEADFUL });
  const customerCtx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const dispatcherCtx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const operatorCtx = await browser.newContext({
    viewport: { width: 1000, height: 1000 },
    geolocation: DEVICE,
    permissions: ['geolocation'],
  });
  const customer = await customerCtx.newPage();
  const dispatcher = await dispatcherCtx.newPage();
  const operator = await operatorCtx.newPage();
  const pages = { customer, dispatcher, operator };
  if (process.env.E2E_TRACE) {
    for (const [label, p] of Object.entries(pages)) {
      p.on('request', (r) => r.url().startsWith(STACK) && console.log(`   ${label} → ${r.method()} ${r.url().slice(STACK.length)}`));
      p.on('console', (m) => console.log(`   ${label} console.${m.type()}: ${m.text().slice(0, 300)}`));
    }
  }
  const emails = {
    customer: `journey-customer-${RUN}@example.test`,
    dispatcher: `journey-dispatcher-${RUN}@example.test`,
    operator: `journey-operator-${RUN}@example.test`,
    admin: `journey-admin-${RUN}@example.test`,
  };

  let current = '';
  const step = async (name, fn) => {
    current = name;
    const detail = await fn();
    pass(name, detail || '');
  };
  try {
    await step('customer: confirmation-required sign-up (Mailpit link) and sign-in', () =>
      signupConfirmSignIn(customer, emails.customer, 'Journey Customer'));

    await step(`customer: add ${product.sku} to the cart`, () => addToCart(customer, product.id));

    await step('checkout courier: server options, NZ address, server quote', async () => {
      await open(customer, '/checkout');
      await click(customer, 'Standard courier');
      await fill(customer, 'Full name *', 'Journey Customer');
      await fill(customer, 'Street address *', '1 Quay Street');
      await fill(customer, 'Town or city *', 'Auckland');
      await fill(customer, 'Postcode *', '1010');
      await fill(customer, 'Phone *', '021 555 0199');
      await click(customer, 'Get courier quote');
      await see(customer, 'Courier quote');
      await see(customer, 'Development rate card');
      return 'quote shown with development rate card label';
    });

    let courierOrderUrl = '';
    await step('review: server preview, place order (Idempotency-Key)', async () => {
      const placed = customer.waitForRequest((r) => r.url().endsWith('/orders/checkout') && r.method() === 'POST');
      await click(customer, 'Continue to review');
      await see(customer, 'Total (NZD)'); // server preview loaded (button enabled)
      await click(customer, 'Place order');
      const req = await placed;
      const key = req.headers()['idempotency-key'];
      if (!key || !/^[A-Za-z0-9_\-:.]{8,100}$/.test(key)) throw new Error(`bad Idempotency-Key ${key}`);
      await see(customer, 'Afterpay');
      return `Idempotency-Key ${key}`;
    });

    await step('payment: TEST MODE decline, then retry succeeds (server-confirmed)', async () => {
      await see(customer, 'Not available — Afterpay is not offered');
      await payTestMode(customer, { declineFirst: true });
    });

    await step('order detail shows Paid', async () => {
      await click(customer, 'View order');
      await customer.waitForURL(/#\/orders\//);
      courierOrderUrl = customer.url();
      await see(customer, 'Paid');
      return courierOrderUrl.split('#')[1];
    });

    let deliveryId = '';
    let hdOrderNumber = '';
    await step('Helm Dash order: pin inside the area, contact, quote, pay', async () => {
      await addToCart(customer, product.id);
      await open(customer, '/checkout');
      await click(customer, 'Helm Dash — delivered to your vessel');
      await see(customer, 'Where should we deliver?');
      await fill(customer, 'Latitude', PIN.lat);
      await fill(customer, 'Longitude', PIN.lng);
      await click(customer, 'Set pin');
      await see(customer, 'Inside Hauraki Gulf');
      await fillAll(customer, [
        ['Location name (e.g. bay or anchorage)', 'Motuihe Channel'],
        ['Vessel name *', 'Journey Runner'],
        ['Contact phone *', '021 555 0198'],
      ]);
      await click(customer, 'Get Helm Dash quote');
      await see(customer, 'Helm Dash quote');
      await click(customer, 'Continue to review');
      await see(customer, 'Total (NZD)');
      const created = customer.waitForResponse((r) => r.url().endsWith('/orders/checkout') && r.request().method() === 'POST');
      await click(customer, 'Place order');
      const order = await (await created).json();
      hdOrderNumber = order.order_number;
      await payTestMode(customer, { declineFirst: false });
      await click(customer, 'View order');
      await click(customer, 'Track delivery', { timeout: 45000 });
      await customer.waitForURL(/#\/dash\//);
      deliveryId = customer.url().split('/dash/')[1];
      await see(customer, 'Awaiting dispatch');
      return `${hdOrderNumber}, delivery ${deliveryId}`;
    });

    await step('dispatcher account: sign-up, grant-role dispatcher (CLI)', async () => {
      await signupConfirmSignIn(dispatcher, emails.dispatcher, 'Journey Dispatcher');
      return grantRole(emails.dispatcher, 'dispatcher');
    });

    let operatorId = '';
    await step('operator account: sign-up, grant-role operator, profile created + activated via admin API', async () => {
      await signupConfirmSignIn(operator, emails.operator, 'Journey Operator');
      const g = grantRole(emails.operator, 'operator');
      // Admin account through GoTrue + Mailpit, then the admin API.
      const s = await json(`${STACK}/auth/v1/signup`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', apikey: anonKey, authorization: `Bearer ${anonKey}` },
        body: JSON.stringify({ email: emails.admin, password: PASSWORD, data: { full_name: 'Journey Admin' } }),
      });
      if (s.status !== 200) throw new Error(`admin signup ${s.status}`);
      await fetch(await confirmationLink(emails.admin), { redirect: 'manual' });
      let adminTok = await gotrueToken(emails.admin);
      await api('POST', '/auth/provision', adminTok, { full_name: 'Journey Admin' });
      grantRole(emails.admin, 'admin');
      adminTok = await gotrueToken(emails.admin);
      const opTok = await gotrueToken(emails.operator);
      operatorId = (await api('GET', '/auth/me', opTok)).body.id;
      const created = await api('POST', '/dispatch/operators', adminTok, {
        user_id: operatorId,
        display_name: `Skipper Journey ${RUN.slice(0, 4)}`,
        vessel_name: 'MV Journey',
        area_id: 'hauraki-gulf',
      });
      if (created.status !== 201) throw new Error(`create operator ${created.status} ${JSON.stringify(created.body)}`);
      const act = await api('POST', `/dispatch/operators/${operatorId}/activate`, adminTok);
      if (act.status !== 200 || !act.body.active) throw new Error(`activate ${act.status}`);
      return `${g}; operator ${operatorId} active`;
    });

    await step('dispatcher console: find the delivery, assign the operator', async () => {
      await open(dispatcher, '/staff/dispatch');
      await see(dispatcher, 'Dispatch console');
      await click(dispatcher, `Order ${hdOrderNumber}`);
      await see(dispatcher, 'Assign a skipper');
      await click(dispatcher, 'Operator');
      await click(dispatcher, `Skipper Journey ${RUN.slice(0, 4)}`);
      const assigned = dispatcher.waitForResponse((r) => r.url().endsWith(`/dispatch/deliveries/${deliveryId}/assign`));
      await click(dispatcher, 'Assign', { exact: true });
      const res = await assigned;
      if (res.status() !== 200) throw new Error(`assign answered ${res.status()}`);
      await see(dispatcher, 'Skipper assigned');
    });

    await step('operator: online, accept the job, mark picked up', async () => {
      await open(operator, '/staff/operator');
      await see(operator, 'Profile active');
      await click(operator, 'Available for jobs');
      await see(operator, 'Online');
      await click(operator, `Order ${hdOrderNumber}`);
      await click(operator, 'Accept job');
      await see(operator, 'Job accepted');
      await click(operator, 'Mark picked up');
      await see(operator, 'Status: Picked up');
    });

    await step('customer tracking: status + "Awaiting first position report"', async () => {
      await open(customer, `/dash/${deliveryId}`);
      await see(customer, 'Picked up from the warehouse');
      await see(customer, 'Awaiting first position report');
      await see(customer, 'Skipper: Skipper Journey');
    });

    await step('operator shares a REAL browser geolocation reading (Playwright-mocked coordinates)', async () => {
      await click(operator, 'Share my current position');
      await see(operator, 'Share your current position?');
      const posted = operator.waitForRequest((r) => r.url().endsWith(`/dispatch/jobs/${deliveryId}/location`));
      await click(operator, 'Share position', { exact: true });
      const body = JSON.parse((await posted).postData());
      if (Math.abs(body.lat - DEVICE.latitude) > 1e-6 || Math.abs(body.lng - DEVICE.longitude) > 1e-6) {
        throw new Error(`posted ${JSON.stringify(body)}`);
      }
      await see(operator, 'Position shared');
      return `posted ${body.lat}, ${body.lng} recorded_at ${body.recorded_at} accuracy ${body.accuracy_m}`;
    });

    await step('customer tracking shows the reported position (device source, no interpolation)', async () => {
      await see(customer, "Reported by the skipper's device", 30000); // via the 10 s poll
      await see(customer, `Position ${DEVICE.latitude.toFixed(5)}, ${DEVICE.longitude.toFixed(5)}`);
      await see(customer, 'Last reported');
    });

    await step('operator: en route → delivered; customer sees Delivered', async () => {
      await click(operator, 'Mark en route');
      await see(operator, 'Status: En route');
      await click(operator, 'Mark delivered');
      await see(operator, 'Status: Delivered');
      await see(customer, 'Delivered', 30000);
      await open(customer, courierOrderUrl.split('#')[1]);
      await see(customer, 'Paid');
    });
  } catch (e) {
    await fail(current, e, pages);
  } finally {
    await browser.close();
  }
  const ok = steps.filter((s) => s[1]).length;
  console.log(`\n${ok}/${steps.length} steps passed`);
  process.exit(steps.every((s) => s[1]) ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});

// Waiters created before a failing click must not crash the run.
process.on('unhandledRejection', () => {});
