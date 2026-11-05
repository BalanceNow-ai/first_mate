#!/usr/bin/env node
// Engagement browser journey (node Playwright) against a release web build and the
// REAL local stack (scripts/local_stack.sh up + seed). Nothing is mocked:
//
//   confirmed signup (Mailpit link) → add vessel Yamaha F150 → ask the First Mate →
//   grounded answer with a source and a fitting product → tap "Add to cart" → cart has it →
//   edit the engine to Suzuki DF140 → ask again → the F150 part is no longer offered as fitting →
//   earn points by paying an order (local TEST MODE payment, API) → redeem a discount in the UI →
//   create a crew and invite a second account, who accepts in its own browser context →
//   an admin (role granted with the grant-role CLI) verifies a fitment rule in the admin console.
//
// Usage:
//   node frontend/e2e/engagement_journey.mjs
// Environment (defaults in brackets):
//   WEB_URL      the served web build                      [http://localhost:18433]
//   API_URL      the stack's public URL for node-side calls [http://localhost:18080]
//   MAILPIT_URL  Mailpit                                   [http://localhost:18025]
//   STACK_ROOT   checkout with .env + scripts/local_stack.sh [repository root]
//   HOST_MAP     Chromium host-resolver rule for the API host the build was compiled
//                against (release builds refuse loopback URLs), e.g.
//                "MAP helm-local.test 127.0.0.1"           [none]
//   OUT_DIR      screenshots on failure                    [os tmpdir]
//   HEADED=1     show the browser
// Exit status 0 only if every step passes.
import { execFileSync } from 'node:child_process';
import { createHmac, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '..', '..');

async function loadPlaywright() {
  try {
    return await import('playwright');
  } catch {
    const root = execFileSync('npm', ['root', '-g']).toString().trim();
    return await import(join(root, 'playwright', 'index.mjs'));
  }
}

const WEB = (process.env.WEB_URL ?? 'http://localhost:18433').replace(/\/$/, '');
const API = (process.env.API_URL ?? 'http://localhost:18080').replace(/\/$/, '');
const MAILPIT = (process.env.MAILPIT_URL ?? 'http://localhost:18025').replace(/\/$/, '');
const STACK_ROOT = process.env.STACK_ROOT ?? repo;
const OUT = process.env.OUT_DIR ?? join(tmpdir(), 'helm-engagement-e2e');
mkdirSync(OUT, { recursive: true });

const steps = [];
let currentPages = [];
function step(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) throw new Error(`step failed: ${name}`);
}

