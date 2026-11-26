const assert = require('node:assert/strict');
const { once } = require('node:events');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const output = path.resolve(__dirname, '..');
const previews = process.env.MGTS_PREVIEW_DIR;
const base = 'http://127.0.0.1:' + (process.env.MGTS_PORT || '18086');
const fps = 30;
const initialCursor = { x: 1350, y: 135 };
const overviewPath = '/?month=6';
const detailPath = '/interns/DEMO-2?month=6';
const ease = t => t * t * (3 - 2 * t);
const phase = (time, start, end) => ease(Math.min(1, Math.max(0, (time - start) / (end - start))));
const mix = (a, b, p) => a + (b - a) * p;
const move = (a, b, p) => ({ x: mix(a.x, b.x, p), y: mix(a.y, b.y, p) });

async function overlay(page) {
  await page.evaluate(() => {
    // Capture-only graphics. The app's HTML, CSS, and data stay intact.
    const layer = document.createElement('div');
    layer.id = 'capture-overlay';
    layer.setAttribute('aria-hidden', 'true');
    layer.style.cssText = 'all:initial;pointer-events:none;position:fixed;inset:0;z-index:2147483647';
    const shadow = layer.attachShadow({ mode: 'open' });
    shadow.innerHTML = `
      <style>
        .caption { position:absolute;bottom:22px;left:50%;transform:translateX(-50%);
          display:flex;align-items:center;gap:17px;box-sizing:border-box;padding:11px 21px;
          border-radius:10px;background:#102b4b;color:#fff;white-space:nowrap;
          font:600 22px/1.3 system-ui,sans-serif;box-shadow:0 3px 14px #102b4b2d; }
        .section { color:#9bddff;font-size:14px;font-weight:750;letter-spacing:.04em;
          padding-right:16px;border-right:1px solid #ffffff42; }
        svg { position:absolute;left:0;top:0;overflow:visible;
          filter:drop-shadow(0 1px 2px #102b4b55); }
      </style>
      <div class="caption"><span class="section"></span><span class="text"></span></div>
      <svg width="24" height="29" viewBox="0 0 24 29">
        <path d="M2 1.8v22.1l5.8-5.5 4 8.6 3.5-1.7-4-8.5h8.1z"
          fill="#142b44" stroke="#fff" stroke-width="1.7" stroke-linejoin="round"/>
      </svg>`;
    document.body.append(layer);
  });
}

async function open(page, route) {
  const response = await page.goto(base + route, { waitUntil: 'load' });
  assert.equal(response.status(), 200);
  await page.evaluate(() => document.fonts.ready);
  assert.match(await page.locator('main').innerText(), /Демонстрационный режим/);
  await overlay(page);
}

async function paint(page, scroll, cursor, section, caption) {
  await page.mouse.move(cursor.x, cursor.y);
  await page.evaluate(({ scroll, cursor, section, caption }) => {
    window.scrollTo(0, scroll);
    const layer = document.querySelector('#capture-overlay').shadowRoot;
    layer.querySelector('svg').style.transform = `translate(${cursor.x}px,${cursor.y}px)`;
    layer.querySelector('.section').textContent = section;
    layer.querySelector('.text').textContent = caption;
  }, { scroll, cursor, section, caption });
}

async function measure(locator) {
  const box = await locator.boundingBox();
  assert.ok(box);
  return box;
}

