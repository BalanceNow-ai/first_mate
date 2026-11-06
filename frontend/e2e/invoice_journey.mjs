#!/usr/bin/env node
// "Understand my invoice" browser journey (node Playwright) against a release web build
// and the REAL local stack (scripts/local_stack.sh up). Nothing is mocked: accounts are
// real GoTrue signups confirmed through Mailpit, invoices are synthetic text-layer PDFs
// uploaded through the UI into private storage (intent → PUT → scan/process), and reading
// uses the stack's local_fixture extraction substitute.
//
//   owner uploads a standalone invoice in the UI → it is read into a draft → the owner
//   corrects the hard-to-read line → the server's recomputed sums show → the explanation
//   says "comparison unavailable" and sharing is unavailable → a job-linked invoice (job,
//   accepted assignment and accepted scope set up through the API) shows matches,
//   differences and "no approval record available" → the owner edits one suggested
//   question and sends it with a document → the contractor (second browser context)
//   replies with a corrected invoice → the owner sees the attributed reply → a moderator
//   resolves a reported review with a reason → an unrelated user cannot open the invoice.
//
// Usage:
//   node frontend/e2e/invoice_journey.mjs
// Environment (defaults in brackets):
//   WEB_URL     the stack's public URL the build was compiled against [http://localhost:18080]
//   BUILD_DIR   serve this release build for the app's own files (index.html, main.dart.js,
//               assets) instead of whatever the stack's web container serves; API, auth
//               and private-media paths still go to the stack   [frontend/build/web if present;
//               "none" to disable]
//   MAILPIT_URL Mailpit                                            [http://localhost:18025]
//   STACK_ROOT  checkout with .env + scripts/local_stack.sh        [repository root]
//   OUT_DIR     screenshots on failure                             [os tmpdir]
//   HEADED=1    show the browser
// Exit status 0 only if every step passes.
import { execFileSync } from 'node:child_process';
import { createHmac, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';
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

const WEB = (process.env.WEB_URL ?? 'http://localhost:18080').replace(/\/$/, '');
const API = WEB;
const MAILPIT = (process.env.MAILPIT_URL ?? 'http://localhost:18025').replace(/\/$/, '');
const STACK_ROOT = process.env.STACK_ROOT ?? repo;
const DEFAULT_BUILD = join(repo, 'frontend', 'build', 'web');
const BUILD = process.env.BUILD_DIR === 'none' ? null : (process.env.BUILD_DIR ?? (existsSync(DEFAULT_BUILD) ? DEFAULT_BUILD : null));
const OUT = process.env.OUT_DIR ?? join(tmpdir(), 'helm-invoice-e2e');
mkdirSync(OUT, { recursive: true });

const steps = [];
const pages = [];
function step(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) throw new Error(`step failed: ${name}`);
}

// ------------------------------------------------------------------ synthetic documents
function pdfEscape(s) {
  return s.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)');
}

