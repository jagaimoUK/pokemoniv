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
 const csv=JSON.parse(fs.readFileSync('tests/fixtures/strategy_rows.json')).map(x=>[x.species,x.fast,x.charged1,x.charged2,x.atk,x.def,x.hp].join(',')).join('\n');
 await page.click('[data-tab=compose]');await page.locator('#members details').first().locator('summary').click();
 const speciesInput=page.locator('#members [data-field=species]').first();await speciesInput.fill('ぬお');await page.locator('#members .suggestions button').filter({hasText:'ヌオー'}).first().click();
 assert.equal(await speciesInput.inputValue(),'ヌオー');assert.equal(await page.locator('#members [data-field=fast]').first().evaluate(el=>el.tagName),'SELECT');
 await page.click('[data-tab=selection]');await page.locator('#selection').getByRole('button',{name:'ポケモンを追加',exact:true}).click();await page.locator('#selection [data-field=species]').fill('Azumarill');await page.locator('#selection .suggestions button').first().click();assert((await page.inputValue('#enemy')).startsWith('azumarill,'));
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
 assert.equal(await page.locator('#selection [data-field=atk]').first().inputValue(),'');
 await page.selectOption('#saved',partyB);await page.click('#load');
 await page.waitForFunction(()=>document.getElementById('partyState').textContent.includes('大会B'));
 assert.equal(await page.locator('#selection [data-field=atk]').first().inputValue(),'9');
 assert.equal(await page.locator('#members [data-field=atk]').first().inputValue(),aOwn==='7'?'8':'7');
 // Real authenticated search from bundled meta; apply one suggested change if improved.
 // Autocomplete the whole party, compare endpoints and inspect a real 2-2 heatmap.
 await page.click('[data-tab=compose]');
 await page.click('#autoComplete');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('計算完了'),{timeout:60000});
 assert((await page.textContent('#swapAdvice')).includes('自動補完の最終候補'));
 assert(await page.locator('#swapAdvice .completion-card').count()>=1);
 assert(await page.locator('#swapAdvice .completion-card').count()<=3);
 const firstPlan=page.locator('#swapAdvice .completion-card').first();
 await firstPlan.getByRole('button',{name:'弱点を視覚化'}).click();
 assert(await firstPlan.locator('table.heatmap tbody tr').count()>=1,'heatmap must include real meta opponents');
 assert.equal(await firstPlan.locator('table.heatmap tbody tr').first().locator('td').count(),6);
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
 assert.equal(errors.length,0,errors.join('\n'));
 const out=process.env.STRATEGY_SCREENSHOT_DIR;
 if(out){fs.mkdirSync(out,{recursive:true});await page.screenshot({path:out+'/strategy-mobile.png',fullPage:true});}
 console.log('Mobile 390px: real authenticated gateway/worker/engine, all 4 features, 5 branches, named own/enemy save and restore, actionable swaps, iterative completion and matchup heatmap, cache reuse and stale-response guard passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
