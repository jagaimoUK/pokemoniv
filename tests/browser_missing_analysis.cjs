// Mobile UI smoke with synthetic responses and no production services.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const {chromium} = require('playwright');
const rows = require('./fixtures/strategy_rows.json');

const html = fs.readFileSync('pvpoke_missing_ui.py', 'utf8').split("HTML = r'''")[1].split("'''")[0];
const digest = text => crypto.createHash('sha256').update(text).digest('base64');
const inline = tag => digest(html.split('<' + tag + '>')[1].split('</' + tag + '>')[0]);
const csp = "default-src 'none'; connect-src 'self'; script-src 'sha256-" + inline('script')
  + "'; style-src 'sha256-" + inline('style') + "'";
const species = Object.fromEntries(rows.map(r => [r.species, {
  name: r.species,
  fastMoves: [r.fast],
  chargedMoves: [r.charged1, r.charged2],
  default_moves: {fast: r.fast, charged1: r.charged1, charged2: r.charged2},
}]));

async function fillBuild(page, selector, row) {
  await page.locator(selector + ' input[type=text]').fill(row.species);
  const controls = page.locator(selector + ' input[type=number]');
  for (const [i, value] of [row.atk, row.def, row.hp, row.level].entries()) {
    await controls.nth(i).fill(String(value));
  }
}

async function checkWidth(browser, width) {
  const page = await browser.newPage({viewport: {width, height: 844}, isMobile: true});
  const errors = [];
  const requests = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.addInitScript(() => sessionStorage.setItem('pokemoniv:tactic-evidence-link-v1',
      JSON.stringify({evaluation_id:'e'.repeat(64),build_id:'b'.repeat(64),search_ids:['f'.repeat(64)]})));
    await page.route('http://127.0.0.1:9876/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === '/app/missing') {
        return route.fulfill({contentType: 'text/html', body: html, headers: {'Content-Security-Policy': csp}});
      }
      if (path === '/favicon.ico') return route.fulfill({status: 404, body: ''});
      const payload = request.postDataJSON();
      requests.push({path, payload});
      if (path === '/app-api/catalog') return route.fulfill({json: {ready: true, species}});
      if (payload.action === 'evaluate') {
        const candidate = payload.candidates[0];
        const opponent = payload.scenarios[0].opponent;
        const condition = {opponent, shields: [1, 1], state: 'unknown', meets: null,
                           spec: {combatants: [{initial: {energy: 0}}, opponent]}};
        const reference = {build_id: 'b'.repeat(64), species_id: candidate.species_id};
        return route.fulfill({json: {
          state: 'evidence_pending', evaluation_id: 'e'.repeat(64), reference,
          role: {role_id: 'lead', priority: 1}, can_calculate: false,
          candidates: [{...candidate, ...reference, status: 'pending', party_substitution: 'pending',
                        conditions: [condition], owned_instances: []}],
        }});
      }
      if (payload.action === 'tactic_evidence') {
        assert.equal(payload.evaluation_id,'e'.repeat(64));
        assert.deepEqual(payload.search_ids,['f'.repeat(64)]);
        return route.fulfill({json:{schema:'missing-tactic-evidence-v1',standard_state:'evidence_pending',
          searched_count:1,new_battles:0,builds:[{build_id:'b'.repeat(64),
          theoretical_all_conditions:false,advisory:{evidence_order:1,role_priority:3,
          required_conditions:1,tested_conditions:1,theoretical_supported_conditions:0,
          unfavorable_shield_conditions:0,only_observed_complete_build:false},
          conditions:[{standard:{meets:null},tested_scripts:1,
          matching_scripts:0,truncated:false,paths:[{strategy:'original',
          opponent_response:'alternate_charged',meets:null}]}]}]}});
      }
      if (payload.action === 'explore') {
        assert.equal(payload.budget, 0);
        return route.fulfill({json: {completed_iv_count: 1, eligible_iv_count: 4096,
                                     qualifying_count: 1, qualifying: [{attack: 0, defense: 15, hp: 15}]}});
      }
      throw Error('Unexpected request ' + path);
    });
    await page.goto('http://127.0.0.1:9876/app/missing');
    await page.locator('#workspace').waitFor({state: 'visible'});
    await fillBuild(page, '#reference', rows[0]);
    await fillBuild(page, '#scenarios', rows[2]);
    await page.locator('#evaluate').click();
    await page.getByText('対戦証拠待ち', {exact: true}).waitFor();
    await page.locator('summary').filter({hasText: '重要IVを探索'}).click();
    await page.getByRole('button', {name: '探索範囲を確認'}).click();
    await page.getByText('達成したIV　0/15/15', {exact: true}).waitFor();
    assert.equal(await page.getByRole('button', {name: '1対面を追加検証'}).count(), 0);
    assert.equal(await page.getByRole('button', {name: 'この対面だけ計算'}).count(), 0);
    await page.locator('#tactic-evidence-read').click();
    await page.getByText(/理論上の戦術であり、観測情報に基づく実戦再現性は未検証です/).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
    assert.deepEqual(errors, []);
    assert.equal(requests.length, 4);
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined});
  try {
    for (const width of [320, 390]) await checkWidth(browser, width);
    console.log('Mobile missing analysis and read-only IV exploration passed');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
