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
 assert.equal(errors.length,0,errors.join('\n'));
 const out=process.env.STRATEGY_SCREENSHOT_DIR;
 if(out){fs.mkdirSync(out,{recursive:true});await page.screenshot({path:out+'/strategy-mobile.png',fullPage:true});}
 console.log('Mobile 390px: real authenticated gateway/worker/engine, all 4 features, 5 branches, save, cache reuse and stale-response guard passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
