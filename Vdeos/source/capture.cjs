const assert = require('node:assert/strict');
const { once } = require('node:events');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const output = process.env.MGTS_VIDEO_DIR || path.resolve(__dirname, '..');
const base = 'http://127.0.0.1:' + (process.env.MGTS_PORT || '18086');
const overview = '/?month=6';
const detail = '/interns/DEMO-2?month=6';
const fps = 15;
const duration = 10;
const newFeedback = 'Критерии готовности пришли после начала работы. Пришлось дважды переделать отчёт.';

function ease(value) {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
}

async function open(page, route) {
  const navigation = await page.goto(base + route);
  const response = navigation || await page.reload();
  assert.equal(response.status(), 200);
  await page.evaluate(() => document.fonts.ready);
  assert.match(await page.locator('main').innerText(), /демонстрационн/i);
  await page.evaluate(() => {
    const caption = document.createElement('div');
    caption.id = 'video-caption';
    caption.style.cssText = 'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:9999;pointer-events:none;white-space:nowrap;padding:11px 20px;color:#fff;background:#102b4b;border-radius:9px;box-shadow:0 4px 14px #102b4b40;font:600 20px/1.3 system-ui,sans-serif';
    document.body.append(caption);
  });
}

async function draw(page, scroll, text) {
  await page.evaluate(({ scroll, text }) => {
    window.scrollTo({ top: scroll, behavior: 'instant' });
    document.querySelector('#video-caption').textContent = text;
  }, { scroll, text });
}

async function verticalPosition(locator, inset = 35) {
  return locator.evaluate((element, margin) => Math.max(0, element.getBoundingClientRect().top + window.scrollY - margin), inset);
}

async function record(page, file, scene) {
  const encoder = spawn(process.env.FFMPEG || 'ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y', '-f', 'image2pipe',
    '-framerate', String(fps), '-c:v', 'mjpeg', '-i', 'pipe:0',
    '-vf', 'scale=1920:1080:flags=lanczos,fps=30', '-an', '-c:v', 'libx264',
    '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
    path.join(output, file + '.mp4'),
  ], { stdio: ['pipe', 'ignore', 'inherit'] });
  const done = once(encoder, 'close');
  try {
    for (let frame = 0; frame < fps * duration; frame++) {
      await scene(frame / fps);
      const bytes = await page.screenshot({ type: 'jpeg', quality: 94 });
      if (!encoder.stdin.write(bytes)) await once(encoder.stdin, 'drain');
    }
    encoder.stdin.end();
    const [code] = await done;
    assert.equal(code, 0);
    console.log(file + '.mp4: ' + duration + ' seconds');
  } catch (error) {
    encoder.kill();
    throw error;
  }
}

async function recordRecommendation(page) {
  const webhookToken = process.env.MGTS_WEBHOOK_TOKEN;
  assert.ok(webhookToken, 'Set the webhook token of the isolated demo');
  await open(page, detail + '#answers');
  const submission = await page.request.post(base + '/webhooks/yandex/intern', {
    headers: { 'X-Webhook-Token': webhookToken },
    data: {
      form_id: 'local-demo-intern', submission_id: 'video-recommendation-' + Date.now(),
      intern_id: 'DEMO-2', department: 'IT', period: 6,
      scores: { task_clarity: 2, mentor_support: 4, workload: 4, interest: 5,
        development: 4, team_interaction: 5, satisfaction: 3 },
      comments: { difficulties: newFeedback },
    },
  });
  assert.equal(submission.status(), 202);
  await open(page, detail + '#answers');
  const feedback = page.locator('#month-6 blockquote').filter({ hasText: newFeedback });
  assert.equal(await feedback.count(), 1);
  const sourcePosition = await verticalPosition(feedback, 90);

  let showAnalysis = false;
  let position;
  await record(page, '04-deepseek-advice', async time => {
    if (time < 2.4) {
      await draw(page, sourcePosition, 'Новый отзыв: стажёр дважды переделал отчёт');
      return;
    }
    if (!showAnalysis) {
      let ready = false;
      for (let attempt = 0; attempt < 38; attempt++) {
        const response = await page.request.get(base + detail);
        const html = await response.text();
        if (html.includes('<strong>Что может сделать HR.</strong>')) {
          ready = true;
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 1250));
      }
      assert.ok(ready, 'DeepSeek did not produce a recommendation for the new response');
      await open(page, detail + '#analysis');
      position = await verticalPosition(page.locator('#analysis'), 24);
      showAnalysis = true;
    }
    if (time >= 6 && !await page.locator('#analysis details[open]').count()) {
      const matchingTheme = page.locator('#analysis details').filter({ hasText: newFeedback }).first();
      assert.equal(await matchingTheme.count(), 1, 'The model must cite the new comment');
      await matchingTheme.locator('summary').click();
    }
    await draw(page, position, time < 6
      ? 'После анализа DeepSeek предлагает конкретный шаг для HR'
      : 'Куратор раскрывает источник и проверяет совет');
  });
}

async function main() {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    headless: true,
    args: ['--hide-scrollbars'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, locale: 'ru-RU' });
    await page.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());

    if (process.argv.includes('--deepseek-only')) {
      await recordRecommendation(page);
      return;
    }
    await open(page, overview);
    const trend = await verticalPosition(page.locator('#trend'));
    assert.match(await page.locator('#interns').innerText(), /DEMO-2/);
    await record(page, '01-overview', async time => {
      await draw(page, trend * ease((time - 3.2) / 2),
        time < 4.4 ? 'HR видит охват анкет и стажёров, которым нужна поддержка'
          : 'Графики выделяют низкие оценки и падения за шесть месяцев');
    });

    await open(page, overview);
    const list = await verticalPosition(page.locator('#interns'));
    let detailOpen = false;
    await record(page, '02-intern-card', async time => {
      if (time < 2.4) {
        await draw(page, list, 'Открываем карточку стажёра с критичным сигналом');
        return;
      }
      if (!detailOpen) {
        await page.getByRole('link', { name: 'DEMO-2', exact: true }).click();
        assert.match(page.url(), /\/interns\/DEMO-2/);
        await open(page, detail);
        assert.match(await page.locator('.comparison').innerText(), /Месяц 6\s+2\s+4\s+\+2/);
        detailOpen = true;
      }
      await draw(page, 0, 'Шестой месяц: стажёр поставил 2, наставник — 4. Разница +2');
    });

    await open(page, detail);
    const analysis = page.locator('#analysis');
    const answer = page.locator('#month-6');
    const ready = await analysis.getByText('Что может сделать HR.', { exact: true }).count() > 0;
    const start = await verticalPosition(ready ? analysis : page.locator('#answers'));
    const end = await verticalPosition(answer);
    let themeOpen = false;
    await record(page, '03-signal-evidence', async time => {
      if (ready && time >= 2.0 && !themeOpen) {
        const theme = analysis.locator('details').first();
        if (await theme.count()) await theme.locator('summary').click();
        themeOpen = true;
      }
      const target = ready && time >= 5.4 ? await verticalPosition(answer) : end;
      const scroll = ready ? start + (target - start) * ease((time - 5.4) / 1.6) : start + (end - start) * ease(time / 2);
      const text = ready && time < 6
        ? 'DeepSeek предлагает шаг для HR и показывает основания'
        : 'Исходные оценки и комментарии помогают проверить сигнал';
      await draw(page, scroll, text);
    });
    console.log('Live model shown: ' + ready);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