// ------------------------------------------------------------------ stack access
function secret() {
  if (process.env.SUPABASE_JWT_SECRET) return process.env.SUPABASE_JWT_SECRET;
  const env = join(STACK_ROOT, '.env');
  if (existsSync(env)) {
    const m = readFileSync(env, 'utf8').match(/^\s*SUPABASE_JWT_SECRET=(.*)$/m);
    if (m) return m[1].trim().replace(/^['"]|['"]$/g, '');
  }
  throw new Error('SUPABASE_JWT_SECRET not found (env or STACK_ROOT/.env)');
}
const b64 = (b) => Buffer.from(b).toString('base64url');
function anonKey() {
  const now = Math.floor(Date.now() / 1000);
  const h = b64(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const p = b64(JSON.stringify({ role: 'anon', iss: 'supabase', iat: now, exp: now + 3600 }));
  return `${h}.${p}.${createHmac('sha256', secret()).update(`${h}.${p}`).digest('base64url')}`;
}
const ANON = anonKey();

async function auth(path, body, params = {}) {
  const qs = new URLSearchParams(params).toString();
  const r = await fetch(`${API}/auth/v1/${path}${qs ? '?' + qs : ''}`, {
    method: 'POST',
    headers: { apikey: ANON, Authorization: `Bearer ${ANON}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}

async function api(method, path, token, body, headers = {}) {
  for (let i = 0; i < 30; i++) {
    const r = await fetch(`${API}/api/v1${path}`, {
      method,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json', ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (r.status === 502 && !(r.headers.get('content-type') ?? '').includes('json')) {
      await new Promise((res) => setTimeout(res, 2000)); // shared stack restarting
      continue;
    }
    const text = await r.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { json = text; }
    return { status: r.status, body: json };
  }
  throw new Error(`${method} ${path}: API unreachable`);
}

async function confirmationLink(email) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const msgs = await (await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent('to:' + email)}`)).json();
    for (const m of msgs.messages ?? []) {
      const body = await (await fetch(`${MAILPIT}/api/v1/message/${m.ID}`)).json();
      const link = `${body.Text ?? ''}${body.HTML ?? ''}`.match(/https?:\/\/[^\s"'<>]+\/verify\?[^\s"'<>]+/);
      if (link) return link[0].replaceAll('&amp;', '&');
    }
    await new Promise((res) => setTimeout(res, 1000));
  }
  throw new Error(`no confirmation email for ${email}`);
}

async function confirmEmail(email) {
  const r = await fetch(await confirmationLink(email), { redirect: 'manual' });
  return r.status;
}

async function passwordToken(email, password) {
  const r = await auth('token', { email, password }, { grant_type: 'password' });
  if (r.status !== 200) throw new Error(`sign-in failed for ${email}: ${r.status}`);
  return r.body.access_token;
}

/** Real GoTrue signup + Mailpit confirmation + provisioning (API side). */
async function apiAccount(email, password, name) {
  const s = await auth('signup', { email, password, data: { full_name: name } });
  if (s.status !== 200) throw new Error(`signup ${email}: ${s.status}`);
  await confirmEmail(email);
  const token = await passwordToken(email, password);
  const p = await api('POST', '/auth/provision', token, { full_name: name });
  if (p.status !== 201) throw new Error(`provision ${email}: ${p.status}`);
  return token;
}

// ------------------------------------------------------------------ UI helpers
const button = (page, name) => page.getByRole('button', { name }).first();
// Tappable cards (InkWell) may not carry the button role on the web: fall back to their text.
const tappable = (page, name) => page.getByRole('button', { name }).or(page.getByText(name, { exact: true })).first();
const field = (page, label) => page.getByRole('textbox', { name: label }).first();
// Flutter merges some text into a container's aria-label, so match either.
const text = (page, t) => page.getByText(t).or(page.getByLabel(t)).first();

/** A response promise that never becomes an unhandled rejection. */
function responseOf(page, predicate, timeout = 60_000) {
  const p = page.waitForResponse(predicate, { timeout });
  p.catch(() => {});
  return p;
}

async function visible(locator, timeout = 30_000) {
  await locator.waitFor({ state: 'visible', timeout });
  return true;
}

async function fill(page, label, value) {
  const f = field(page, label);
  await f.waitFor({ state: 'visible', timeout: 20_000 });
  await f.click();
  await f.fill(value);
  if ((await f.inputValue()) !== value) {
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.type(value);
  }
}

async function tap(page, locator) {
  await locator.waitFor({ state: 'visible', timeout: 30_000 });
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.click();
}

async function newPage(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log(`  [page error] ${e.message}`));
  currentPages.push(page);
  return page;
}

async function signIn(page, email, password) {
  await page.goto(`${WEB}/#/login`);
  await fill(page, 'Email', email);
  await fill(page, 'Password', password);
  await tap(page, button(page, 'Sign In'));
  await visible(text(page, /Kia ora/), 45_000);
}

async function askFirstMate(page, question) {
  const reply = responseOf(page, (r) => r.url().endsWith('/api/v1/ai/chat') && r.request().method() === 'POST');
  await fill(page, 'Ask your First Mate', question);
  await tap(page, button(page, 'Send'));
  const response = await reply;
  return { status: response.status(), body: await response.json() };
}

// ------------------------------------------------------------------ journey
async function main() {
  const { chromium } = await loadPlaywright();
  const args = process.env.HOST_MAP ? [`--host-resolver-rules=${process.env.HOST_MAP}`] : [];
  const browser = await chromium.launch({ headless: process.env.HEADED !== '1', args });
  const run = randomUUID().slice(0, 8);
  const pw = `Pw-${randomUUID()}`;
  const emailA = `e2e-skipper-${run}@example.test`;
  const emailB = `e2e-mate-${run}@example.test`;
  const emailC = `e2e-admin-${run}@example.test`;
  const cleanup = [];
  try {
    const ready = await (await fetch(`${API}/ready`)).json();
    step('stack ready', ready.ready === true);

    // 1. Confirmed signup through the UI.
    const page = await newPage(browser);
    await page.goto(`${WEB}/#/signup`);
    await fill(page, 'Full name', 'Journey Skipper');
    await fill(page, 'Email', emailA);
    await fill(page, 'Password', pw);
    await fill(page, 'Confirm password', pw);
    await tap(page, button(page, 'Create Account'));
    step('signup asks to confirm the email', await visible(button(page, 'Back to sign in')));
    const confirmed = await confirmEmail(emailA);
    step('confirmation link from Mailpit accepted', confirmed === 302 || confirmed === 303, String(confirmed));
    await tap(page, button(page, 'Back to sign in'));
    await fill(page, 'Email', emailA);
    await fill(page, 'Password', pw);
    await tap(page, button(page, 'Sign In'));
    step('signed in and provisioned', await visible(text(page, /Kia ora, Journey Skipper/), 45_000));
    const tokA = await passwordToken(emailA, pw);

    // 2. Add vessel Yamaha F150.
    await tap(page, button(page, 'Add Vessel'));
    await fill(page, 'Nickname *', 'Kahawai');
    await fill(page, 'Make *', 'Stabicraft');
    await fill(page, 'Model *', '2050 Supercab');
    await fill(page, 'Year *', '2021');
    await fill(page, 'Engine make', 'Yamaha');
    await fill(page, 'Engine model', 'F150');
    const created = responseOf(page, (r) => r.url().endsWith('/api/v1/vessels/') && r.request().method() === 'POST');
    await tap(page, button(page, 'Add vessel'));
    const vessel = await (await created).json();
    step('vessel Yamaha F150 added', vessel.engine_make === 'Yamaha' && vessel.engine_model === 'F150', vessel.id);

    // 3. Ask the First Mate.
    await tap(page, button(page, 'Ask First Mate'));
    const a1 = await askFirstMate(page, 'Which spark plug does my Yamaha F150 need?');
    step('First Mate answered (200)', a1.status === 200, a1.body.grounding?.status);
    await visible(text(page, 'Grounded in admitted sources'));
    await visible(text(page, 'Sources'));
    const source = a1.body.citations[0];
    step('answer rendered with a source', await visible(text(page, source.title)), source.title);
    await visible(text(page, 'Synthetic test source'));
    await visible(text(page, 'Local test assistant'));
    const plug = a1.body.products.find((p) => p.sku === 'SYN-PLUG-150');
    step('fitting product offered (server verified_fit)', plug?.fitment.status === 'verified_fit');
    step('product card shows it fits', await visible(text(page, plug.name)) && await visible(page.getByText(/Fits Kahawai/).first()));

    // 4. Explicit Add to cart.
    const before = await api('GET', '/cart/', tokA);
    step('cart untouched before tapping', before.body.item_count === 0);
    const added = responseOf(page, (r) => r.url().endsWith('/api/v1/cart/items') && r.request().method() === 'POST');
    await tap(page, page.getByRole('button', { name: /^Add to cart: .*Yamaha F150/ }).first());
    step('Add to cart called POST /cart/items', (await added).status() === 201);
    await visible(text(page, 'Added to cart'));
    const cart = await api('GET', '/cart/', tokA);
    step('cart contains the spark plug', cart.body.items.some((i) => i.product_id === plug.id), `${cart.body.item_count} item(s)`);

    // 5. Edit the engine to Suzuki DF140.
    await page.goto(`${WEB}/#/vessels/${vessel.id}/edit`);
    await fill(page, 'Engine make', 'Suzuki');
    await fill(page, 'Engine model', 'DF140');
    const saved = responseOf(page, (r) => r.url().endsWith(`/api/v1/vessels/${vessel.id}`) && r.request().method() === 'PATCH');
    await tap(page, button(page, 'Save changes'));
    const v2 = await (await saved).json();
    step('engine edited to Suzuki DF140', v2.engine_make === 'Suzuki' && v2.engine_model === 'DF140');

    // 6. Ask again: the F150 part is no longer offered as fitting.
    await tap(page, button(page, 'Ask First Mate'));
    await tap(page, button(page, 'New conversation'));
    const a2 = await askFirstMate(page, 'Which spark plug does my Yamaha F150 need?');
    const f150 = a2.body.products.find((p) => p.sku === 'SYN-PLUG-150');
    step('F150 plug not offered as fitting any more',
      (!f150 || !['verified_fit', 'universal'].includes(f150.fitment.status)) &&
        !a2.body.actions.some((x) => x.product_id === plug.id),
      f150 ? f150.fitment.status : 'not listed');
    await visible(text(page, a2.body.grounding.status === 'grounded' ? 'Grounded in admitted sources'
      : a2.body.grounding.status === 'conflicting' ? 'Sources disagree'
        : 'No verified source — the First Mate asked a clarifying question'));
    const f150Buttons = await page.getByRole('button', { name: /^Add to cart: .*Yamaha F150/ }).count();
    step('no Add to cart offered for the F150 plug in the UI', f150Buttons === 0, `answer: ${a2.body.grounding.status}`);
    if (f150) step('F150 plug shown as not fitting', await visible(page.getByText(/Does not fit/).first()));

    // 7. Earn points by paying an order (local TEST MODE payment via the API).
    const search = await api('GET', '/products/?search=SYN-OIL-150&limit=20', tokA);
    const oil = search.body.items.find((p) => p.sku === 'SYN-OIL-150');
    await api('POST', '/cart/items', tokA, { product_id: oil.id, quantity: 1 });
    const quote = await api('POST', '/shipping/quotes', tokA, { delivery_type: 'courier', destination: { postcode: '1010' } });
    const order = await api('POST', '/orders/checkout', tokA, {
      delivery_type: 'courier', quote_id: quote.body.id,
      shipping_address: { name: 'Journey Skipper', line1: '1 Quay St', city: 'Auckland', postcode: '1010', phone: '021 000 000' },
    }, { 'Idempotency-Key': `e2e-${run}` });
    const intent = await api('POST', `/payments/orders/${order.body.id}/intent`, tokA);
    const paid = await api('POST', `/payments/local/${intent.body.payment_intent_id}/confirm`, tokA, { outcome: 'succeed' });
    step('order paid through the TEST MODE flow', paid.body.order_status === 'paid', order.body.order_number);
    cleanup.push(['stock', plug.id, 1], ['stock', oil.id, 1]);
    const pts = await api('GET', '/loyalty/points', tokA);
    step('points earned on the paid order', pts.body.points_balance >= 100, `${pts.body.points_balance} CP`);

    // 8. Redeem a discount in the UI.
    await page.goto(`${WEB}/#/`);
    await tap(page, tappable(page, 'Crew Rewards'));
    await visible(text(page, `${pts.body.points_balance} CP`));
    await tap(page, page.getByRole('tab', { name: 'Redeem' }));
    await fill(page, 'Points to redeem', '100');
    const redeemed = responseOf(page, (r) => r.url().endsWith('/api/v1/loyalty/redeem/discount'));
    await tap(page, button(page, 'Redeem points'));
    const ent = await (await redeemed).json();
    step('discount redeemed in the UI', await visible(text(page, `Discount code ${ent.code}`)), `${ent.code} = $${(ent.amount_cents / 100).toFixed(2)}`);

    // 9. Create a crew and invite a second account.
    const tokB = await apiAccount(emailB, pw, 'Journey Mate');
    await tap(page, page.getByRole('tab', { name: 'Crew' }));
    await fill(page, 'Crew name', `Journey Crew ${run}`);
    await tap(page, button(page, 'Create crew'));
    step('crew created in the UI', await visible(text(page, 'You are the captain', 30_000)));
    await fill(page, 'Email address to invite', emailB);
    await tap(page, button(page, 'Send invite'));
    step('invite pending for the second account', await visible(text(page, emailB)));

    const pageB = await newPage(browser);
    await signIn(pageB, emailB, pw);
    await tap(pageB, tappable(pageB, 'Crew Rewards'));
    await tap(pageB, pageB.getByRole('tab', { name: 'Crew' }));
    await visible(text(pageB, `Join Journey Crew ${run}`));
    await tap(pageB, button(pageB, 'Accept invite'));
    step('second account accepted in its own browser context', await visible(text(pageB, 'You are a member')));
    const crewA = await api('GET', '/loyalty/crews/mine', tokA);
    step('captain sees two members', crewA.body.member_count === 2 && crewA.body.members.some((m) => m.display_name === 'Journey Mate'));
    void tokB;

    // 10. Admin verifies a fitment rule in the admin console.
    const tokC = await apiAccount(emailC, pw, 'Journey Admin');
    execFileSync(join(STACK_ROOT, 'scripts', 'local_stack.sh'), ['cli', 'grant-role', emailC, 'admin'], { cwd: STACK_ROOT, stdio: 'ignore' });
    const belt = (await api('GET', '/products/?search=SYN-BELT-UNI', tokC)).body.items.find((p) => p.sku === 'SYN-BELT-UNI');
    const rule = await api('POST', `/products/${belt.id}/fitment-rules`, tokC, {
      engine_make: 'Fixturesynth', engine_model: `E2E-${run}`, fitment_type: 'service_part',
      data_source: 'e2e_journey', confidence_score: 0.3, notes: 'E2E rule for a fictional engine',
    });
    step('unverified rule queued (fictional engine)', rule.status === 201 && rule.body.verification_status === 'unverified');
    cleanup.push(['rule', rule.body.id]);
    const pageC = await newPage(browser);
    await signIn(pageC, emailC, pw);
    await tap(pageC, tappable(pageC, 'Admin console'));
    await fill(pageC, 'Filter rules', `E2E-${run}`);
    await tap(pageC, button(pageC, 'Verify rule'));
    const verified = responseOf(pageC, (r) => r.url().includes(`/fitment-rules/${rule.body.id}/verify`));
    await tap(pageC, button(pageC, 'Confirm verification'));
    const vr = await verified;
    step('admin verified the rule in the console', vr.status() === 200 && (await vr.json()).verification_status === 'verified');
    const after = await api('GET', '/products/fitment-rules?verification_status=verified&limit=500', tokC);
    step('rule is verified on the server', after.body.some((r) => r.id === rule.body.id && r.confidence_score >= 0.7));

    // Cleanup (shared stack): remove the e2e rule, restore consumed stock.
    for (const c of cleanup) {
      if (c[0] === 'rule') await api('DELETE', `/products/fitment-rules/${c[1]}`, tokC);
      if (c[0] === 'stock') await api('POST', `/products/${c[1]}/stock`, tokC, { delta: c[2], reason: `e2e ${run}: restore` });
    }
  } catch (e) {
    console.log(`ERROR: ${e.message}`);
    for (const [i, p] of currentPages.entries()) {
      try {
        await p.screenshot({ path: join(OUT, `failure-${i}.png`), fullPage: true });
        writeFileSync(join(OUT, `failure-${i}.html`), await p.content());
        console.log(`  saved ${join(OUT, `failure-${i}.png`)} (${p.url()})`);
      } catch { /* page closed */ }
    }
    if (steps.every((s) => s.ok)) steps.push({ name: 'unexpected error', ok: false });
  } finally {
    await browser.close();
  }
  const passed = steps.filter((s) => s.ok).length;
  console.log(`\n${passed}/${steps.length} steps passed`);
  return steps.every((s) => s.ok) ? 0 : 1;
}

process.exit(await main());
