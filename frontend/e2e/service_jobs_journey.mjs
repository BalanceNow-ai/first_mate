#!/usr/bin/env node
// Service-jobs browser journey (node Playwright) against a release web build and the
// REAL local stack (scripts/local_stack.sh up). Nothing is mocked:
//
//   owner: confirmed signup (Mailpit link) → add vessel → "Get help with a problem" →
//   next suggested request → upload a synthetic photo through the file chooser (intent →
//   PUT → scan/decode) and see it processed → upload a synthetic PDF document (job_document)
//   and see it processed; a PDF with a JavaScript action is refused with a plain reason →
//   "I cannot safely get this" → record an owner measurement → invite a contractor
//   organisation (provisioned with the audited CLI) with chosen sections and live updates
//   left off (the default, explained), preview exactly, send → contractor admin (second
//   browser context) accepts and assigns themself and is told the owner hasn't published a
//   brief yet → owner previews and publishes the brief and downloads the printable brief →
//   contractor sees "Showing the brief published on <date>", reads it, downloads it and
//   requests one more view → owner answers → contractor confirms a measurement and proposes
//   a scope → owner accepts that exact revision → contractor records attendance and
//   completion → both submit blind feedback → reviews reveal → a third unrelated user gets
//   nothing. Printable briefs are fetched with the Authorization header (never a token in a
//   URL) and saved from a blob download.
//
// Usage:
//   node frontend/e2e/service_jobs_journey.mjs
// Environment (defaults in brackets):
//   WEB_URL      the served web build                      [http://localhost:18432]
//   API_URL      the stack's public URL for node-side calls [http://localhost:18080]
//   MAILPIT_URL  Mailpit                                   [http://localhost:18025]
//   STACK_ROOT   checkout with .env + scripts/local_stack.sh [repository root]
//   OUT_DIR      screenshots on failure                    [os tmpdir]
//   HEADED=1     show the browser
// Exit status 0 only if every step passes.
import { execFileSync } from 'node:child_process';
import { createHmac, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';

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

const WEB = (process.env.WEB_URL ?? 'http://localhost:18432').replace(/\/$/, '');
const API = (process.env.API_URL ?? 'http://localhost:18080').replace(/\/$/, '');
const MAILPIT = (process.env.MAILPIT_URL ?? 'http://localhost:18025').replace(/\/$/, '');
const STACK_ROOT = process.env.STACK_ROOT ?? repo;
const OUT = process.env.OUT_DIR ?? join(tmpdir(), 'helm-service-jobs-e2e');
mkdirSync(OUT, { recursive: true });

const steps = [];
const currentPages = [];
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
      await new Promise((res) => setTimeout(res, 2000));
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

function cli(...args) {
  return execFileSync(join(STACK_ROOT, 'scripts', 'local_stack.sh'), ['cli', ...args], { cwd: STACK_ROOT }).toString();
}

// ------------------------------------------------------------------ synthetic photo
function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
/** A small synthetic PNG (gradient + stripes): no real boat, no metadata. */
function syntheticPng(w = 320, h = 240) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 3 + 1)] = 0;
    for (let x = 0; x < w; x++) {
      const o = y * (w * 3 + 1) + 1 + x * 3;
      const stripe = ((x >> 3) + (y >> 3)) % 2 ? 200 : 40;
      raw[o] = (x * 255) / w; raw[o + 1] = stripe; raw[o + 2] = (y * 255) / h;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

/** A minimal one-page text PDF; `active` adds an /OpenAction JavaScript action (must be refused). */
function syntheticPdf(lines, active = false) {
  const esc = (t) => t.replace(/[\\()]/g, (c) => `\\${c}`);
  const stream = lines.map((t, i) => `BT /F1 11 Tf 1 0 0 1 50 ${780 - 18 * i} Tm (${esc(t)}) Tj ET\n`).join('');
  const objs = [
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Type /Pages /Kids [4 0 R] /Count 1 >>',
    `<< /Length ${Buffer.byteLength(stream, 'latin1')} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> >> /Contents 3 0 R >>',
    `<< /Type /Catalog /Pages 2 0 R${active ? ' /OpenAction 6 0 R' : ''} >>`,
  ];
  if (active) objs.push('<< /S /JavaScript /JS (app.alert\\(1\\)) >>');
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

// ------------------------------------------------------------------ UI helpers
const button = (page, name) => page.getByRole('button', { name }).first();
const lastButton = (page, name) => page.getByRole('button', { name }).last();
const field = (page, label) => page.getByRole('textbox', { name: label }).first();
const text = (page, t) => page.getByText(t).or(page.getByLabel(t)).first();
const dialog = (page) => page.getByRole('alertdialog').or(page.getByRole('dialog')).last();

function responseOf(page, predicate, timeout = 60_000) {
  const p = page.waitForResponse(predicate, { timeout });
  p.catch(() => {});
  return p;
}
const isCall = (method, re) => (r) => r.request().method() === method && re.test(new URL(r.url()).pathname);

/** Flutter builds list content lazily: scroll the page until [locator] exists. */
async function reveal(locator, timeout = 30_000) {
  const page = locator.page();
  const deadline = Date.now() + timeout;
  let down = true;
  let moves = 0;
  while (Date.now() < deadline) {
    if (await locator.isVisible().catch(() => false)) return;
    await page.mouse.move(700, 650);
    await page.mouse.wheel(0, down ? 500 : -500);
    await page.waitForTimeout(250);
    if (++moves % 16 === 0) down = !down;
  }
  await locator.waitFor({ state: 'visible', timeout: 1000 });
}

async function visible(locator, timeout = 30_000) {
  await reveal(locator, timeout);
  return true;
}

async function fill(page, label, value, scope) {
  const f = (scope ?? page).getByRole('textbox', { name: label }).first();
  await f.waitFor({ state: 'visible', timeout: 20_000 });
  for (let i = 0; i < 5; i++) {
    await f.click();
    await page.waitForTimeout(100);
    await f.fill(value);
    await page.waitForTimeout(150);
    if ((await f.inputValue().catch(() => '')) === value) break;
    if (i === 4) throw new Error(`could not fill "${label}"`);
  }
  if (/^(Make|Model) \*$/.test(label)) await page.keyboard.press('Escape');
}

async function tap(page, locator) {
  await reveal(locator);
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.click();
}

/** Opens a Flutter dropdown by its label and picks an option. */
async function choose(page, label, option) {
  await tap(page, page.getByRole('button', { name: new RegExp(label) }).first());
  await page.waitForTimeout(300);
  await tap(page, page.getByRole('menuitem', { name: option }).or(page.getByRole('option', { name: option }))
    .or(page.getByText(option, { exact: true })).last());
  await page.waitForTimeout(300);
}

async function newPage(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 1100 }, acceptDownloads: true });
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

async function openTab(page, base, tab) {
  await page.goto(`${WEB}/#${base}/${tab}`);
  await page.waitForTimeout(500);
}

/** Taps "Download printable brief" and checks: an authenticated fetch (header, no token in
 * the URL) of the export, then a browser download of the HTML from a blob URL. */
async function downloadBrief(page) {
  const exportReq = page.waitForRequest((r) => r.method() === 'GET' && /\/briefs\/[^/]+\/export$/.test(new URL(r.url()).pathname),
    { timeout: 30_000 });
  const exportResp = responseOf(page, isCall('GET', /\/briefs\/[^/]+\/export$/));
  const download = page.waitForEvent('download', { timeout: 30_000 });
  await tap(page, button(page, 'Download printable brief'));
  const req = await exportReq;
  const resp = await exportResp;
  const dl = await download;
  const path = await dl.path();
  const html = path ? readFileSync(path, 'utf8') : '';
  const url = new URL(req.url());
  return {
    ok: resp.status() === 200 && /^Bearer /.test(req.headers().authorization ?? '') && url.search === ''
      && !/token|access/i.test(url.href) && dl.url().startsWith('blob:') && /\.html$/.test(dl.suggestedFilename())
      && /<html/i.test(html),
    detail: `${dl.suggestedFilename()} ${html.length} bytes`,
  };
}

async function rateAll(page, n) {
  // Five dimensions, each with its own row of 1–5 / Not applicable chips; nothing pre-selected.
  // Each chip is named with its question, e.g. "Communication and clarity: 5, Excellent".
  const name = new RegExp(`: ${n}, `);
  const chips = page.getByRole('checkbox', { name }).or(page.getByRole('button', { name }));
  await chips.first().waitFor({ timeout: 30_000 });
  const count = await chips.count();
  for (let i = 0; i < count; i++) {
    await chips.nth(i).scrollIntoViewIfNeeded().catch(() => {});
    await chips.nth(i).click();
    await page.waitForTimeout(150);
  }
  return count;
}

// ------------------------------------------------------------------ journey
async function main() {
  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch({ headless: process.env.HEADED !== '1' });
  const run = randomUUID().slice(0, 8);
  const pw = `Pw-${randomUUID()}`;
  const emailOwner = `e2e-sj-owner-${run}@example.test`;
  const emailCon = `e2e-sj-contractor-${run}@example.test`;
  const emailOther = `e2e-sj-other-${run}@example.test`;
  const orgName = `Journey Marine ${run}`;
  try {
    const ready = await (await fetch(`${API}/ready`)).json();
    step('stack ready', ready.ready === true);

    // 1. Owner: confirmed signup and sign-in through the UI.
    const page = await newPage(browser);
    await page.goto(`${WEB}/#/signup`);
    await fill(page, 'Full name', 'Journey Owner');
    await fill(page, 'Email', emailOwner);
    await fill(page, 'Password', pw);
    await fill(page, 'Confirm password', pw);
    await tap(page, button(page, 'Create Account'));
    await visible(button(page, 'Back to sign in'));
    const confirmed = await confirmEmail(emailOwner);
    step('owner confirmed the email (Mailpit link)', confirmed === 302 || confirmed === 303, String(confirmed));
    await tap(page, button(page, 'Back to sign in'));
    await fill(page, 'Email', emailOwner);
    await fill(page, 'Password', pw);
    await tap(page, button(page, 'Sign In'));
    step('owner signed in', await visible(text(page, /Kia ora, Journey Owner/), 45_000));
    const tokOwner = await passwordToken(emailOwner, pw);

    // 2. Add a vessel.
    await tap(page, button(page, 'Add Vessel'));
    await fill(page, 'Nickname *', 'Kahawai');
    await fill(page, 'Make *', 'Stabicraft');
    await fill(page, 'Model *', '2050 Supercab');
    await fill(page, 'Year *', '2021');
    await fill(page, 'Engine make', 'Yamaha');
    await fill(page, 'Engine model', 'F150');
    const vCreated = responseOf(page, isCall('POST', /\/api\/v1\/vessels\/$/));
    await tap(page, button(page, 'Add vessel'));
    const vessel = await (await vCreated).json();
    step('vessel added', !!vessel.id, vessel.id);

    // 3. Start a job from the vessel.
    await page.goto(`${WEB}/#/vessels/${vessel.id}`);
    await tap(page, button(page, 'Get help with a problem'));
    await visible(text(page, /We will use the details saved for Kahawai/));
    await fill(page, 'Short title *', 'Water under the sink when the pump runs');
    await fill(page, 'What is happening?', 'Water collects under the galley sink whenever the freshwater pump runs.');
    await fill(page, 'Which equipment is affected?', 'Freshwater pump');
    const jCreated = responseOf(page, isCall('POST', /\/api\/v1\/service-jobs\/$/));
    await tap(page, button(page, 'Start service job'));
    const jr = await jCreated;
    const job = await jr.json();
    step('job started from the vessel (entry point vessel, vessel context reused)',
      jr.status() === 201 && job.vessel_id === vessel.id && job.entry_point === 'vessel' && job.vessel_context?.vessel?.make === 'Stabicraft',
      job.id);
    const base = `/service-jobs/${job.id}`;
    await visible(text(page, 'Carry on where you left off'));

    // 4. Next suggested request in the capture workspace.
    await openTab(page, base, 'capture');
    const next = (await api('GET', `/service-jobs/${job.id}/evidence-requests/next`, tokOwner)).body;
    const firstPrompt = next.request?.prompt ?? next.proposal?.prompt;
    step('capture shows the next suggested request with its reason',
      !!firstPrompt && await visible(text(page, firstPrompt)) && await visible(text(page, /Why this helps:/)), next.proposal?.category);

    // 5. Upload a synthetic photo through the real file chooser.
    const png = syntheticPng();
    const chooser = page.waitForEvent('filechooser', { timeout: 30_000 });
    const intentResp = responseOf(page, isCall('POST', /\/assets\/intents$/));
    const putResp = responseOf(page, isCall('PUT', /\/service-assets\/[^/]+\/content$/));
    await tap(page, button(page, 'Upload a file'));
    const fc = await chooser;
    await fc.setFiles({ name: 'overview.png', mimeType: 'image/png', buffer: png });
    const intent = await (await intentResp).json();
    const put = await putResp;
    step('upload intent tied to the request, bytes PUT to the server',
      intent.asset.evidence_request_id != null && put.status() === 202, `${png.length} bytes`);
    await visible(text(page, 'Photo added'), 60_000);
    const assets = await api('GET', `/service-jobs/${job.id}/assets`, tokOwner);
    const mine = assets.body.items.find((a) => a.id === intent.asset.id);
    step('photo processed and shown as Ready with quality hints',
      mine?.status === 'available' && await visible(text(page, 'Ready')) && await visible(text(page, 'Framing: not assessed')),
      `${mine?.width}×${mine?.height} ${mine?.detected_type}`);

    // 5b. A PDF document (job_document) through the document picker; active content is refused.
    for (const [name, pdf, expectOk] of [
      ['pump-service-record.pdf', syntheticPdf(['Freshwater pump service record', 'Outlet hose 25 mm ID']), true],
      ['pump-manual.pdf', syntheticPdf(['Pump manual'], true), false],
    ]) {
      const docChooser = page.waitForEvent('filechooser', { timeout: 30_000 });
      const docIntent = responseOf(page, isCall('POST', /\/assets\/intents$/));
      // The extra-upload row (the first such button belongs to the next suggested request).
      await tap(page, page.getByRole('button', { name: 'Upload a document (PDF)' }).nth(1));
      await (await docChooser).setFiles({ name, mimeType: 'application/pdf', buffer: pdf });
      const di = await (await docIntent).json();
      await visible(text(page, expectOk ? 'Document added' : /Document rejected: The PDF contains active content/), 60_000);
      const doc = (await api('GET', `/service-assets/${di.asset.id}`, tokOwner)).body;
      step(expectOk ? 'PDF document uploaded as job_document and processed'
        : 'PDF with a JavaScript action refused with a plain reason',
      di.asset.purpose === 'job_document' && (expectOk ? doc.status === 'available' && doc.pages === 1
        : doc.status === 'rejected' && doc.rejection_reason === 'active_pdf_content'), `${doc.status} ${doc.rejection_reason ?? ''}`);
    }

    // 6. "I cannot safely get this" on the next request.
    await page.reload();
    await page.waitForTimeout(1500);
    await visible(button(page, 'I cannot safely get this'));
    const gapResp = responseOf(page, isCall('POST', /\/evidence-requests\/[^/]+\/unavailable$/));
    await tap(page, button(page, 'I cannot safely get this'));
    await visible(text(page, 'That is fine — leave it'));
    await fill(page, 'Anything the contractor should know? (optional)', 'Behind the hot water cylinder');
    await tap(page, button(page, 'Record gap'));
    const gap = await (await gapResp).json();
    step('"cannot safely access" recorded as a visible gap', gap.status === 'unavailable' && gap.unavailable_reason === 'cannot_safely_access'
      && await visible(text(page, 'Gap recorded — the contractor will see it')));

    // 7. Owner measurement with an explicit dimension type and method.
    await openTab(page, base, 'measurements');
    await tap(page, button(page, 'Record a measurement'));
    await fill(page, 'What did you measure? *', 'Pump outlet hose');
    await choose(page, 'Which dimension', 'Hose outside diameter (OD)');
    await fill(page, 'Value as measured or written *', '32');
    await choose(page, 'How did you get it', 'Measured with a caliper');
    const mResp = responseOf(page, isCall('POST', /\/measurements$/));
    await tap(page, button(page, 'Save measurement'));
    const measurement = await (await mResp).json();
    step('owner measurement recorded (OD, caliper) with an "Owner measured" badge',
      measurement.dimension === 'hose_external_diameter' && measurement.state === 'owner_measured'
        && await visible(text(page, 'Owner measured')), `${measurement.value_text} ${measurement.unit}`);

    // 8. Provision a contractor organisation (audited CLI) and its admin.
    const tokCon = await apiAccount(emailCon, pw, 'Journey Technician');
    const orgId = cli('create-contractor-org', orgName).trim().split('\t')[0];
    cli('add-contractor-member', orgId, emailCon, '--role', 'admin');
    const memberships = await api('GET', '/contractors/me', tokCon);
    step('contractor organisation provisioned via CLI', memberships.body.some((m) => m.organization_id === orgId && m.role === 'admin'), orgId);

    // 9. Owner invites the organisation with chosen sections after previewing.
    await openTab(page, base, 'sharing');
    const dirResp = responseOf(page, (r) => r.url().includes('/contractors/directory') && r.url().includes('q='));
    await fill(page, 'Search organisations', orgName);
    await tap(page, button(page, 'Search'));
    await dirResp;
    await page.waitForTimeout(500);
    await tap(page, page.getByRole('radio', { name: orgName }).or(page.getByText(orgName, { exact: true })).first());
    const liveSwitch = page.getByRole('switch', { name: /Live updates/ }).or(page.getByRole('checkbox', { name: /Live updates/ })).first();
    step('live updates are off by default and explained', await visible(text(page, /as of the brief you publish/))
      && !(await liveSwitch.isChecked().catch(() => true)));
    const previewResp = responseOf(page, isCall('POST', /\/assignments\/preview$/));
    await tap(page, button(page, 'Preview what they will see'));
    const preview = await (await previewResp).json();
    step('sharing preview lists exactly the chosen sections', preview.organization.id === orgId
      && preview.withheld.includes('access_restricted') && await visible(text(page, /Preview: what Journey Marine/)),
      preview.sections.map((s) => s.section).join(','));
    step('the preview explains what live updates off means', preview.live_updates === false
      && await visible(text(page, /Live updates off: They will see the job/)));
    const inviteResp = responseOf(page, isCall('POST', /\/assignments$/));
    await tap(page, button(page, 'Send invitation'));
    const invite = await inviteResp;
    const assignment = await invite.json();
    step('invitation sent with an Idempotency-Key (live updates off)', invite.status() === 201
      && !!invite.request().headers()['idempotency-key'] && assignment.live_updates === false,
      assignment.sections.join(','));

    // 10. Contractor (second browser context): inbox → accept → assign themself.
    const pageC = await newPage(browser);
    await signIn(pageC, emailCon, pw);
    await pageC.goto(`${WEB}/#/contractor/inbox`);
    step('contractor inbox shows the invitation', await visible(text(pageC, 'Invitations to review'))
      && await visible(text(pageC, 'Water under the sink when the pump runs')));
    await tap(pageC, text(pageC, 'Water under the sink when the pump runs'));
    await tap(pageC, button(pageC, 'Accept and assign people'));
    await tap(pageC, dialog(pageC).getByRole('checkbox', { name: /Journey Technician/ }).or(dialog(pageC).getByText('Journey Technician')).first());
    const acceptResp = responseOf(pageC, isCall('POST', /\/contractors\/assignments\/[^/]+\/accept$/));
    await tap(pageC, dialog(pageC).getByRole('button', { name: 'Confirm', exact: true }));
    const accepted = await (await acceptResp).json();
    step('org admin accepted and assigned a member', accepted.status === 'accepted' && accepted.members.length === 1);
    const conBase = `/contractor/jobs/${job.id}`;
    await openTab(pageC, conBase, 'brief');
    const early = await api('GET', `/service-jobs/${job.id}`, tokCon);
    step('before a brief is published the contractor sees only the header, and is told why',
      early.body.snapshot_state === 'no_brief_published' && early.body.issue_description == null
        && await visible(text(pageC, /The owner hasn't published a brief yet\. Until they do/)));

    // 11. Owner: ready for review, then preview and publish the brief.
    await openTab(page, base, 'overview');
    const trResp = responseOf(page, isCall('POST', /\/transition$/));
    await tap(page, button(page, 'Start collecting evidence').or(button(page, 'Ready for contractor review')));
    await trResp;
    await page.waitForTimeout(800);
    const tr2 = responseOf(page, isCall('POST', /\/transition$/));
    if (await button(page, 'Ready for contractor review').isVisible().catch(() => false)) {
      await tap(page, button(page, 'Ready for contractor review'));
      await tr2;
    }
    await openTab(page, base, 'brief');
    const bpResp = responseOf(page, isCall('POST', /\/briefs\/preview$/));
    await tap(page, button(page, 'Preview the brief'));
    const briefPreview = await (await bpResp).json();
    await visible(text(page, `Preview — revision ${briefPreview.revision_number}`));
    const pubResp = responseOf(page, isCall('POST', /\/briefs\/[^/]+\/publish$/));
    await tap(page, button(page, 'Publish this revision'));
    await tap(page, dialog(page).getByRole('button', { name: 'Publish', exact: true }));
    const published = await (await pubResp).json();
    step('owner previewed and published the brief revision', published.status === 'published'
      && published.content_digest === briefPreview.content_digest, `revision ${published.revision_number}`);
    await page.reload();
    await page.waitForTimeout(1000);
    const ownerDl = await downloadBrief(page);
    step('owner downloaded the printable brief (authenticated fetch → blob download)', ownerDl.ok, ownerDl.detail);

    // 12. Contractor reads the brief and requests one more view.
    await openTab(pageC, conBase, 'brief');
    await pageC.reload();
    await pageC.waitForTimeout(1000);
    const snap = await api('GET', `/service-jobs/${job.id}`, tokCon);
    step('contractor sees "Showing the brief published on <date>" (live updates off)',
      snap.body.snapshot_state === 'brief' && snap.body.snapshot_brief_id === published.id
        && await visible(text(pageC, /Showing the brief published on/)));
    const conDl = await downloadBrief(pageC);
    step('contractor downloaded the printable brief (authenticated fetch → blob download)', conDl.ok, conDl.detail);
    step('contractor reads the published brief with gaps and limitations',
      await visible(text(pageC, /Brief — revision/)) && await visible(text(pageC, 'Gaps and open requests:')) && await visible(text(pageC, 'Limitations')));
    await tap(pageC, button(pageC, 'Request one more view'));
    await fill(pageC, 'What should the owner photograph?', 'Photograph the pump label without moving the pump');
    await fill(pageC, 'Why it helps', 'Confirms the pump model and outlet size');
    const ackResp = responseOf(pageC, isCall('POST', /\/acknowledgements$/));
    await tap(pageC, dialog(pageC).getByRole('button', { name: 'Send request', exact: true }));
    const ack = await (await ackResp).json();
    step('contractor requested one more view', ack.acknowledgement.kind === 'incomplete' && ack.evidence_request?.status === 'outstanding');

    // 13. Owner answers that request.
    await openTab(page, base, 'capture');
    await page.reload();
    const next2 = (await api('GET', `/service-jobs/${job.id}/evidence-requests/next`, tokOwner)).body;
    step('owner sees the contractor’s request as the next step', next2.request?.id === ack.evidence_request.id
      && await visible(text(page, 'Requested by your contractor')));
    await tap(page, button(page, 'Answer with a note'));
    await fill(page, 'Your answer', 'The label reads FW-PUMP 12V; I could not move the pump.');
    const ansResp = responseOf(page, isCall('POST', /\/evidence-requests\/[^/]+\/answer$/));
    await tap(page, dialog(page).getByRole('button', { name: 'Save answer', exact: true }));
    const ans = await (await ansResp).json();
    step('owner answered the contractor’s request', ans.id === ack.evidence_request.id && ans.status === 'answered');

    // 14. Contractor confirms the measurement.
    await openTab(pageC, conBase, 'measurements');
    await tap(pageC, button(pageC, 'Confirm measurement'));
    const confResp = responseOf(pageC, isCall('POST', /\/measurements\/[^/]+\/confirm$/));
    await tap(pageC, dialog(pageC).getByRole('button', { name: 'Confirm', exact: true }));
    const conf = await (await confResp).json();
    step('contractor confirmed the measurement', conf.state === 'contractor_confirmed' && await visible(text(pageC, 'Contractor confirmed')));

    // 15. Contractor proposes a scope with an estimate.
    await openTab(pageC, conBase, 'scope');
    await tap(pageC, button(pageC, 'Propose a scope'));
    await fill(pageC, 'Summary of the work *', 'Replace the pump outlet hose and both clamps');
    await fill(pageC, /Tasks \(one per line/, 'Replace outlet hose\nInspect far-end fitting?');
    await fill(pageC, 'Line 1 description', 'Labour');
    await fill(pageC, 'Qty', '1.5');
    await fill(pageC, 'Unit', 'hour');
    await fill(pageC, 'Unit price (NZD)', '95');
    const scResp = responseOf(pageC, isCall('POST', /\/scopes$/));
    await tap(pageC, dialog(pageC).getByRole('button', { name: 'Send to the owner', exact: true }));
    const scope = await (await scResp).json();
    step('contractor proposed a scope revision (integer minor units)', scope.status === 'proposed'
      && scope.estimate_total_minor === 14250 && scope.currency === 'NZD', `$${scope.estimate_total_minor / 100}`);

    // 16. Owner accepts that exact revision.
    await openTab(page, base, 'scope');
    await tap(page, button(page, `Accept revision ${scope.revision_number}`));
    const decResp = responseOf(page, isCall('POST', /\/scopes\/[^/]+\/decision$/));
    await tap(page, dialog(page).getByRole('button', { name: 'Accept this revision', exact: true }));
    const dr = await decResp;
    const decision = await dr.json();
    step('owner accepted exactly that revision (digest + Idempotency-Key)', decision.decision === 'accepted'
      && decision.scope_revision_id === scope.id && decision.revision_digest === scope.content_digest
      && !!dr.request().headers()['idempotency-key']);

    // 17. Contractor records attendance and completion.
    await openTab(pageC, conBase, 'visits');
    for (const kind of ['attended', 'completed']) {
      await tap(pageC, button(pageC, 'Record a visit'));
      await tap(pageC, dialog(pageC).getByRole('radio', { name: kind === 'attended' ? 'Contractor attended' : 'Work completed' })
        .or(dialog(pageC).getByText(kind === 'attended' ? 'Contractor attended' : 'Work completed', { exact: true })).first());
      const vResp = responseOf(pageC, isCall('POST', /\/visits$/));
      await tap(pageC, dialog(pageC).getByRole('button', { name: 'Record', exact: true }));
      const v = await (await vResp).json();
      step(`contractor recorded ${kind}`, v.event.kind === kind, v.job_status);
      await pageC.waitForTimeout(800);
    }

    // 18. Both submit blind feedback; reviews reveal.
    await openTab(page, base, 'feedback');
    const nOwner = await rateAll(page, 5);
    await tap(page, button(page, 'Submit review'));
    const fbResp = responseOf(page, isCall('POST', /\/feedback\/owner_to_contractor\/submit$/));
    await tap(page, dialog(page).getByRole('button', { name: 'Submit review', exact: true }));
    const fbOwner = await (await fbResp).json();
    step('owner submitted feedback (blind)', fbOwner.mine?.status === 'submitted' && fbOwner.theirs === null, `${nOwner} dimensions rated`);
    const blind = await api('GET', `/service-jobs/${job.id}/feedback`, tokCon);
    step('contractor cannot see the owner’s review before submitting', blind.body.theirs === null);

    await openTab(pageC, conBase, 'feedback');
    await rateAll(pageC, 4);
    await tap(pageC, button(pageC, 'Submit review'));
    const fbcResp = responseOf(pageC, isCall('POST', /\/feedback\/contractor_to_owner\/submit$/));
    await tap(pageC, dialog(pageC).getByRole('button', { name: 'Submit review', exact: true }));
    const fbCon = await (await fbcResp).json();
    step('contractor submitted feedback and both reviews revealed', fbCon.window?.revealed === true && fbCon.theirs?.direction === 'owner_to_contractor');
    await page.reload();
    step('owner sees the revealed review of them', await visible(text(page, 'Their review of you'), 30_000));

    // 19. A third, unrelated user gets nothing.
    const tokOther = await apiAccount(emailOther, pw, 'Journey Outsider');
    const other = await api('GET', `/service-jobs/${job.id}`, tokOther);
    const otherBrief = await api('GET', `/service-jobs/${job.id}/briefs`, tokOther);
    const otherInbox = await api('GET', '/contractors/me/jobs', tokOther);
    step('unrelated user gets 404 for the job and brief and an empty inbox', other.status === 404 && otherBrief.status === 404
      && otherInbox.body.assigned.length === 0 && otherInbox.body.invitations.length === 0);
    const pageX = await newPage(browser);
    await signIn(pageX, emailOther, pw);
    await pageX.goto(`${WEB}/#/contractor/jobs/${job.id}`);
    step('unrelated user sees "not shared" in the UI', await visible(text(pageX, 'Not found, or not shared with you')));
  } catch (e) {
    console.log(`ERROR: ${e.message}`);
    for (const [i, p] of currentPages.entries()) {
      try {
        await p.screenshot({ path: join(OUT, `failure-${i}.png`), fullPage: true });
        writeFileSync(join(OUT, `failure-${i}.aria.txt`), await p.locator('body').ariaSnapshot().catch(() => ''));
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
