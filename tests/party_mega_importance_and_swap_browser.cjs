'use strict';
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');

(async () => {
  const server = spawn('python3', ['tests/party_strategy_fixture_server.py'], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {...process.env, PARTY_TEST_SYNTHETIC_MEGA: '1'}
  });
  let browser;
  try {
    const config = await new Promise((resolve, reject) => {
      let buffer = '', stderr = '';
      server.stdout.on('data', chunk => {
        buffer += chunk;
        const at = buffer.indexOf('\n');
        if (at >= 0) {
          try { resolve(JSON.parse(buffer.slice(0, at))); } catch (e) { reject(e); }
        }
      });
      server.stderr.on('data', chunk => { stderr += chunk.toString().slice(-500); });
      server.on('exit', code => reject(Error('Fixture exited ' + code + ': ' + stderr.slice(-1000))));
    });

    browser = await chromium.launch({
      headless: true,
      executablePath: process.env.STRATEGY_CHROMIUM_PATH || '/usr/bin/google-chrome',
      args: ['--no-sandbox', '--disable-dev-shm-usage']
    });
    const page = await browser.newPage({viewport: {width: 480, height: 900}});
    page.setDefaultTimeout(15000);

    const errors = [];
    page.on('pageerror', e => errors.push(e.message));

    console.log('Navigating to', config.url + '/app/party');
    await page.goto(config.url + '/app/party');
    await page.fill('#key', config.key);
    await page.click('#login');
    await page.waitForSelector('#workspace:not([hidden])');

    // 1. Load saved fixture party
    await page.selectOption('#saved', await page.locator('#saved option').nth(1).getAttribute('value'));
    await page.click('#load');
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('読み込みました'));

    // Set tournament rules to great_mega so megas are legal in 3-pick
    await page.selectOption('#partyRuleset', 'great_mega');

    // 2. Switch to "弱点・補完" tab
    await page.click('button[data-tab="weakness"]');
    await page.waitForSelector('#weakness:not([hidden])');
    assert.equal(await page.locator('#megaImportanceSection').isVisible(), true, 'Mega importance section must be visible');
    assert.equal(await page.locator('#manualSwapSection').isVisible(), true, 'Manual swap section must be visible');

    // 3. Seed shared moveset in pvpoke-app-movesets-v1 and test Mega Importance calculation
    await page.evaluate(() => {
      localStorage.setItem('pvpoke-app-movesets-v1', JSON.stringify({
        quagsire_mega: [{species: 'quagsire_mega', fast: 'WATER_GUN', charged1: 'MUD_BOMB', charged2: 'SLUDGE_BOMB', mega_level: 3, enabled: true}]
      }));
    });
    console.log('Testing #runMegaImportance...');
    await page.click('#runMegaImportance');
    await page.waitForFunction(() => {
      const el = document.getElementById('megaImportanceResult');
      return el && !el.textContent.includes('「メガ重要性を比較する」を押すと');
    });
    const importanceText = await page.textContent('#megaImportanceResult');
    console.log('Mega importance result:', importanceText.slice(0, 140));
    assert.ok(importanceText.includes('使用技'), 'Mega importance table should have move column');
    assert.ok(importanceText.includes('厳選共有技'), 'Mega importance should apply and display shared moveset');

    // Open move editor inside Mega Importance card and verify move controls + re-analysis
    await page.locator('#megaImportanceResult details.mega-moves-editor summary').first().click();
    const firstReanalyzeBtn = page.locator('#megaImportanceResult .mega-form-move-box button', {hasText: 'この技で再分析'}).first();
    assert.equal(await firstReanalyzeBtn.isVisible(), true, 'Re-analyze button should be visible inside move editor');
    const firstFastSel = page.locator('#megaImportanceResult .mega-form-move-box select').first();
    await firstFastSel.selectOption('MUD_SHOT');
    await firstReanalyzeBtn.click();
    await page.waitForFunction(() => document.getElementById('megaImportanceResult')?.textContent.includes('分析用変更'));

    // 4. Test quick form buttons and swap move editor
    const quickButtons = await page.locator('#manualSwapQuickForms button').count();
    console.log('Quick swap form buttons found:', quickButtons);

    // 5. Test Manual Swap comparison
    console.log('Testing #runManualSwap...');
    // Type a replacement species into #manualSwapSearch and verify move editor appears
    await page.fill('#manualSwapSearch', 'quagsire_mega');
    await page.waitForSelector('#manualSwapMovesWrap:not([hidden])');
    await page.click('#runManualSwap');

    // Wait for the comparison dialog
    await page.waitForSelector('dialog.manual-swap-dialog[open]');
    assert.equal(await page.locator('dialog.manual-swap-dialog').isVisible(), true, 'Manual swap dialog should open');

    const dialogHeader = await page.textContent('dialog.manual-swap-dialog h2');
    console.log('Dialog header:', dialogHeader);
    assert.ok(dialogHeader.includes('1体交換の相性比較'), 'Header should mention swap comparison');

    // Verify heatmap table and metrics box
    const tableVisible = await page.locator('dialog.manual-swap-dialog .compare-heatmap').isVisible();
    assert.equal(tableVisible, true, 'Heatmap table should be displayed');

    const metricsText = await page.textContent('dialog.manual-swap-dialog .completion-card');
    console.log('Metrics summary:', metricsText);
    assert.ok(metricsText.includes('補完率:'), 'Should display coverage delta');
    assert.ok(metricsText.includes('深刻度:'), 'Should display severity delta');

    // 6. Test Shield switcher in dialog
    console.log('Testing shield switching in swap dialog...');
    const ownShieldSelect = page.locator('dialog.manual-swap-dialog select').nth(0);
    const enemyShieldSelect = page.locator('dialog.manual-swap-dialog select').nth(1);

    // Switch to 0-0 shield
    await ownShieldSelect.selectOption('0');
    await enemyShieldSelect.selectOption('0');
    await page.waitForFunction(() => {
      const card = document.querySelector('dialog.manual-swap-dialog .completion-card');
      return card && card.textContent.includes('自分 0枚 / 相手 0枚');
    });
    const updatedMetrics = await page.textContent('dialog.manual-swap-dialog .completion-card');
    assert.ok(updatedMetrics.includes('自分 0枚 / 相手 0枚'), 'Metrics should update to 0-0 shields');
    console.log('0-0 shield metrics verified:', updatedMetrics);

    // Switch to 1-1 shield
    await ownShieldSelect.selectOption('1');
    await enemyShieldSelect.selectOption('1');
    await page.waitForFunction(() => {
      const card = document.querySelector('dialog.manual-swap-dialog .completion-card');
      return card && card.textContent.includes('自分 1枚 / 相手 1枚');
    });
    console.log('1-1 shield metrics verified');

    // 7. Test Apply swap to party button
    console.log('Testing apply swap button...');
    const applyBtn = page.locator('dialog.manual-swap-dialog button', {hasText: 'この交換をパーティに反映'});
    assert.equal(await applyBtn.isVisible(), true, 'Apply button should be visible');
    await applyBtn.click();

    // Dialog should be closed and first slot species should be updated
    await page.waitForFunction(() => !document.querySelector('dialog.manual-swap-dialog')?.open);
    const firstSlotSpecies = await page.locator('#members [data-field=species]').first().getAttribute('data-species');
    console.log('First slot species ID after swap:', firstSlotSpecies);
    assert.equal(firstSlotSpecies, 'quagsire_mega', 'First slot species ID should be updated to quagsire_mega');

    const isMegaWrapHidden = await page.locator('#members [data-mega-wrap=mega_level]').first().evaluate(el => el.hidden);
    assert.equal(isMegaWrapHidden, false, 'Mega level selector hidden attribute should be false for quagsire_mega');

    const summaryText = await page.locator('#members summary').first().textContent();
    console.log('First slot card summary after swap:', summaryText);
    assert.ok(summaryText.includes('メガヌオー') || summaryText.includes('quagsire_mega'), 'Summary should display Mega form name');

    assert.equal(errors.length, 0, 'No JavaScript page errors: ' + errors.join('; '));
    console.log('ALL BROWSER VALIDATION TESTS PASSED!');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})();
