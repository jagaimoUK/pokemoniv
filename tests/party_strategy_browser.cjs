'use strict';
// Run with an installed Playwright browser, or STRATEGY_CHROMIUM_PATH.
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const server=spawn('python',['tests/party_strategy_fixture_server.py'],{stdio:['ignore','pipe','pipe']});
 let browser,page,lastStart;
 try{
 const config=await new Promise((resolve,reject)=>{let buffer='';server.stdout.on('data',chunk=>{buffer+=chunk;const at=buffer.indexOf('\n');if(at>=0)try{resolve(JSON.parse(buffer.slice(0,at)))}catch(e){reject(e)}});server.on('exit',c=>reject(Error('Fixture server exited '+c)));server.stderr.on('data',()=>{});});
 browser=await chromium.launch({headless:true,executablePath:process.env.STRATEGY_CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
 page=await browser.newPage({viewport:{width:390,height:844}});const errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
 page.on('request',r=>{if(r.url().endsWith('/app-api/party/start'))lastStart=r.postDataJSON()});
 async function launch(selector){
  const started=page.waitForResponse(r=>r.url().endsWith('/app-api/party/start'));
  await page.click(selector);const response=await started;
  assert.equal(response.status(),200,await response.text());const job=await response.json();
  await page.waitForFunction(id=>activeJob===id,job.job_id,{timeout:10000});
 }
 async function done(message='計算完了'){
  await page.waitForFunction(text=>activeJob===null&&document.getElementById('status').textContent.includes(text),message,{timeout:60000});
 }

 await page.goto(config.url+'/app/party');await page.fill('#key',config.key);await page.click('#login');await page.waitForSelector('#workspace:not([hidden])');

 // 1) Verify P0 streamlined layout: 2-col 6 cards, no permanent large save panel, top-right パーティ button, 2 primary buttons, detail calc OFF by default.
 assert.equal(await page.locator('#members > details.mon').count(),6,'Exactly 6 manual cards');
 assert.equal(await page.locator('#partyLibrary').count(),0,'Old permanent save panel removed');
 assert.equal(await page.locator('#partyMenuBtn').isVisible(),true,'Top-right compact パーティ button visible');
 assert.equal(await page.locator('#autoComplete').isVisible(),true,'Primary 自動補完 button visible');
 assert.equal(await page.locator('#evaluate').isVisible(),true,'Primary パーティ評価 button visible');
 assert.equal(await page.isChecked('#strategyRefinement'),false,'Detail strategy refinement defaults OFF');
 assert.equal(await page.isChecked('#opponentUncertainty'),false,'Opponent uncertainty defaults OFF');
 // No slot numbers like 枠1 on empty cards; lock toggles hidden on unselected cards.
 assert(!/枠[1-6]/.test(await page.locator('#members').textContent()),'No unnecessary slot numbers');
 assert.equal(await page.locator('#members .lock-toggle:not([hidden])').count(),0,'Lock toggles hidden on empty cards');

 // 2) Verify 2-column grid & zero horizontal overflow at 360px and 390px.
 for(const width of [360,390]){
  await page.setViewportSize({width,height:844});
  const cols=await page.locator('#members').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
  assert.equal(cols,2,'Cards render in 2 columns on mobile '+width+'px');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'No horizontal overflow at '+width+'px');
 }
 await page.setViewportSize({width:390,height:844});

 // 3) Manual selection reveals lock toggle WITHOUT auto-locking it!
 await page.locator('#members details.mon').first().locator('summary').click();
 const firstInput=page.locator('#members [data-field=species]').first();
 await firstInput.fill('ぬお');
 await page.locator('#members .suggestions button').filter({hasText:'ヌオー'}).first().click();
 assert.equal(await firstInput.inputValue(),'ヌオー');
 assert.equal(await page.locator('#members .lock-toggle').first().isHidden(),false,'Selected card shows lock toggle');
 assert.equal(await page.locator('#members [data-field=locked]').first().isChecked(),false,'Manual selection does NOT auto-lock');

 // 4) Unsaved changes protection in top-right パーティ drawer + Save / Rename / Switch.
 await page.click('#partyMenuBtn');
 await page.waitForSelector('#partyDialog[open]');
 const fixtureId=await page.locator('#saved option').nth(1).getAttribute('value');
 await page.selectOption('#saved',fixtureId);
 await page.click('#load');
 assert.equal(await page.locator('#unsavedGuard').isVisible(),true,'Unsaved changes guard blocks silent discard');
 await page.click('#confirmDiscard');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('読み込みました'));

 // Save As + Rename + Switch independence.
 await page.click('#partyMenuBtn');
 await page.fill('#partyName','大会A');await page.click('#saveAs');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会A'));
 const partyA=await page.inputValue('#saved');
 await page.fill('#partyName','大会A改');await page.click('#renameParty');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会A改'));
 await page.click('#closePartyDialog');

 // 5) Unified weight-driven meta sets: custom set A edit must NOT affect custom set B or Current Meta, and survives reload!
 await page.locator('#scenarioEditorDetails > summary').click();
 // Save custom set A and B, edit quagsire=10 only on A.
 await page.fill('#scenarioName','独自予測A');
 await page.click('#scenarioSaveAs');
 await page.waitForFunction(()=>document.getElementById('scenarioManageStatus').textContent.includes('独自予測A'));
 const setAId=await page.inputValue('#scenario');
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 await page.selectOption('#metaWeights select[data-species=quagsire]','10');
 await page.waitForFunction(()=>document.getElementById('metaWeightSaveStatus').textContent.includes('保存済み'));
 await page.selectOption('#scenario','current');
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 assert.notEqual(await page.inputValue('#metaWeights select[data-species=quagsire]'),'10','Custom set A weight must NOT bleed into Current Meta');
 await page.fill('#scenarioName','独自予測B');
 await page.click('#scenarioSaveAs');
 await page.waitForFunction(()=>document.getElementById('scenarioManageStatus').textContent.includes('独自予測B'));
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 assert.notEqual(await page.inputValue('#metaWeights select[data-species=quagsire]'),'10','Custom set A weight must NOT bleed into Custom set B');
 await page.reload();await page.waitForSelector('#workspace:not([hidden])');
 await page.locator('#scenarioEditorDetails > summary').click();
 await page.selectOption('#scenario',setAId);
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 assert.equal(await page.inputValue('#metaWeights select[data-species=quagsire]'),'10','Isolated custom weight survives reload');

 // 6) 0-member Auto-Complete with automatic 3-phase meta evolution (average + worst case) + Heatmap modal.
 await launch('#autoComplete');await done();
 assert((await page.textContent('#summaryResult')).includes('時系列メタ変化'),'Automatic 3-phase meta evolution displayed');
 assert((await page.textContent('#summaryResult')).includes('全3段階の平均'),'Cross-phase average displayed');
 assert((await page.textContent('#summaryResult')).includes('最悪ケース耐性'),'Worst-case phase resilience displayed');
 assert((await page.textContent('#recommendedThree')).includes('推奨3体選出'),'Recommended 3 displayed immediately');
 assert((await page.textContent('#allTriplesPanel')).includes('全20組'),'All 20 triples expandable panel rendered');
 assert(await page.locator('#swapAdvice .completion-card').count()>=1);
 const firstPlan=page.locator('#swapAdvice .completion-card').first();
 await firstPlan.getByRole('button',{name:'弱点を視覚化'}).click();
 const comparison=page.locator('.party-comparison');
 assert.equal(await comparison.evaluate(el=>el.open),true);
 await comparison.getByRole('button',{name:'比較を閉じる'}).click();
 await firstPlan.getByRole('button',{name:'この6体を反映'}).click();
 assert.equal(await page.locator('#members .lock-toggle:not([hidden])').count(),6,'Applied 6 cards show lock toggles');

 // 7) 6-member Evaluate (パーティ評価) + Opponent 6 gating custom strategy panel.
 assert.equal(await page.locator('#opponentStrategyPanel').isHidden(),true,'Opponent strategy panel hidden until 6 opponents entered');
 const csv=JSON.parse(fs.readFileSync('tests/fixtures/strategy_rows.json')).map(x=>[x.species,x.fast,x.charged1,x.charged2,x.atk,x.def,x.hp].join(',')).join('\n');
 await page.locator('#enemyDetails > summary').click();
 await page.locator('#enemyDetails details').filter({has:page.locator('#enemy')}).locator('summary').click();
 await page.fill('#enemy',csv);
 await page.locator('#enemy').blur();
 assert.equal(await page.locator('#opponentStrategyPanel').isHidden(),false,'Opponent strategy panel revealed once 6 opponents entered');
 await launch('#evaluate');await done();
 assert((await page.textContent('#recommendedThree')).includes('相手6体に対する詳細選出根拠'),'Opponent 6 selection shown in results');

 // 8) Run opponent-specific detail strategy calculation.
 await page.locator('#opponentStrategyPanel > summary').click();
 await page.selectOption('#strategySelf','2');
 await launch('#runStrategy');await done();
 assert((await page.textContent('#strategyResult')).includes('詳細条件 9/9'));

 // Final mobile width sanity check.
 for(const width of [360,390]){
  await page.setViewportSize({width,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Final mobile check fits without horizontal overflow at '+width+'px');
 }
 assert.equal(errors.length,0,errors.join('\n'));
 console.log('P0 Mobile 360/390px browser regression passed');
 }catch(e){if(page){console.error('Final app status:',await page.locator('#status').textContent());}
 throw e;
 }finally{if(browser)await browser.close();server.kill();}
})();
