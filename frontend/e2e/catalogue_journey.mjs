#!/usr/bin/env node
// Browser journey for the catalogue / vessel garage / checklist client against
// the REAL local stack (scripts/local_stack.sh up + seed) and a web build of
// this app served on :18431.
//
//   flutter build web --profile \
//     --dart-define=API_BASE_URL=http://localhost:18080/api/v1 \
//     --dart-define=SUPABASE_URL=http://localhost:18080 \
//     --dart-define=SUPABASE_ANON_KEY=<local anon key>
//   python3 -m http.server 18431 -d build/web
//
// (A --release build refuses loopback API/Supabase URLs by design — see
// AppConfig.problems() — so the local journey uses a --profile build.)
//   node e2e/catalogue_journey.mjs [--app http://localhost:18431] [--mailpit http://localhost:18025]
//
// Sign up (confirmed via Mailpit) → sign in → add a vessel with a HIN and a
// Yamaha F150 → compatible-only product list shows SYN-PLUG-150 as a fit →
// product detail → add to cart → vessel equipment add → checklist generate,
// tick, reload (persisted), add missing twice (second adds nothing) → export.
// Uses only role/label selectors on Flutter's semantics tree. Exit 0 = pass.
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const APP = arg('app', 'http://localhost:18431');
const MAILPIT = arg('mailpit', 'http://localhost:18025');
const HEADLESS = !process.argv.includes('--headed');
const SHOTS = arg('screenshots', '');

const TOTAL_STEPS = 12;
const results = [];
let page;

async function step(name, fn) {
  const started = Date.now();
  try {
    const detail = await fn();
    results.push([name, true]);
    console.log(`[PASS] ${name}${detail ? ` — ${detail}` : ''} (${Date.now() - started} ms)`);
  } catch (e) {
    results.push([name, false]);
    console.log(`[FAIL] ${name} — ${e.message.split('\n')[0]}`);
    if (page && SHOTS) {
      await page.screenshot({ path: `${SHOTS}/fail.png`, fullPage: true }).catch(() => {});
      const snapshot = await page.locator('body').ariaSnapshot().catch(() => '');
      require('fs').writeFileSync(`${SHOTS}/fail.aria.txt`, snapshot);
    }
    throw e;
  }
}

const button = (name, opts = {}) => page.getByRole('button', { name, exact: true, ...opts });
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// A field's accessible name is its label, followed by any hint/helper text.
const textbox = (label) => page.getByRole('textbox', { name: new RegExp(`^${escapeRe(label)}( |$)`) });
const text = (t, opts = {}) => page.getByText(t, { exact: true, ...opts });
// Flutter merges a widget's texts into its semantics node, which the browser
// exposes either as text or as an accessible name (aria-label): match either.
const see = (re, p = page) => p.getByText(re).or(p.getByLabel(re)).first();
const countAny = async (re) => (await page.getByText(re).count()) + (await page.getByLabel(re).count());

// Flutter moves its single DOM editing element to the focused field; a fill
// that lands before focus settles is lost, so retry until the value sticks.
async function fill(label, value) {
  const box = textbox(label);
  await box.waitFor();
  for (let i = 0; i < 5; i++) {
    await box.click();
    await page.waitForTimeout(100);
    await box.fill(value);
    await page.waitForTimeout(150);
    if ((await box.inputValue().catch(() => '')) === value) return;
  }
  throw new Error(`could not fill "${label}"`);
}

/// Waits for a matching response; never left as an unhandled rejection.
function responseFor(predicate) {
  const p = page.waitForResponse(predicate);
  p.catch(() => {});
  return p;
}

async function scrollUntilVisible(locator, { max = 25, dy = 500 } = {}) {
  for (let i = 0; i < max; i++) {
    if (await locator.first().isVisible().catch(() => false)) return;
    await page.mouse.move(640, 900);
    await page.mouse.wheel(0, dy);
    await page.waitForTimeout(350);
  }
  await locator.first().waitFor({ state: 'visible', timeout: 2000 });
}