/** A minimal valid one-page PDF with a Helvetica text layer: [text, x, y, size]. */
function makePdf(items) {
  const stream = items.map(([t, x, y, size]) => `BT /F1 ${size} Tf 1 0 0 1 ${x} ${y} Tm (${pdfEscape(t)}) Tj ET\n`).join('');
  const objs = [
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    '<< /Type /Pages /Kids [4 0 R] /Count 1 >>',
    `<< /Length ${Buffer.byteLength(stream, 'latin1')} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> >> /Contents 3 0 R >>',
    '<< /Type /Catalog /Pages 2 0 R >>',
  ];
  let out = '%PDF-1.4\n';
  const offsets = [];
  objs.forEach((o, i) => {
    offsets.push(Buffer.byteLength(out, 'latin1'));
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = Buffer.byteLength(out, 'latin1');
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) out += `${String(off).padStart(10, '0')} 00000 n \n`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 5 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

function invoicePdf(number, rows, footer, extra) {
  const items = [];
  let y = 800;
  for (const [label, value] of [['Supplier', 'Journey Harbour Marine'], ['Invoice No', number], ['Date', '2026-10-30'], ['Currency', 'NZD']]) {
    items.push([`${label}: ${value}`, 50, y, 10]);
    y -= 16;
  }
  y -= 14;
  const xs = [50, 230, 330, 370, 420, 500];
  ['Description', 'Part No', 'Qty', 'Unit', 'Unit Price', 'Amount'].forEach((c, i) => items.push([c, xs[i], y, 10]));
  y -= 16;
  for (const row of rows) {
    row.forEach((cell, i) => { if (cell) items.push([cell, xs[i], y, 10]); });
    y -= 16;
  }
  y -= 10;
  for (const [label, value] of footer) {
    items.push([`${label}: ${value}`, 330, y, 10]);
    y -= 16;
  }
  y -= 10;
  for (const line of extra) {
    items.push([line, 50, y, 9]);
    y -= 14;
  }
  return makePdf(items);
}

const ROWS = [
  ['Labour - replace hose and clamps', '', '2.5', 'hr', '95.00', '237.50'],
  ['Sanitation hose 25mm ID', 'SH-25', '1.5', 'm', '18.40', '27.60'],
  ['S/S hose clamp 316', 'HC-316-32', '[hw]3', 'ea', '6.50', '26.00'], // handwritten → low certainty
  ['Call-out fee', '', '1', '', '95.00', '95.00'],
  ['Consumables / sundries', '', '', '', '', '12.00'],
];
const FOOTER = [['Subtotal', '398.10'], ['GST', '59.72'], ['Total', '458.82']];
const EXTRA = ['Warranty: 12 months on parts supplied'];

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

async function must(promise, expect, what) {
  const r = await promise;
  if (r.status !== expect) throw new Error(`${what}: ${r.status} ${JSON.stringify(r.body).slice(0, 400)}`);
  return r.body;
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

async function passwordToken(email, password) {
  const r = await auth('token', { email, password }, { grant_type: 'password' });
  if (r.status !== 200) throw new Error(`sign-in failed for ${email}: ${r.status}`);
  return r.body.access_token;
}

/** Real GoTrue signup + Mailpit confirmation + provisioning (API side). */
async function apiAccount(email, password, name) {
  const s = await auth('signup', { email, password, data: { full_name: name } });
  if (s.status !== 200) throw new Error(`signup ${email}: ${s.status}`);
  await fetch(await confirmationLink(email), { redirect: 'manual' });
  const token = await passwordToken(email, password);
  await must(api('POST', '/auth/provision', token, { full_name: name }), 201, `provision ${email}`);
  return token;
}

function cli(...args) {
  return execFileSync(join(STACK_ROOT, 'scripts', 'local_stack.sh'), ['cli', ...args], { cwd: STACK_ROOT, stdio: ['ignore', 'pipe', 'ignore'] }).toString();
}

// ------------------------------------------------------------------ UI helpers
const button = (page, name) => page.getByRole('button', { name }).first();
const field = (page, label) => page.getByRole('textbox', { name: label }).first();
const text = (page, t) => page.getByText(t).or(page.getByLabel(t)).first();

function responseOf(page, predicate, timeout = 60_000) {
  const p = page.waitForResponse(predicate, { timeout });
  p.catch(() => {});
  return p;
}

const isCall = (method, re) => (r) => r.request().method() === method && re.test(new URL(r.url()).pathname);

async function visible(locator, timeout = 30_000) {
  await locator.waitFor({ state: 'visible', timeout });
  return true;
}

/** Visible after scrolling the page's list if needed. */
async function seen(page, locator, opts = {}) {
  return reveal(page, locator, typeof opts === 'number' ? { timeout: opts } : opts);
}

async function fill(page, label, value) {
  const f = field(page, label);
  await f.waitFor({ state: 'visible', timeout: 20_000 });
  for (let i = 0; i < 5; i++) {
    await f.click();
    await page.waitForTimeout(100);
    await f.fill(value);
    await page.waitForTimeout(150);
    if ((await f.inputValue().catch(() => '')) === value) return;
  }
  throw new Error(`could not fill "${label}"`);
}

/**
 * Flutter builds list items lazily, so off-screen widgets have no DOM node yet: scroll
 * the list under the pointer (right-hand pane by default) until [locator] appears.
 */
async function reveal(page, locator, { timeout = 30_000, x = 0.75 } = {}) {
  const deadline = Date.now() + timeout;
  const size = page.viewportSize();
  let direction = 1;
  let travelled = 0;
  while (Date.now() < deadline) {
    if (await locator.isVisible().catch(() => false)) {
      // Built, but maybe in the list's cache area outside the viewport: scroll it in.
      const box = await locator.boundingBox().catch(() => null);
      if (box && box.y >= 56 && box.y + box.height <= size.height) return true;
      if (box) {
        await page.mouse.move(size.width * x, size.height * 0.6);
        await page.mouse.wheel(0, box.y + box.height / 2 - size.height / 2);
        await page.waitForTimeout(250);
        continue;
      }
    }
    await page.mouse.move(size.width * x, size.height * 0.6);
    await page.mouse.wheel(0, 500 * direction);
    travelled += 500;
    if (travelled > 12_000) { direction = -direction; travelled = 0; }
    await page.waitForTimeout(250);
  }
  await locator.waitFor({ state: 'visible', timeout: 1000 });
  return true;
}

/**
 * Clicks at the element's position. Playwright's own scroll-into-view would scroll the
 * DOM semantics overlay, which Flutter turns into a list scroll that moves the target
 * again; [reveal] already brought it into the viewport with the mouse wheel.
 */
async function tap(page, locator, { timeout = 30_000 } = {}) {
  const deadline = Date.now() + timeout;
  for (;;) {
    await reveal(page, locator, { timeout: Math.max(1000, deadline - Date.now()) });
    const disabled = await locator.getAttribute('aria-disabled').catch(() => null);
    const box = await locator.boundingBox().catch(() => null);
    if (disabled !== 'true' && box) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      return;
    }
    if (Date.now() > deadline) throw new Error(`could not tap ${locator}`);
    await page.waitForTimeout(250);
  }
}

/**
 * Taps an action button and returns the API response it causes. A tap that lands while
 * the button is still disabled (e.g. during a recalculation) is retried; the actions
 * used with this are idempotent or version-checked on the server.
 */
async function press(page, locator, predicate, { attempts = 4, wait = 15_000 } = {}) {
  for (let i = 1; ; i++) {
    const response = page.waitForResponse(predicate, { timeout: wait });
    response.catch(() => {});
    await tap(page, locator);
    try {
      return await response;
    } catch (e) {
      if (i >= attempts) throw e;
      console.log(`  (no response to the tap on ${locator} yet — tapping again, attempt ${i + 1})`);
    }
  }
}

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
  '.css': 'text/css', '.png': 'image/png', '.ico': 'image/x-icon', '.svg': 'image/svg+xml', '.wasm': 'application/wasm',
  '.otf': 'font/otf', '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.bin': 'application/octet-stream', '.frag': 'text/plain',
};
const STACK_PATHS = /^\/(api|auth|helm-private|ready|health)(\/|$)/;

async function newPage(browser) {
  const context = await browser.newContext({ viewport: { width: 1400, height: 1000 }, serviceWorkers: 'block' });
  if (BUILD) {
    // Serve this worktree's release build for the app's own files; everything the app
    // calls (API, GoTrue, signed private-media URLs) still goes to the real stack.
    const origin = new URL(WEB).origin;
    await context.route((url) => url.origin === origin && !STACK_PATHS.test(url.pathname), async (route) => {
      const path = decodeURIComponent(new URL(route.request().url()).pathname);
      let file = join(BUILD, path === '/' ? 'index.html' : path);
      if (!file.startsWith(BUILD) || !existsSync(file) || statSync(file).isDirectory()) file = join(BUILD, 'index.html');
      await route.fulfill({
        status: 200,
        body: readFileSync(file),
        contentType: MIME[extname(file)] ?? 'application/octet-stream',
        headers: { 'cache-control': 'no-store' },
      });
    });
  }
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log(`  [page error] ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') console.log(`  [console] ${m.text().slice(0, 300)}`); });
  pages.push(page);
  return page;
}

async function signIn(page, email, password) {
  await page.goto(`${WEB}/#/login`);
  await fill(page, 'Email', email);
  await fill(page, 'Password', password);
  await tap(page, button(page, 'Sign In'));
  await seen(page, text(page, /Kia ora/), 45_000);
}

/** Choose [pdf] in the app's file chooser opened by [chooseButton]. */
async function chooseFile(page, chooseButton, name, pdf) {
  const chooser = page.waitForEvent('filechooser', { timeout: 30_000 });
  await tap(page, chooseButton);
  await (await chooser).setFiles({ name, mimeType: 'application/pdf', buffer: pdf });
}

/** Upload [pdf] through /invoices/new and return the created invoice (UI). */
async function uploadInvoice(page, { jobId, name, pdf, title }) {
  await page.goto(`${WEB}/#/invoices/new${jobId ? `?job_id=${jobId}` : ''}`);
  await seen(page, text(page, jobId ? 'Linked to your service job' : 'Not linked to a service job'));
  await fill(page, 'Name for this invoice', title);
  await chooseFile(page, button(page, 'Choose a PDF or photo'), name, pdf);
  await seen(page, text(page, name));
  const put = responseOf(page, isCall('PUT', /\/service-assets\/[^/]+\/content$/));
  const created = responseOf(page, isCall('POST', /\/api\/v1\/invoices$/));
  await tap(page, button(page, 'Upload and read'));
  const putStatus = (await put).status();
  const invoice = await (await created).json();
  return { invoice, putStatus };
}

async function waitRead(token, invoiceId) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const d = await must(api('GET', `/invoices/${invoiceId}`, token), 200, 'invoice');
    if (d.revision.extraction_status !== 'none') return d;
    await new Promise((res) => setTimeout(res, 1000));
  }
  throw new Error('invoice was never read');
}

