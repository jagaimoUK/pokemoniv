'use strict';
// Run with an installed Playwright browser, or STRATEGY_CHROMIUM_PATH.
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const server=spawn('python',['tests/party_strategy_fixture_server.py'],{stdio:['ignore','pipe','pipe']});
 let browser;
 try{
 const config=await new Promise((resolve,reject)=>{let buffer='';server.stdout.on('data',chunk=>{buffer+=chunk;const at=buffer.indexOf('\n');if(at>=0)try{resolve(JSON.parse(buffer.slice(0,at)))}catch(e){reject(e)}});server.on('exit',c=>reject(Error('Fixture server exited '+c)));server.stderr.on('data',()=>{});});
 browser=await chromium.launch({headless:true,executablePath:process.env.STRATEGY_CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(8000);
 await page.goto(config.url+'/app/party');await page.fill('#key',config.key);await page.click('#login');await page.waitForSelector('#workspace:not([hidden])');
 await page.click('[data-tab=settings]');await page.selectOption('#saved',await page.locator('#saved option').nth(1).getAttribute('value'));await page.click('#load');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('読み込みました'));
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 assert((await page.textContent('#metaWeights')).includes('ヌオー'));
 await page.fill('#metaFilter','ぬおー');
 assert.equal(await page.locator('#metaWeights select').count(),1);
 await page.selectOption('#metaWeights select[data-species=quagsire]','4');
 await page.fill('#metaFilter','');
 assert.equal(await page.inputValue('#metaWeights select[data-species=quagsire]'),'4');
 await page.waitForFunction(()=>document.getElementById('metaWeightSaveStatus').textContent.includes('自動保存しました'));
 const originalMeta=await page.inputValue('#meta');
 const alternative=await page.locator('#meta option').filter({hasText:'Alternate fixture'}).getAttribute('value');
 await page.selectOption('#meta',alternative);
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 assert.equal(await page.inputValue('#metaWeights select[data-species=quagsire]'),'4');
 await page.selectOption('#meta',originalMeta);
 await page.reload();await page.waitForSelector('#workspace:not([hidden])');
 await page.click('[data-tab=settings]');
 await page.waitForSelector('#metaWeights select[data-species=quagsire]');
 assert.equal(await page.inputValue('#metaWeights select[data-species=quagsire]'),'4','Shared importance survives page reload');
 await page.selectOption('#saved',await page.locator('#saved option').nth(1).getAttribute('value'));await page.click('#load');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('読み込みました'));
 const csv=JSON.parse(fs.readFileSync('tests/fixtures/strategy_rows.json')).map(x=>[x.species,x.fast,x.charged1,x.charged2,x.atk,x.def,x.hp].join(',')).join('\n');
 await page.click('[data-tab=compose]');await page.locator('#members details').first().locator('summary').click();
 const speciesInput=page.locator('#members [data-field=species]').first();await speciesInput.fill('ぬお');await page.locator('#members .suggestions button').filter({hasText:'ヌオー'}).first().click();
 assert.equal(await speciesInput.inputValue(),'ヌオー');assert.equal(await page.locator('#members [data-field=fast]').first().evaluate(el=>el.tagName),'SELECT');
 await page.click('[data-tab=selection]');await page.locator('#selection').getByRole('button',{name:'ポケモンを追加',exact:true}).click();await page.locator('#selection [data-field=species]').fill('Azumarill');await page.locator('#selection .suggestions button').first().click();assert((await page.inputValue('#enemy')).startsWith('azumarill,'));
 await page.locator('#selection details').filter({has:page.locator('#enemy')}).locator('summary').click();
 await page.fill('#enemy','ヌオー,マッドショット,アクアテール,ストーンエッジ,0,15,15');
 await page.locator('#enemy').blur();
 assert.equal(await page.locator('#selection [data-field=fast]').first().inputValue(),'MUD_SHOT');
 assert.equal(await page.locator('#selection [data-field=fast]').first().locator('option:checked').textContent(),'マッドショット');
 await page.click('[data-tab=strategy]');await page.locator('details').filter({has:page.locator('#strategyEnemy')}).locator('summary').click();await page.fill('#strategyEnemy',csv);await page.locator('#strategyEnemy').blur();
 await page.selectOption('#strategySelf','2');await page.getByText('初手→交代→後追い（限定モデル）',{exact:true}).click();await page.selectOption('#strategyLead','1');await page.selectOption('#strategyCloser','3');
 await page.check('#includeBranch');
 await page.click('#runStrategy');await page.waitForFunction(()=>document.getElementById('strategyResult').textContent.includes('詳細条件 9/9'),{timeout:20000});
 assert((await page.textContent('#strategyResult')).includes('完全な3対3'));
 assert((await page.textContent('#strategyResult')).includes('後追い 5/5'));
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Mobile page must not overflow horizontally');
 await page.click('[data-tab=settings]');await page.click('#save');await page.waitForFunction(()=>document.getElementById('status').textContent.includes('保存済み'));
 await page.click('[data-tab=strategy]');await page.click('#runStrategy');await page.waitForFunction(()=>document.getElementById('status').textContent.includes('計算完了'));
 assert((await page.textContent('#strategyResult')).includes('新規条件 0'));
 // Ensure a late response cannot replace results after an edit.
 await page.click('#runStrategy');await page.fill('#workFraction','16');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('以前の入力の結果は表示しません'));
 // Save two independent named snapshots and verify restored opponent, IV and strategy.
 await page.fill('#partyName','大会A');await page.click('#saveAs');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会A'));
 const partyA=await page.inputValue('#saved');
 const aOwn=await page.locator('#members [data-field=atk]').first().inputValue();
 const aStrategy=await page.inputValue('#strategyEnemy');
 await page.click('[data-tab=compose]');
 await page.locator('#members details').first().evaluate(el=>el.open=true);
 await page.locator('#members [data-field=atk]').first().fill(aOwn==='7'?'8':'7');
 await page.click('[data-tab=selection]');
 await page.locator('#selection details.mon').first().evaluate(el=>el.open=true);
 await page.locator('#selection [data-field=atk]').first().fill('9');
 await page.fill('#partyName','大会B');await page.click('#saveAs');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会B'));
 const partyB=await page.inputValue('#saved');assert.notEqual(partyA,partyB);
 await page.selectOption('#saved',partyA);await page.click('#load');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会A'));
 assert.equal(await page.locator('#members [data-field=atk]').first().inputValue(),aOwn);
 assert.equal(await page.inputValue('#strategyEnemy'),aStrategy);
 assert.equal(await page.locator('#selection [data-field=atk]').first().inputValue(),'0','Restore the attack IV provided by the Japanese CSV');
 await page.selectOption('#saved',partyB);await page.click('#load');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会B'));
 assert.equal(await page.locator('#selection [data-field=atk]').first().inputValue(),'9');
 assert.equal(await page.locator('#members [data-field=atk]').first().inputValue(),aOwn==='7'?'8':'7');
 await page.click('[data-tab=settings]');
 assert.equal(await page.inputValue('#metaWeights select[data-species=quagsire]'),'4');
 // Real authenticated search from bundled meta; apply one suggested change if improved.
 // Autocomplete the whole party, compare endpoints and inspect a real 2-2 heatmap.
 await page.click('[data-tab=compose]');
 await page.click('#autoComplete');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('計算完了'),{timeout:60000});
 assert((await page.textContent('#swapAdvice')).includes('自動補完の最終候補'));
 assert((await page.textContent('#weakResult')).includes('構築に使った詳細戦略'));
 assert((await page.textContent('#weakResult')).includes('一次探索'));
 assert((await page.textContent('#weakResult')).includes('通常技の圧力'));
 assert((await page.textContent('#weakResult')).includes('ゲージ技を受ける役割'));
 await page.waitForFunction(()=>{
  const r=document.getElementById('swapAdvice').getBoundingClientRect();
  return !document.getElementById('weakness').hidden&&r.top>=0&&r.top<100;
 });
 assert(await page.locator('#swapAdvice .completion-card').count()>=1);
 assert(await page.locator('#swapAdvice .completion-card').count()<=3);
 const firstPlan=page.locator('#swapAdvice .completion-card').first();
 await firstPlan.getByRole('button',{name:'弱点を視覚化'}).click();
 const comparison=page.locator('.party-comparison');
 assert(await comparison.locator('table.heatmap tbody tr').count()>=1,'comparison must include real meta opponents');
 assert(await comparison.locator('table.heatmap tbody tr').count()<=8,'page remains compact');
 for(const [own,enemy] of [['0','0'],['1','1'],['2','2'],['0','2'],['2','0']]){
  await comparison.getByLabel('自分のシールド',{exact:true}).selectOption(own);
  await comparison.getByLabel('相手のシールド',{exact:true}).selectOption(enemy);
  assert.equal(await comparison.locator('table').getAttribute('data-shields'),own+'-'+enemy);
  assert(!(await comparison.locator('tbody').textContent()).includes('未計算'));
 }
 await comparison.getByLabel('比較表示',{exact:true}).selectOption('slots');
 assert.equal(await comparison.evaluate(el=>el.open),true);
 assert.equal(await comparison.locator('table tbody tr').count(),6);
 assert.equal(await comparison.locator('table tbody tr').first().locator('td').count(),2);
 assert.equal(await comparison.locator('table tbody tr').first().locator('td strong').count(),2);
 assert(!/初 |案 |[1-6]枠/.test(await comparison.locator('table').textContent()));
 for(const width of [360,390]){
  await page.setViewportSize({width,height:844});
  assert(await comparison.evaluate(el=>el.getBoundingClientRect().width>=innerWidth-2),'comparison uses full viewport');
  assert(await comparison.locator('td strong').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=18),'Pokemon names remain readable');
  assert(await comparison.locator('td span').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=22),'ratings remain readable');
  assert.equal(await comparison.evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
 }
 await comparison.getByRole('button',{name:'次の相手'}).click();
 assert((await comparison.locator('.compare-paging').textContent()).includes('2–2'));
 await comparison.getByLabel('自分のシールド',{exact:true}).selectOption('1');
 assert((await comparison.locator('.compare-paging').textContent()).includes('2–2'),'shield change keeps opponent');
 await comparison.getByLabel('比較表示',{exact:true}).selectOption('summary');
 assert(await comparison.locator('tbody tr').count()<=8);
 await comparison.getByLabel('比較表示',{exact:true}).selectOption('slots');
 assert.equal(await comparison.locator('.compare-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true,'comparison fits mobile width without horizontal scrolling');
 const rowCount=await comparison.locator('tbody tr').count();assert(rowCount<=8);
 await comparison.getByLabel('比較する提案',{exact:true}).selectOption('0');
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>!document.querySelector('.party-comparison').open&&document.body.style.overflow==='');
 assert.equal(await comparison.evaluate(el=>el.open),false);
 assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
 await firstPlan.getByRole('button',{name:'弱点を視覚化'}).click();
 await comparison.getByRole('button',{name:'比較を閉じる'}).click();
 await page.waitForFunction(()=>!document.querySelector('.party-comparison').open&&document.body.style.overflow==='');
 assert.equal(await comparison.evaluate(el=>el.open),false);
 assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
 const history=firstPlan.locator('details').filter({hasText:'入れ替え履歴'});
 if(await history.count()){
  await history.locator('summary').click();
  assert((await history.textContent()).includes('交換直前の6体・2枚対2枚'));
  assert((await history.textContent()).includes('改善した相手'));
 }
 // Visual controls must not invalidate the proposal before applying it.

 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Heatmap must fit mobile viewport with own scrolling');
 await firstPlan.getByRole('button',{name:'この6体を反映'}).click();
 assert((await page.textContent('#partyState')).includes('未保存の変更あり'));
 assert((await page.textContent('#status')).includes('再分析'));
 await page.click('[data-tab=compose]');
 await page.click('#recommend');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('計算完了'),{timeout:40000});
 assert((await page.textContent('#swapAdvice')).includes('次に何をすればよい？'));
 assert((await page.textContent('#swapAdvice')).includes('仮候補'));
 const proposals=page.locator('#swapAdvice button');
 if(await proposals.count()){
  const old=await page.locator('#members [data-field=species]').allTextContents();
  await proposals.first().click();
  assert((await page.textContent('#status')).includes('まだ保存していません'));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.equal(await page.textContent('#partyState'),'未保存の変更あり（上部の保存・上書きで記録）');
 }
 // Candidate build uses the same refinement and can explicitly opt out.
 await page.click('[data-tab=compose]');
 await page.evaluate(text=>{const el=document.getElementById('pool');el.value=text;
  el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));},csv+'\nprimeape,COUNTER,ICE_PUNCH,CLOSE_COMBAT');
 await page.click('#build');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('計算完了'),{timeout:60000});
 assert((await page.textContent('#weakResult')).includes('構築に使った詳細戦略'));
 assert(await page.locator('#weakResult .completion-card').count()<=3);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 const refinedApply=page.locator('#weakResult .completion-card button:not([disabled])').first();
 if(await refinedApply.count()){
  await refinedApply.click();
  assert((await page.textContent('#status')).includes('再分析'));
 }
 await page.click('[data-tab=compose]');await page.uncheck('#strategyRefinement');
 await page.click('#save');await page.waitForFunction(()=>document.getElementById('status').textContent.includes('保存済み'));
 await page.check('#strategyRefinement');await page.click('#load');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('読み込みました'));
 assert.equal(await page.isChecked('#strategyRefinement'),false);
 await page.click('#build');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('計算完了'),{timeout:60000});
 assert(!(await page.textContent('#weakResult')).includes('構築に使った詳細戦略'));
 assert((await page.textContent('#weakResult')).includes('通常技の圧力：未評価'));
 assert.equal(errors.length,0,errors.join('\n'));
 const out=process.env.STRATEGY_SCREENSHOT_DIR;
 if(out){fs.mkdirSync(out,{recursive:true});await page.screenshot({path:out+'/strategy-mobile.png',fullPage:true});}
 console.log('Mobile 390px: real authenticated gateway/worker/engine, all 4 features, 5 branches, named own/enemy save and restore, Japanese moves and weights, actionable swaps, iterative completion and matchup heatmap, cache reuse and stale-response guard passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
