// Mobile browser smoke for the authenticated UI, using a native fixture and local API responses.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const rows = require('./fixtures/strategy_rows.json');

process.env.PVP_PVPOKE_SOURCE = path.resolve(__dirname, '../vendor/pvpoke');
const {runSandbox} = require('../pvpoke_sandbox_runner.js');
const gamemasterPath = path.join(__dirname, 'fixtures/strategy_gamemaster.json');
const html = fs.readFileSync('pvpoke_sandbox_ui.py', 'utf8').split("HTML = r'''")[1].split("'''")[0];
const searchHtml = html.replace('data-tactic-search="0"','data-tactic-search="1"');
const digest = tag => crypto.createHash('sha256').update(html.split('<' + tag + '>')[1].split('</' + tag + '>')[0]).digest('base64');
const csp = "default-src 'none'; connect-src 'self'; script-src 'sha256-" + digest('script') + "'; style-src 'sha256-" + digest('style') + "'";
const origin = 'http://127.0.0.1:9877';
const importKey = 'pokemoniv:sandbox-input-v1';
const sideRows = [rows[0], rows[2]];
const names = ['ヌオー', 'マリルリ'];
const species = Object.fromEntries(sideRows.map((row, i) => [row.species, {
  name_ja: names[i], fastMoves: [row.fast], chargedMoves: [row.charged1, row.charged2],
  default_moves: {fast: row.fast, charged1: row.charged1, charged2: row.charged2},
}]));
const moves = {
  MUD_SHOT: {name_ja: 'マッドショット'}, AQUA_TAIL: {name_ja: 'アクアテール', energy: 35},
  BUBBLE: {name_ja: 'あわ'}, ICE_BEAM: {name_ja: 'れいとうビーム', energy: 55},
};
const initialSpec = {
  schema: 'battle-spec-v1', mode: 'standard',
  rules: {league: 'great', cp_cap: 1500, max_level: 50, cup_id: 'all'},
  calculation_version: 'a'.repeat(64), policies: {attack: ['fast_only', 'standard']},
  combatants: sideRows.map((row, i) => ({
    species_id: row.species, ivs: {attack: row.atk, defense: row.def, hp: row.hp}, level: row.level,
    moves: {fast: row.fast, charged: [row.charged1, row.charged2]},
    initial: {hp: i ? 150 : 155, energy: i ? 100 : 0, shields: i ? 0 : 1, stages: [1, -1]},
  })),
};

function fixtureResult(spec) {
  const native = runSandbox({
    gamemaster_path: gamemasterPath, self: sideRows[0], opponent: sideRows[1],
    initial: spec.combatants.map(({initial}) => ({hp_points: initial.hp, energy_points: initial.energy, buffs: initial.stages})),
    shields: spec.combatants.map(({initial}) => initial.shields),
    actions: spec.actions || [], shield_decisions: spec.shield_decisions || [],
  });
  const status = native.outcome === 'timeout' ? 'partial' : 'complete';
  return {
    schema: 'sandbox-result-v1', status, initial: native.initial, trace: native.trace, shield_results: native.shield_results,
    summary: {schema: 'battle-result-v1', status, ...native},
  };
}