// ------------------------------------------------------------------ journey
async function main() {
  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch({ headless: process.env.HEADED !== '1' });
  const run = randomUUID().slice(0, 8);
  const pw = `Pw-${randomUUID()}`;
  const email = (k) => `e2e-inv-${k}-${run}@example.test`;
  try {
    const ready = await (await fetch(`${API}/ready`)).json();
    step('stack ready', ready.ready === true, BUILD ? `serving build ${BUILD}` : 'stack web build');

    // Accounts (real GoTrue + Mailpit), moderator role and contractor organization (audited CLI).
    const tokOwner = await apiAccount(email('owner'), pw, 'Journey Owner');
    const tokTech = await apiAccount(email('tech'), pw, 'Journey Technician');
    const tokMod = await apiAccount(email('moderator'), pw, 'Journey Moderator');
    await apiAccount(email('outsider'), pw, 'Journey Outsider');
    cli('grant-role', email('moderator'), 'moderator');
    const orgId = cli('create-contractor-org', `Journey Harbour Marine ${run}`).trim().split('\n').pop().split('\t')[0];
    cli('add-contractor-member', orgId, email('tech'), '--role', 'admin');
    const techMe = await must(api('GET', '/auth/me', tokTech), 200, 'tech me');
    step('accounts, moderator role and contractor organization ready', /^[0-9a-f-]{36}$/.test(orgId), run);

    // 1. Standalone invoice uploaded through the UI.
    const owner = await newPage(browser);
    await signIn(owner, email('owner'), pw);
    const s = await uploadInvoice(owner, {
      name: 'harbour-invoice.pdf', title: 'Harbour invoice', pdf: invoicePdf(`J-${run}-S`, ROWS, FOOTER, EXTRA),
    });
    step('standalone PDF uploaded through the UI (intent → PUT → available → invoice)',
      s.putStatus === 202 && s.invoice.standalone === true, s.invoice.id);
    const sid = s.invoice.id;
    await seen(owner, text(owner, 'Read into a draft'), 60_000);
    const read = await waitRead(tokOwner, sid);
    step('read into a draft by the extraction substitute',
      read.revision.extraction_status === 'extracted' && read.lines.length === 5 && read.extraction.provider === 'local_fixture',
      `${read.lines.length} lines, needs confirmation: ${read.needs_confirmation.length}`);
    const clamp = read.lines.find((l) => l.description === 'S/S hose clamp 316');
    step('the handwritten quantity is low certainty and needs confirmation',
      clamp.certainty === 'low' && read.needs_confirmation.includes(`line:${clamp.id}`) &&
        await seen(owner, text(owner, '1 value was hard to read')));

    // 2. Correct the low-certainty line in the side-by-side review.
    await tap(owner, button(owner, 'Check and correct the details'));
    await seen(owner, text(owner, 'Invoice document (PDF · 1 page)'));
    step('review shows the document beside the values', await seen(owner, text(owner, 'Needs your confirmation')));
    await tap(owner, button(owner, 'Edit line 3'));
    await fill(owner, 'Quantity', '4');
    const patched = responseOf(owner, isCall('PATCH', new RegExp(`/invoices/${sid}/lines/${clamp.id}$`)));
    const explained = responseOf(owner, isCall('POST', new RegExp(`/invoices/${sid}/explain$`)));
    await tap(owner, button(owner, 'Save line'));
    const pr = await patched;
    const corrected = await pr.json();
    const line3 = corrected.lines.find((l) => l.id === clamp.id);
    step('owner corrected the quantity (extracted value kept)',
      pr.status() === 200 && line3.quantity === '4' && line3.extracted_values.quantity === '3' && line3.source === 'owner_corrected');
    const exp = await (await explained).json();
    const chk = exp.content.lines.find((l) => l.line_id === clamp.id).arithmetic;
    step('server recomputed the line deterministically', chk.status === 'matches' && chk.computed === '26.00', `4 × 6.50 = ${chk.computed}`);
    step('recomputed sums shown in the UI',
      await seen(owner, text(owner, /4 × NZD 6\.50 = NZD 26\.00/)) &&
        await seen(owner, text(owner, 'Lines add up to: NZD 398.10')) &&
        await seen(owner, text(owner, /Total: printed NZD 458\.82, calculated NZD 457\.82\. Does not add up, difference NZD 1\.00/)));
    const recalculated = responseOf(owner, async (r) => isCall('POST', new RegExp(`/invoices/${sid}/explain$`))(r) &&
      (await r.json().catch(() => ({}))).content?.provisional === false);
    const reviewed = await press(owner, button(owner, 'Mark as reviewed'), isCall('POST', new RegExp(`/invoices/${sid}/review$`)));
    step('marked as reviewed', reviewed.status() === 200);
    await recalculated;

    // 3. Explanation: standalone → comparison unavailable, sharing unavailable.
    await tap(owner, button(owner, 'Back'));
    await seen(owner, text(owner, 'What each line is'), 45_000);
    step('explanation: comparison unavailable for a standalone invoice',
      await seen(owner, text(owner, 'Comparison unavailable')) &&
        await seen(owner, text(owner, /not linked to a service job, so there is no accepted scope/)));
    step('sharing is unavailable for a standalone invoice',
      await seen(owner, text(owner, 'Sharing isn’t available for this invoice')) &&
        (await owner.getByRole('button', { name: 'Send to the contractor…' }).count()) === 0);

    // 4. Job-linked invoice with an accepted scope (job set up through the API).
    const vessel = await must(api('POST', '/vessels/', tokOwner, {
      nickname: 'Kotare', make: 'Haines Hunter', model: 'SF600', year: 2018,
      engine_make: 'Yamaha', engine_model: 'F150', propulsion_type: 'outboard',
    }), 201, 'vessel');
    const job = await must(api('POST', '/service-jobs/', tokOwner, {
      vessel_id: vessel.id, title: 'Water under the sink when the pump runs', entry_point: 'vessel',
      issue_description: 'There is water under the galley sink whenever the freshwater pump runs.',
      affected_system: 'plumbing', affected_equipment: 'freshwater pump',
    }), 201, 'job');
    const assignment = await must(api('POST', `/service-jobs/${job.id}/assignments`, tokOwner,
      { organization_id: orgId, sections: ['summary', 'evidence', 'scope', 'invoices'] },
      { 'Idempotency-Key': `e2e-assign-${run}` }), 201, 'assignment');
    await must(api('POST', `/contractors/assignments/${assignment.id}/accept`, tokTech, { member_user_ids: [techMe.id] }), 200, 'accept');
    const scope = await must(api('POST', `/service-jobs/${job.id}/scopes`, tokTech, {
      summary: 'Replace the leaking sink hose and clamps', currency: 'NZD',
      estimate_lines: [
        { description: 'Labour - replace hose and clamps', kind: 'labour', quantity: '2.5', unit: 'hr', unit_price_minor: 9500, amount_minor: 23750 },
        { description: 'Sanitation hose 25mm ID', kind: 'parts', quantity: '1.5', unit: 'm', unit_price_minor: 1840, amount_minor: 2760 },
        { description: 'S/S hose clamp 316', kind: 'parts', quantity: '4', unit: 'ea', unit_price_minor: 650, amount_minor: 2600 },
        { description: 'Call-out fee', kind: 'call_out', quantity: '1', unit_price_minor: 8500, amount_minor: 8500 },
      ],
    }), 201, 'scope');
    await must(api('POST', `/service-jobs/${job.id}/scopes/${scope.id}/decision`, tokOwner,
      { decision: 'accepted', revision_digest: scope.content_digest }, { 'Idempotency-Key': `e2e-scope-${run}` }), 201, 'scope decision');
    step('job with an accepted assignment and an accepted scope (API)', true, job.id);

    const j = await uploadInvoice(owner, {
      jobId: job.id, name: 'job-invoice.pdf', title: 'Sink repair invoice', pdf: invoicePdf(`J-${run}-J`, ROWS, FOOTER, EXTRA),
    });
    const jid = j.invoice.id;
    step('job-linked invoice uploaded through the UI', j.invoice.standalone === false && j.invoice.job_id === job.id, jid);
    await seen(owner, text(owner, 'Read into a draft'), 60_000);
    const jread = await waitRead(tokOwner, jid);
    const jclamp = jread.lines.find((l) => l.description === 'S/S hose clamp 316');
    await tap(owner, button(owner, 'Check and correct the details'));
    const confirmed = responseOf(owner, isCall('PATCH', new RegExp(`/invoices/${jid}/lines/${jclamp.id}$`)));
    await tap(owner, button(owner, 'Confirm line 3 as printed'));
    step('owner confirmed the hard-to-read line as printed', (await confirmed).status() === 200);
    const jexplained = responseOf(owner, async (r) => isCall('POST', new RegExp(`/invoices/${jid}/explain$`))(r) &&
      (await r.json().catch(() => ({}))).content?.provisional === false, 90_000);
    const jreviewed = await press(owner, button(owner, 'Mark as reviewed'), isCall('POST', new RegExp(`/invoices/${jid}/review$`)));
    if (jreviewed.status() !== 200) throw new Error(`review: ${jreviewed.status()}`);
    const jexp = await (await jexplained).json();
    const items = Object.fromEntries(jexp.content.comparison.items.map((i) => [i.line_number, i.status]));
    step('comparison: matches, differences and additional work',
      items[1] === 'matches' && items[3] === 'differs' && items[4] === 'differs' && items[5] === 'not_in_accepted_scope',
      JSON.stringify(items));
    await tap(owner, button(owner, 'Back'));
    await seen(owner, text(owner, 'What each line is'), 45_000);
    step('UI shows matches / differences / “no approval record available”',
      await seen(owner, text(owner, 'Matches the accepted scope')) &&
        await seen(owner, text(owner, 'Differs from the accepted scope')) &&
        await seen(owner, text(owner, 'Additional — not in the accepted scope')) &&
        await seen(owner, text(owner, /No approval record available/)) &&
        await seen(owner, text(owner, 'Amount: invoice NZD 95.00 · accepted scope NZD 85.00')));

    // 5. Edit one suggested question and send it with the document (explicit).
    const suggestions = jexp.content.suggested_questions;
    const idx = suggestions.findIndex((q) => q.key.startsWith('scope:additional'));
    await tap(owner, button(owner, `Edit and save suggestion ${idx + 1}`));
    const edited = `${suggestions[idx].text} We didn't discuss sundries on the day.`;
    await fill(owner, 'Question', edited);
    const drafted = responseOf(owner, isCall('POST', new RegExp(`/invoices/${jid}/questions$`)));
    await tap(owner, button(owner, 'Save draft'));
    const draft = await (await drafted).json();
    step('owner edited the suggested question into a private draft', draft.status === 'draft' && draft.text === edited);
    const before = await must(api('GET', `/service-jobs/${job.id}/invoice-questions`, tokTech), 200, 'contractor list');
    step('nothing reaches the contractor before Send', before.length === 0);
    await tap(owner, button(owner, 'Send to the contractor…'));
    await tap(owner, owner.getByRole('checkbox', { name: /Revision 1 document/ }).first());
    const sent = responseOf(owner, isCall('POST', new RegExp(`/questions/${draft.id}/send$`)));
    await tap(owner, button(owner, /^Send$/));
    const sentBody = await (await sent).json();
    step('owner sent one question with the invoice document',
      sentBody.status === 'shared' && sentBody.shared_asset_ids.length === 1 && sentBody.shared_asset_ids[0] === j.invoice.revision.source_asset_id);

    // 6. Contractor replies with a corrected invoice in a second browser context.
    const tech = await newPage(browser);
    await signIn(tech, email('tech'), pw);
    await tech.goto(`${WEB}/#/contractor/jobs/${job.id}/invoice-questions`);
    await seen(tech, text(tech, edited), 45_000);
    step('contractor sees only the sent question and its document',
      await seen(tech, text(tech, 'Invoice document (PDF, 1 page)')) && await seen(tech, text(tech, 'Waiting for your reply')));
    await fill(tech, 'Your reply to the owner', 'The sundries were not agreed; a corrected invoice is attached.');
    await chooseFile(tech, button(tech, 'Attach a corrected invoice (optional)'), 'corrected-invoice.pdf',
      invoicePdf(`J-${run}-J2`, ROWS.slice(0, 4).map((r, i) => (i === 2 ? [r[0], r[1], '4', r[3], r[4], r[5]] : r)),
        [['Subtotal', '386.10'], ['GST', '57.92'], ['Total', '444.02']], ['Corrected invoice']));
    const replied = responseOf(tech, isCall('POST', /\/invoice-questions\/[^/]+\/respond$/), 90_000);
    await tap(tech, button(tech, 'Send reply'));
    const reply = await replied;
    const replyBody = await reply.json();
    step('contractor replied with a corrected invoice (new revision)',
      reply.status() === 201 && replyBody.status === 'answered' && replyBody.responses[0].corrected_revision_id !== null);

    // 7. Owner sees the attributed reply.
    await owner.mouse.wheel(0, -20_000);
    await tap(owner, button(owner, 'Refresh'));
    await seen(owner, text(owner, /Reply from the assigned contractor/), 45_000);
    step('owner sees the attributed reply and the corrected revision',
      await seen(owner, text(owner, 'The sundries were not agreed; a corrected invoice is attached.')) &&
        await seen(owner, text(owner, /Attached a corrected invoice — revision 2/)) &&
        await seen(owner, text(owner, 'A corrected invoice was attached')));
    const withReply = await must(api('GET', `/invoices/${jid}`, tokOwner), 200, 'invoice');
    step('the original revision is kept (superseded, not overwritten)',
      withReply.revisions.length === 2 && withReply.revisions[0].status === 'superseded' &&
        withReply.questions[0].responses[0].author_role === 'contractor');

    // 8. A reported review is resolved by a moderator with a reason.
    await must(api('POST', `/service-jobs/${job.id}/visits`, tokOwner,
      { kind: 'attended', occurred_at: new Date(Date.now() - 300_000).toISOString() }, { 'Idempotency-Key': `e2e-visit-${run}` }), 201, 'visit');
    for (const [tok, dir, ratings, narrative] of [
      [tokOwner, 'owner_to_contractor', { communication_clarity: 4 }, 'Clear explanation of the work.'],
      [tokTech, 'contractor_to_owner', { problem_description_accuracy: 2 }, 'Description was vague; gate code 4512# failed.'],
    ]) {
      const d = await must(api('PUT', `/service-jobs/${job.id}/feedback/${dir}`, tok, { ratings, narrative }), 200, 'feedback draft');
      await must(api('POST', `/service-jobs/${job.id}/feedback/${dir}/submit`, tok, { expected_version: d.mine.version },
        { 'Idempotency-Key': `e2e-fb-${dir}-${run}` }), 201, 'feedback submit');
    }
    const fb = await must(api('GET', `/service-jobs/${job.id}/feedback`, tokOwner), 200, 'feedback');
    await must(api('POST', `/service-feedback/${fb.theirs.id}/reports`, tokOwner, {
      category: 'personal_or_security_information', reason: 'The review includes my marina gate code.', restrict_content: true,
    }), 201, 'report');
    const cases = await must(api('GET', '/moderation/cases?status=active&limit=200', tokMod), 200, 'cases');
    const kase = cases.find((c) => c.feedback_id === fb.theirs.id);
    step('the report opened a moderation case', Boolean(kase), kase?.id);
    const mod = await newPage(browser);
    await signIn(mod, email('moderator'), pw);
    await mod.goto(`${WEB}/#/profile`);
    step('moderator sees the Moderation entry', await seen(mod, text(mod, 'Moderation')));
    await mod.goto(`${WEB}/#/moderation/cases/${kase.id}`);
    await seen(mod, text(mod, 'Reported review: Personal or security information'), 45_000);
    step('case shows the reported content and minimal job context',
      await seen(mod, text(mod, /Their reason: The review includes my marina gate code\./)) &&
        await seen(mod, text(mod, 'Water under the sink when the pump runs')));
    await tap(mod, mod.getByRole('button', { name: /^Disposition$/ }).or(mod.getByText('Disposition', { exact: true })).first());
    await tap(mod, mod.getByRole('menuitem', { name: 'Content removed (personal or security information)' })
      .or(mod.getByText('Content removed (personal or security information)')).last());
    await fill(mod, 'Reason (required)', 'The review contained a gate code; the rest of the review stands.');
    const acted = responseOf(mod, isCall('POST', new RegExp(`/moderation/cases/${kase.id}/actions$`)));
    await tap(mod, button(mod, 'Resolve case'));
    const actedRes = await acted;
    const resolved = await actedRes.json();
    step('moderator resolved the case with a disposition and a reason',
      actedRes.status() === 200 && resolved.status === 'resolved' &&
        resolved.disposition === 'content_removed_for_personal_information' &&
        resolved.actions.at(-1).reason === 'The review contained a gate code; the rest of the review stands.');
    step('audit trail shows the resolution', await seen(mod, text(mod, 'Resolved — Content removed (personal or security information)')));

    // 9. An unrelated user cannot open the invoice.
    const out = await newPage(browser);
    await signIn(out, email('outsider'), pw);
    const denied = responseOf(out, isCall('GET', new RegExp(`/invoices/${jid}$`)));
    await out.goto(`${WEB}/#/invoices/${jid}`);
    const deniedRes = await denied;
    step('an unrelated user gets 404 for the invoice', deniedRes.status() === 404 && await seen(out, text(out, 'Invoice not found')));
    const outTok = await passwordToken(email('outsider'), pw);
    const direct = await api('GET', `/invoices/${jid}`, outTok);
    const docs = await api('POST', `/service-assets/${j.invoice.revision.source_asset_id}/download-url`, outTok, { variant: 'derivative' });
    step('…and cannot fetch the invoice or its document through the API', direct.status === 404 && docs.status === 404);
  } catch (e) {
    console.log(`ERROR: ${e.message}`);
    for (const [i, p] of pages.entries()) {
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