async function encode(page, file, length, scene) {
  const target = path.join(output, file + '.mp4');
  const encoder = spawn(process.env.FFMPEG || 'ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', 'pipe:0',
    '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '15', '-pix_fmt', 'yuv420p',
    '-profile:v', 'high', '-level:v', '4.1', '-movflags', '+faststart', target,
  ], { stdio: ['pipe', 'ignore', 'inherit'] });
  const done = once(encoder, 'exit');
  const frameCount = length * fps;
  try {
    let frame;
    let previous;
    for (let index = 0; index < frameCount; index += 1) {
      const signature = JSON.stringify(await scene(index / fps));
      if (signature !== previous) {
        frame = await page.screenshot();
        previous = signature;
      }
      if (!encoder.stdin.write(frame)) await once(encoder.stdin, 'drain');
    }
    encoder.stdin.end();
    const [code] = await done;
    assert.equal(code, 0);
    process.stdout.write(`${file}.mp4: ${length} s / ${frameCount} frames\n`);
  } catch (error) {
    encoder.kill();
    throw error;
  }
}

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    headless: true,
    args: ['--hide-scrollbars'],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 1.2,
      locale: 'ru-RU',
      reducedMotion: 'reduce',
    });
    await context.route('**/*', route => {
      return route.request().url().startsWith(base + '/') ? route.continue() : route.abort();
    });
    const page = await context.newPage();
    const browserErrors = [];
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('response', response => {
      if (response.status() >= 400) browserErrors.push(`${response.status()} ${response.url()}`);
    });
    const health = await context.request.get(base + '/health');
    assert.equal(health.status(), 200);
    assert.deepEqual(await health.json(), { status: 'ok' });

    await open(page, overviewPath);
    assert.deepEqual(await page.locator('.stats strong').allTextContents(), ['5/5', '4/5', '59']);
    const internLink = page.getByRole('link', { name: 'DEMO-2', exact: true });
    assert.match(await internLink.locator('../..').innerText(), /Критич|критич/);
    const signals = await measure(page.locator('.panel').nth(0));
    const trends = await measure(page.locator('.panel').nth(1));
    const link = await measure(internLink);
    await open(page, detailPath);
    const periods = await measure(page.locator('.panel').first());
    const six = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Месяц 6' }) });
    assert.equal(await six.count(), 1);
    assert.match(await six.innerText(), /неясны критерии готовности задачи/);
    const evidence = await measure(page.locator('main .panel').last());
    const summary = await measure(six.locator('summary'));
    const comments = await measure(six.locator('blockquote', { hasText: 'неясны критерии' }));
    console.log({ signals, trends, link, periods, evidence, summary, comments });

    if (previews) {
      await fs.mkdir(previews, { recursive: true });
      await paint(page, 0, initialCursor, 'КАРТОЧКА СТАЖЁРА', 'Стажёр и наставник видят ситуацию по-разному');
      await page.screenshot({ path: path.join(previews, 'card.png') });
      await paint(page, evidence.y - 25, initialCursor, 'ОСНОВАНИЕ СИГНАЛА', 'В анкетах видны оценки и комментарий стажёра');
      await page.screenshot({ path: path.join(previews, 'evidence.png') });
      await open(page, overviewPath);
      await paint(page, 0, initialCursor, 'ОБЗОР ПРОГРАММЫ', 'HR видит, от кого получены анкеты');
      await page.screenshot({ path: path.join(previews, 'overview.png') });
      assert.deepEqual(browserErrors, []);
      return;
    }

    // The three sequences below use the real app and native link, mouse and disclosure actions.
    await recordScenes({ page, internLink, six, link, periods, evidence });
    assert.deepEqual(browserErrors, []);
  } finally {
    await browser.close();
  }
}