async function confirmationLink(email) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const search = await (await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`)).json();
    for (const m of search.messages ?? []) {
      const body = await (await fetch(`${MAILPIT}/api/v1/message/${m.ID}`)).json();
      const match = `${body.Text ?? ''}${body.HTML ?? ''}`.match(/https?:\/\/[^\s"'<>]+\/verify\?[^\s"'<>]+/);
      if (match) return match[0].replaceAll('&amp;', '&');
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`no confirmation email for ${email}`);
}

const browser = await chromium.launch({ headless: HEADLESS });
const context = await browser.newContext({ viewport: { width: 1280, height: 1800 } });
page = await context.newPage();
page.on('pageerror', (e) => console.log(`  page error: ${e.message}`));

const run = Math.random().toString(16).slice(2, 10);
const email = `catalogue-journey-${run}@example.test`;
const password = `Pw-${run}-${Date.now()}`;
let vesselId;
let plugItemPatched;

try {
  await step('sign up (confirmation required)', async () => {
    await page.goto(`${APP}/#/signup`);
    await fill('Full name', 'Journey Skipper');
    await fill('Email', email);
    await fill('Password', password);
    await fill('Confirm password', password);
    await button('Create Account').click();
    await text('Check your email').waitFor({ timeout: 20000 });
    return email;
  });

  await step('confirm via the Mailpit link', async () => {
    const link = await confirmationLink(email);
    const r = await fetch(link, { redirect: 'manual' });
    if (![302, 303].includes(r.status)) throw new Error(`confirmation returned ${r.status}`);
    return `HTTP ${r.status}`;
  });

  await step('sign in (profile provisioned)', async () => {
    await button('Back to sign in').click();
    await fill('Email', email);
    await fill('Password', password);
    await button('Sign In').click();
    await text('Helm Marine').first().waitFor({ timeout: 20000 });
    await button('Add Vessel').waitFor({ timeout: 20000 });
  });

  await step('add vessel: HIN decoded as a suggestion, accepted explicitly', async () => {
    await page.goto(`${APP}/#/vessels/new`);
    await fill('Nickname *', 'Kahawai');
    await fill('HIN (hull identification number)', 'nz-z9x12345c121');
    await button('Decode HIN').click();
    await page
      .getByRole('group', { name: /^HIN decoded .*Manufacturer Synthetic Test Marine \(fixture\) .*Model year 2021/ })
      .waitFor({ timeout: 15000 });
    // Nothing applied until accepted:
    if ((await textbox('Make *').inputValue()) !== '') throw new Error('make was auto-filled');
    await button('Use make Synthetic Test Marine (fixture)').click();
    await button('Use year 2021').click();
    await button('Use NZ-Z9X12345C121').click();
    await fill('Model *', 'Fixture 600 Runabout');
    await page.keyboard.press('Escape');
    await fill('Engine make', 'Yamaha');
    await fill('Engine model', 'F150');
    await fill('Engine year', '2021');
    const created = responseFor((r) => r.url().endsWith('/api/v1/vessels/') && r.request().method() === 'POST');
    await button('Add vessel').click();
    const vessel = await (await created).json();
    vesselId = vessel.id;
    if (vessel.make !== 'Synthetic Test Marine (fixture)' || vessel.year !== 2021) throw new Error('accepted values not saved');
    await page.waitForURL(new RegExp(`#/vessels/${vesselId}$`), { timeout: 15000 });
    return `model_year_id=${vessel.model_year_id ?? 'none'}, hin_status=${vessel.hin_status}`;
  });

  await step('compatible-only product list shows SYN-PLUG-150 as a verified fit', async () => {
    await page.goto(`${APP}/#/products`);
    const compatible = responseFor((r) => r.url().includes('/api/v1/products/?') && r.url().includes('compatible_only=true'));
    await see(/^Compatible with Kahawai only/).click();
    const body = await (await compatible).json();
    const plug = body.items.find((p) => p.sku === 'SYN-PLUG-150');
    if (!plug || plug.fitment.status !== 'verified_fit') throw new Error('SYN-PLUG-150 not a verified fit');
    if (!body.items.every((p) => ['verified_fit', 'universal'].includes(p.fitment.status))) throw new Error('non-fit in compatible list');
    await see(/^Compatible with Kahawai \(2021 .*showing only parts verified to fit/).waitFor();
    const card = page.getByRole('button', { name: /Spark plug set — Yamaha F150 \(synthetic\) Fits Kahawai\./ });
    await scrollUntilVisible(card);
    if (await countAny(/Does not fit/)) throw new Error('"Does not fit" shown in compatible list');
    if (await countAny(/Fit unknown/)) throw new Error('unknown fit shown in compatible list');
    return `${body.total} compatible items`;
  });

  await step('product detail: fitment, known-to-fit, add to cart', async () => {
    await page.getByRole('button', { name: /Spark plug set — Yamaha F150 \(synthetic\) Fits/ }).click();
    await page.getByRole('heading', { name: 'Known to fit' }).waitFor({ timeout: 15000 });
    await see(/Yamaha F150 engines/).waitFor();
    await see(/^Fits Kahawai\. Fits Kahawai/).waitFor();
    await see(/OEM part number SYN-PLUG-150/).waitFor();
    const added = responseFor((r) => r.url().endsWith('/api/v1/cart/items') && r.request().method() === 'POST');
    await button('Add to cart').click();
    const cart = await (await added).json();
    await see(/^Added 1 × Spark plug set/).waitFor();
    return `cart item_count=${cart.item_count}`;
  });

  await step('vessel detail: add owner equipment', async () => {
    await page.goto(`${APP}/#/vessels/${vesselId}`);
    await page.getByRole('tab', { name: 'Equipment' }).click();
    await page.getByRole('heading', { name: 'Installed equipment' }).waitFor({ timeout: 15000 });
    await button('Add equipment').click();
    await page.getByRole('button', { name: /Category \*/ }).click();
    await page.getByRole('menuitem', { name: 'Chartplotter / GPS' }).or(text('Chartplotter / GPS').last()).first().click();
    await fill('Make *', 'Garmin');
    await fill('Model', 'echoMAP UHD 93sv');
    const posted = responseFor((r) => r.url().endsWith(`/vessels/${vesselId}/equipment`) && r.request().method() === 'POST');
    await button('Add').click();
    const item = await (await posted).json();
    await see(/Garmin echoMAP UHD 93sv/).waitFor({ timeout: 15000 });
    await see(/Owner declared/).waitFor();
    return `${item.provenance}/${item.reliability}`;
  });

  await step('checklists: generate with the disclaimer', async () => {
    await page.goto(`${APP}/#/vessels/${vesselId}/checklists`);
    await button('Generate checklists').click();
    await page.getByRole('tab', { name: /^Day trips: 0 of \d+ on board/ }).waitFor({ timeout: 20000 });
    await see(/NOT a certified safety-equipment list/).waitFor();
  });

  await step('tick an item; it persists across a reload', async () => {
    const box = page.getByRole('checkbox', { name: 'On board: Spare spark plugs' });
    await box.waitFor();
    const patched = responseFor((r) => r.url().includes('/api/v1/checklists/items/') && r.request().method() === 'PATCH');
    await box.click();
    plugItemPatched = await (await patched).json();
    if (!plugItemPatched.is_checked) throw new Error('server did not record the tick');
    await page.reload();
    const reloaded = page.getByRole('checkbox', { name: 'On board: Spare spark plugs' });
    await reloaded.waitFor({ timeout: 30000 });
    if (!(await reloaded.isChecked())) throw new Error('tick not persisted');
    await page.getByRole('tab', { name: /^Day trips: 1 of \d+ on board/ }).waitFor();
  });

  await step('add missing to cart twice: the second adds nothing', async () => {
    let r = responseFor((x) => x.url().endsWith('/add-missing-to-cart'));
    await button('Add missing to cart').click();
    const first = await (await r).json();
    await see(/^Added \d+ items? to your cart/).waitFor();
    await button('Close').click();
    r = responseFor((x) => x.url().endsWith('/add-missing-to-cart'));
    await button('Add missing to cart').click();
    const second = await (await r).json();
    await see(/^Nothing new added — your cart already covers these/).waitFor();
    await button('Close').click();
    if (first.added_count < 1 || second.added_count !== 0) throw new Error(`added ${first.added_count} then ${second.added_count}`);
    return `first added ${first.added_count}, second added ${second.added_count}`;
  });

  await step('printable export opens in a new tab (fetched with the token)', async () => {
    const popup = context.waitForEvent('page');
    const exported = responseFor((x) => x.url().includes('/export?') && x.url().includes('format=html'));
    await button('Printable checklist').click();
    const resp = await exported;
    if (resp.status() !== 200) throw new Error(`export ${resp.status()}`);
    const tab = await popup;
    await tab.waitForFunction(() => location.href.startsWith('blob:') && document.body?.innerText.includes('NOT a certified'), null, { timeout: 15000 });
    const title = await tab.title();
    await tab.close();
    return `tab "${title}"`;
  });

  await step('CSV export downloads', async () => {
    const download = page.waitForEvent('download');
    download.catch(() => {});
    await button('Download CSV').click();
    const file = await download;
    const path = await file.path();
    const csv = require('fs').readFileSync(path, 'utf8');
    if (!csv.includes('NOT a certified')) throw new Error('disclaimer missing from CSV');
    return file.suggestedFilename();
  });
} catch {
  // Reported by step().
} finally {
  await browser.close();
  const passed = results.filter(([, ok]) => ok).length;
  console.log(`\n${passed}/${results.length} steps passed`);
  process.exit(passed === results.length && results.length === TOTAL_STEPS ? 0 : 1);
}
