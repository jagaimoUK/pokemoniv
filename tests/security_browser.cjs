/* Verify actual Chromium execution under the HTTP CSP, with an anonymous fixture. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { chromium } = require('playwright');

(async () => {
  const server = spawn('python', ['tests/security_browser_server.py'], {
    env: { ...process.env, PVP_API_KEY: 'browser-fixture-' + 'x'.repeat(40) },
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  let browser;
  try {
    const [data] = await once(server.stdout, 'data');
    const port = Number(String(data).trim());
    assert(port > 0, 'fixture port');
    browser = await chromium.launch({
      executablePath: process.env.STRATEGY_CHROMIUM_PATH || undefined,
      headless: true,
      env: { PATH: process.env.PATH, HOME: process.env.HOME, LANG: 'C.UTF-8' },
    });
    for (const [path, selector] of [['/app', '#connect'], ['/app/party', '#login'],
                                    ['/reader-backup', '#issue']]) {
      const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(() => {
        window.cspViolations = [];
        document.addEventListener('securitypolicyviolation', e => window.cspViolations.push(e.violatedDirective));
      });
      const response = await page.goto(`http://127.0.0.1:${port}${path}`);
      assert.equal(response.status(), 200);
      await page.waitForFunction(s => typeof document.querySelector(s)?.onclick === 'function', selector);
      assert.deepEqual(await page.evaluate(() => window.cspViolations), [], path);
      assert.deepEqual(errors, [], path);
      await page.close();
    }
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${port}/flashcards`);
    await page.waitForFunction(() => !!window.FLASHCARD_BOOTSTRAP);
    assert.deepEqual(errors, []);
    console.log('CSP scripts initialize on app, party, backup and flashcards (390px mobile).');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