async function checkWidth(browser, width) {
  const page = await browser.newPage({viewport: {width, height: 844}, isMobile: true, hasTouch: true});
  const errors = [];
  const requests = [];
  const tactics = new Map();
  let failNext = false;
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.addInitScript(({key, spec}) => {
      sessionStorage.setItem(key, JSON.stringify(spec));
      sessionStorage.setItem('pokemoniv:tactic-evidence-link-v1', JSON.stringify({
        evaluation_id:'e'.repeat(64), build_id:'b'.repeat(64), search_ids:[]
      }));
    }, {key: importKey, spec: initialSpec});
    await page.route(origin + '/**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === '/app/sandbox') {
        return route.fulfill({contentType: 'text/html', body: searchHtml, headers: {'Content-Security-Policy': csp}});
      }
      if (url.pathname === '/favicon.ico') return route.fulfill({status: 404, body: ''});
      const payload = request.postDataJSON();
      requests.push({path: url.pathname, payload});
      assert.equal(request.headers().authorization, undefined);
      if (url.pathname === '/app-api/catalog') return route.fulfill({json: {ready: true, species, moves}});
      assert.equal(url.pathname, '/app-api/sandbox');
      if (payload.action === 'simulate') {
        assert.equal(payload.spec.mode, 'sandbox');
        assert.equal(payload.spec.calculation_version, undefined);
        assert.equal(payload.spec.policies, undefined);
        if (failNext) {
          failNext = false;
          return route.fulfill({json: {schema: 'sandbox-result-v1', status: 'invalid', error: {message: 'テスト用の入力エラー'}}});
        }
        return route.fulfill({json: fixtureResult(payload.spec)});
      }
      if (payload.action === 'standard') {
        assert.equal(payload.spec.mode, 'sandbox');
        assert.equal(payload.spec.actions, undefined);
        assert.equal(payload.spec.shield_decisions, undefined);
        assert.equal(payload.spec.combatants[0].initial.energy, 100);
        return route.fulfill({json: fixtureResult(payload.spec).summary});
      }
      if (payload.action === 'search_start') {
        assert.equal(payload.spec.mode, 'sandbox');
        return route.fulfill({json: {search_id: 'f'.repeat(64), state: 'unknown',
          coverage: {planned_scripts: 4, attempted_scripts: 0, complete_scripts: 0,
                     fully_executed_scripts: 0, remaining_scripts: 4},
          results: [], information_model: 'fixed_script_counterfactual',
          live_reproducibility: 'not_verified'}});
      }
      if (payload.action === 'search_step') {
        assert.equal(payload.search_id, 'f'.repeat(64));
        assert.equal(payload.budget, 4);
        return route.fulfill({json: {search_id: payload.search_id, state: 'partial',
          coverage: {planned_scripts: 4, attempted_scripts: 1, complete_scripts: 1,
                     fully_executed_scripts: 1, remaining_scripts: 3},
          results: [{index: 0, strategy: 'original', response: 'alternate_charged',
            status: 'complete', outcome: 'self_win', all_self_executed: true,
            opponent_response_executed: true, all_requested_shields_honored: true}],
          information_model: 'fixed_script_counterfactual',
          live_reproducibility: 'not_verified'}});
      }
      if (payload.action === 'save') {
        assert.match(payload.tactic_id, /^[a-f0-9]{32}$/);
        const versions = tactics.get(payload.tactic_id) || [];
        assert.equal(payload.expected_revision, versions.length);
        const record = {tactic_id: payload.tactic_id, name: payload.name, revision: versions.length + 1,
                        spec: payload.spec, saved_at: 0, current: true};
        versions.push(record);
        tactics.set(payload.tactic_id, versions);
        return route.fulfill({json: {...record, latest_revision: versions.length}});
      }
      if (payload.action === 'list') {
        return route.fulfill({json: {items: [...tactics.values()].map(versions => versions.at(-1))}});
      }
      if (payload.action === 'load') {
        const versions = tactics.get(payload.tactic_id);
        return route.fulfill({json: {...versions[(payload.revision || versions.length) - 1], latest_revision: versions.length}});
      }
      throw Error('Unexpected request ' + JSON.stringify(payload));
    });
    await page.goto(origin + '/app/sandbox');
    await page.locator('#workspace').waitFor({state: 'visible'});
    await page.getByText('不足分析から両者の個体・技・開始状態を読み込みました。').waitFor();
    assert.equal(await page.evaluate(key => sessionStorage.getItem(key), importKey), null);
    assert.equal(requests.length, 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
    assert.equal(await page.locator('#turn-scroll').evaluate(el => el.scrollWidth > el.clientWidth), true);

    await page.locator('#action-choice').selectOption('wait');
    await page.locator('#apply-action').click();
    await page.locator('#turn-events summary').filter({hasText: /開始 · 待機（指定）/}).waitFor();
    await page.locator('#undo').click();

    await page.locator('#action-choice').selectOption('charged:AQUA_TAIL');
    assert.equal(await page.locator('#action-form').evaluate(form => form.checkValidity()), false);
    await page.locator('#shield-choice').selectOption('yes');
    assert.equal(requests.length, 2);
    await page.locator('#apply-action').click();
    await page.locator('#action-result').getByText('指定を実行できませんでした。ゲージ不足。').waitFor();
    await page.locator('#action-result').getByText(/相手のシールド.*技が解決しなかった/).waitFor();
    assert.match(await page.locator('#turn-events').innerText(), /マッドショット（自動）/);
    assert.equal(await page.locator('#action-choice').inputValue(), 'charged:AQUA_TAIL');
    await page.locator('#undo').click();
    assert.equal(await page.locator('#action-choice').inputValue(), '');
    await page.locator('#redo').click();
    assert.equal(await page.locator('#action-choice').inputValue(), 'charged:AQUA_TAIL');
    assert.equal(requests.length, 3);

    const selfBuild = page.locator('#setup > details').first();
    await selfBuild.locator(':scope > summary').click();
    await selfBuild.locator('.conditions summary').click();
    await selfBuild.getByLabel('開始ゲージ', {exact: true}).fill('100');
    await selfBuild.getByLabel('開始ゲージ', {exact: true}).press('Tab');
    await page.locator('#apply-action').click();
    await page.locator('#action-result').getByText(/相手のシールド.*残りシールドなし/).waitFor();
    await page.locator('#turn-events summary').filter({hasText: /ダメージ解決.*アクアテール/}).waitFor();

    await page.getByRole('button', {name: /^1ターン 相手 /}).click();
    await page.locator('#action-choice').selectOption('charged:ICE_BEAM');
    await page.locator('#shield-choice').selectOption('no');
    await page.locator('#apply-action').click();
    await page.locator('#action-result').getByText(/自分のシールド.*指定 使わない／結果 未使用/).waitFor();
    assert.deepEqual(requests.at(-1).payload.spec.shield_decisions.map(row => [row.defender, row.use_shield]).sort(), [[0, false], [1, true]]);
    await page.locator('#previous-action').click();
    await page.locator('#selected-turn').filter({hasText: /1ターン · 自分/}).waitFor();

    await page.locator('#jump-turn').fill('3');
    await page.locator('#jump-form button').click();
    await page.locator('#action-choice').selectOption('fast:MUD_SHOT');
    await page.locator('#apply-action').click();
    await page.locator('#action-result').getByRole('button', {name: '開始 T3', exact: true}).waitFor();
    await page.locator('#action-result').getByRole('button', {name: 'ダメージ解決 T4', exact: true}).click();
    await page.locator('#selected-turn').filter({hasText: /4ターン · 自分/}).waitFor();
    const resolution = page.locator('#turn-events summary').filter({hasText: /ダメージ解決.*マッドショット/});
    await resolution.click();
    await page.locator('#turn-events details[open]').getByRole('rowheader', {name: '相手 HP'}).waitFor();
    await page.locator('#turn-events summary').filter({hasText: /効果適用後.*マッドショット/}).waitFor();

    await page.locator('#standard').click();
    await page.locator('#comparison').getByRole('columnheader', {name: '通常対戦'}).waitFor();
    await page.locator('#notice').filter({hasText: /通常対戦：/}).waitFor();
    await page.locator('#tactic-name').fill('テスト戦術');
    await page.locator('#save').click();
    await page.locator('#save-status').filter({hasText: /保存済みの版 1/}).waitFor();
    await page.locator('#tactic-name').fill('テスト戦術の第2版');
    await page.locator('#save').click();
    await page.locator('#save-status').filter({hasText: /保存済みの版 2/}).waitFor();
    await page.locator('#list').click();
    const [id] = tactics.keys();
    await page.locator('#tactics').selectOption(id);
    await page.locator('#revision').fill('1');
    await page.locator('#load-form button').click();
    await page.locator('#save-status').filter({hasText: /過去の版 1/}).waitFor();
    assert.equal(requests.at(-1).payload.action, 'load');
    await page.locator('#save').click();
    await page.locator('#save-status').filter({hasText: /保存済みの版 1/}).waitFor();
    assert.equal(tactics.size, 2);

    assert.equal(await page.locator('#tactic-search-panel').isVisible(),true);
    await page.locator('#tactic-search-panel summary').click();
    await page.locator('#search-start').click();
    await page.locator('#search-status').filter({hasText: /候補 4件/}).waitFor();
    assert.equal(await page.locator('#search-to-missing').isVisible(),true);
    assert.deepEqual(await page.evaluate(() => JSON.parse(sessionStorage.getItem(
      'pokemoniv:tactic-evidence-link-v1')).search_ids), ['f'.repeat(64)]);
    await page.locator('#search-step').click();
    await page.locator('#search-status').filter({hasText: /検証 1件/}).waitFor();
    await page.locator('#search-results').getByText(/相手が別のゲージ技を指定/).waitFor();
    await page.locator('#search-results').getByText(/指定動作・シールドを確認/).waitFor();
    assert.equal(requests.filter(r => r.payload?.action === 'search_step').length, 1);

    failNext = true;
    await page.locator('#simulate').click();
    await page.locator('#script-status').filter({hasText: /^入力エラー$/}).waitFor();
    assert.equal(await page.locator('#initial').isHidden(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined});
  try {
    for (const width of [320, 390]) await checkWidth(browser, width);
    console.log('Mobile Sandbox import, trace, edits, comparison, and tactic revisions passed');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