async function recordScenes({ page, internLink, six, link, periods, evidence }) {
  const side = 1375;
  const overviewCursor = { x: side, y: 270 };
  const signalCursor = { x: side, y: 558 };
  const trendCursor = { x: side, y: 680 };
  await open(page, overviewPath);
  await encode(page, '01-overview', 10, async time => {
    const scroll = mix(0, 78, phase(time, 2.8, 4.1)) + mix(0, 283, phase(time, 6.0, 7.7));
    const cursor = time < 5.9
      ? move(overviewCursor, signalCursor, phase(time, 1.2, 3.9))
      : move(signalCursor, trendCursor, phase(time, 6.0, 7.7));
    const text = time < 3.2 ? 'Охват анкет за шестой месяц'
      : time < 6.5 ? 'В списке HR видит, кому требуется внимание'
        : 'Ниже — динамика средних оценок за полгода';
    await paint(page, scroll, cursor, 'ОБЗОР ПРОГРАММЫ', text);
    return [scroll, cursor, text];
  });

  await open(page, overviewPath);
  const listScroll = 78;
  const cardEntry = { x: 254, y: link.y - listScroll - 40 };
  const clickLink = { x: link.x + link.width * 0.55, y: link.y + link.height / 2 - listScroll };
  const cardCursor = { x: side, y: 310 };
  const gapCursor = { x: side, y: periods.y + periods.height - 45 };
  let onDetail = false;
  await encode(page, '02-intern-card', 10, async time => {
    if (time < 1.95) {
      const cursor = move(cardEntry, clickLink, phase(time, 0, 1.45));
      const text = 'Открываем стажёра с критичным сигналом';
      await paint(page, listScroll, cursor, 'КАРТОЧКА СТАЖЁРА', text);
      return [listScroll, cursor, text];
    }
    if (!onDetail) {
      await Promise.all([
        page.waitForURL(url => url.pathname === '/interns/DEMO-2', { waitUntil: 'load' }),
        page.mouse.click(clickLink.x, clickLink.y),
      ]);
      assert.equal(await page.locator('h1').innerText(), 'Стажёр DEMO-2');
      assert.match(await page.locator('.panel').first().locator('tr').last().innerText(), /Месяц 6\s+2\s+4\s+\+2/);
      await overlay(page);
      onDetail = true;
    }
    const cursor = move(cardCursor, gapCursor, phase(time, 3.0, 5.6));
    const text = time < 5.6 ? 'Оценки стажёра и наставника за шесть месяцев'
      : 'Месяц 6: 2 у стажёра, 4 у наставника. Разница +2';
    await paint(page, 0, cursor, 'КАРТОЧКА СТАЖЁРА', text);
    return [0, cursor, text];
  });

  await open(page, detailPath);
  const disclosure = six.locator('summary');
  await disclosure.click();
  assert.equal(await six.getAttribute('open'), null);
  const closedScroll = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  const closedSummary = await measure(disclosure);
  const currentScroll = await page.evaluate(() => scrollY);
  const clickSummary = {
    x: closedSummary.x + 52,
    y: closedSummary.y + currentScroll - closedScroll + closedSummary.height / 2,
  };
  const evidenceStart = { x: clickSummary.x - 29, y: clickSummary.y - 70 };
  const evidenceSide = { x: side, y: clickSummary.y + 1 };
  const evidenceEnd = { x: side, y: 673 };
  let expanded = false;
  await encode(page, '03-signal-evidence', 10, async time => {
    if (time < 1.47) {
      const cursor = move(evidenceStart, clickSummary, phase(time, 0, 1.13));
      const text = 'Раскрываем ответы за шестой месяц';
      await paint(page, closedScroll, cursor, 'ОСНОВАНИЕ СИГНАЛА', text);
      return [closedScroll, cursor, text];
    }
    if (!expanded) {
      await page.mouse.click(clickSummary.x, clickSummary.y);
      assert.notEqual(await six.getAttribute('open'), null);
      assert.match(await six.locator('ul').innerText(), /Разница по задачам \+2/);
      expanded = true;
    }
    const scroll = mix(closedScroll, evidence.y + 70, phase(time, 1.47, 3.25));
    const cursor = move(evidenceSide, evidenceEnd, phase(time, 1.47, 3.25));
    const text = time < 4.4 ? 'Причины сигнала видны над двумя анкетами'
      : 'Стажёр пишет, что критерии готовности задачи неясны';
    await paint(page, scroll, cursor, 'ОСНОВАНИЕ СИГНАЛА', text);
    return [scroll, cursor, text];
  });
}

main().catch(error => { console.error(error); process.exitCode = 1; });
