// Play the saved-party flow through the real gateway and native worker.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const {chromium} = require('playwright');

const key = 'browser-test-' + 'x'.repeat(32);
const fixture = String.raw`
import sys
from unittest.mock import patch
from test_team_battle_http import TeamBattleHTTPTests, gateway

test = TeamBattleHTTPTests()
try:
    test.setUp()
    opponent = test.store.save_party({"name": "Opponent", "members": test.enemy})
    origin = f"http://127.0.0.1:{test.gateway.server_port}"
    with patch.object(gateway, "APP_ORIGIN", origin):
        print(origin, test.party["id"], opponent["id"], flush=True)
        sys.stdin.read()
finally:
    test.doCleanups()
`;

async function checkWidth(browser, origin, party, opponent, width) {
  const context = await browser.newContext({viewport: {width, height: 844}, isMobile: true, hasTouch: true});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const prefix = '/app-api/team-battle/';
  const viewportFits = async () => assert(await page.evaluate(
    () => document.documentElement.scrollWidth <= innerWidth));
  const clickAndRead = async (selector, operation) => {
    const [response] = await Promise.all([
      page.waitForResponse(origin + prefix + operation),
      page.locator(selector).click(),
    ]);
    assert.equal(response.status(), 200);
    return response.json();
  };

  try {
    if (width === 320) {
      const cookie = await context.request.post(origin + '/app-api/session', {
        headers: {Authorization: 'Bearer ' + key}, data: {},
      });
      assert.equal(cookie.status(), 200);
    }
    await page.goto(origin + '/app/party');
    await page.getByRole('link', {name: '練習対戦'}).click();
    if (width === 390) {
      await page.locator('#key').fill(key);
      await page.getByRole('button', {name: '接続', exact: true}).click();
    }
    await page.locator('#setup').waitFor({state: 'visible'});
    await viewportFits();
    await page.locator('#own').selectOption(party);
    if (width === 320) await page.locator('#opponent').selectOption(opponent);

    const initial = await clickAndRead('#start', 'start');
    assert.equal(initial.status, 'select_three');
    await page.locator('#preview-enemy li').last().waitFor();
    assert.equal(await page.locator('#preview-enemy li').count(), 6);
    for (const slot of [0, 1, 4]) await page.locator('#picks input').nth(slot).check();
    assert(await page.locator('#select-three').isDisabled());
    await page.locator('#lead').selectOption('4');
    await viewportFits();

    if (width === 390) {
      await page.route(origin + prefix + 'step', async route => {
        // Commit the action before the browser's request reaches the server.
        const first = await route.fetch();
        const conflict = await route.fetch();
        assert.equal(first.status(), 200);
        assert.equal(conflict.status(), 409);
        await route.fulfill({response: conflict});
      }, {times: 1});
    }
    let state = await clickAndRead('#select-three', width === 390 ? 'state' : 'step');
    assert.equal(state.revision, 1);
    assert.equal(state.status, 'battle');
    assert.equal(state.observation.own.team[0].species, initial.observation.own_six[4].species);
    await page.locator('#battle').waitFor();
    await viewportFits();

    for (let i = 0; i < 250 && state.status === 'battle'; i++) {
      const legal = state.observation.legal_actions;
      await page.locator('#actions button:not([disabled])').first().waitFor();
      assert.deepEqual(await page.locator('#actions button').evaluateAll(nodes =>
        nodes.map(node => node.dataset.action)), legal);
      const action = ['shield_yes', 'charge_1', 'charge_0', 'fast'].find(a => legal.includes(a)) ?? legal[0];
      const revision = state.revision;
      state = await clickAndRead('#actions button[data-action="' + action + '"]', 'step');
      assert.equal(state.revision, revision + 1);
    }
    assert.equal(state.status, 'terminated', JSON.stringify(state));
    const labels = {self_ko_win: '勝利', opponent_ko_win: '敗北', simultaneous_ko: '引き分け（同時KO）'};
    await page.locator('#result').waitFor();
    assert.equal(await page.locator('#result').textContent(), labels[state.result.outcome]);
    assert(await page.locator('#actions').isHidden());
    await viewportFits();
    await clickAndRead('#close', 'close');
    await page.locator('#setup').waitFor({state: 'visible'});
    assert.deepEqual(errors, []);
    console.log(width + 'px: ' + state.result.outcome + ' after ' + state.revision + ' revisions');
  } finally {
    await context.close();
  }
}

async function main() {
  const server = spawn(process.env.PYTHON_BIN || 'python', ['-B', '-c', fixture], {
    env: {...process.env, PYTHONPATH: '.:tests', PVP_API_KEY: key, AUTH0_DOMAIN: ''},
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let log = '';
  server.stderr.on('data', chunk => { log = (log + chunk).slice(-8000); });
  const lines = createInterface({input: server.stdout});
  let browser;
  try {
    const ready = await lines[Symbol.asyncIterator]().next();
    assert(!ready.done, log);
    const [origin, party, opponent] = ready.value.split(' ');
    browser = await chromium.launch({executablePath: process.env.CHROME_BIN, args: ['--no-sandbox']});
    for (const width of [390, 320]) await checkWidth(browser, origin, party, opponent, width);
  } catch (error) {
    console.error(log);
    throw error;
  } finally {
    if (browser) await browser.close();
    server.stdin.end();
    lines.close();
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});
