'use strict';
// Isolated Chromium E2E test for Party Builder ownership sync (#loadOwnedPool + handoff bridge).
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');

(async()=>{
 const server=spawn('python',['tests/party_strategy_fixture_server.py'],{
  stdio:['ignore','pipe','pipe'],
  env:{...process.env,PARTY_TEST_OWNED_SYNC:'1'}
 });
 let browser;
 try{
  const config=await new Promise((resolve,reject)=>{
   let buffer='',stderr='';
   server.stdout.on('data',chunk=>{
    buffer+=chunk;
    const at=buffer.indexOf('\n');
    if(at>=0){try{resolve(JSON.parse(buffer.slice(0,at)))}catch(e){reject(e)}}
   });
   server.stderr.on('data',chunk=>{stderr+=chunk.toString().slice(-500)});
   server.on('exit',code=>reject(Error('Fixture exited '+code+': '+stderr.slice(-1000))));
  });
  browser=await chromium.launch({
   headless:true,executablePath:process.env.STRATEGY_CHROMIUM_PATH||undefined,
   args:['--no-sandbox','--disable-dev-shm-usage']
  });
  const page=await browser.newPage({viewport:{width:390,height:844}});
  page.setDefaultTimeout(10000);
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));

  await page.goto(config.url+'/app/party');
  await page.fill('#key',config.key);
  await page.click('#login');
  await page.waitForSelector('#workspace:not([hidden])');

  // 1. Click "手持ち一覧から候補を読み込む" and verify normal + Mega Sableye are loaded into #pool
  const ownedResPromise=page.waitForResponse(r=>r.url().endsWith('/app-api/party/owned-candidates'));
  await page.click('#loadOwnedPool');
  const ownedRes=await ownedResPromise;
  assert.equal(ownedRes.status(),200,await ownedRes.text());
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('手持ちから 2件（うちメガ個体 1件）を取得'));
  const poolRows=await page.evaluate(()=>partyRosterRows('pool'));
  assert.equal(poolRows.length,2);
  const sabPool=poolRows.find(r=>r.species==='sableye_mega');
  assert.ok(sabPool,'sableye_mega must be in candidate pool');
  assert.equal(sabPool.mega_level,3);
  assert.equal(sabPool.atk,15);
  assert.equal(sabPool.level_override,27);

  // 2. Simulate one-tap handoff from /app/missing via localStorage
  await page.evaluate(()=>{
   localStorage.setItem('pvpoke_party_handoff_v1',JSON.stringify([{
    species:'sableye_mega',
    fast:'SHADOW_CLAW',
    charged1:'FOUL_PLAY',
    charged2:'POWER_GEM',
    atk:15,def:15,hp:15,
    level_override:27,
    mega_level:3
   }]));
  });
  await page.reload();
  await page.waitForSelector('#workspace:not([hidden])');
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('手持ち・不足分析から 1件'));
  const firstSpecies=await page.locator('#members [data-field=species]').nth(0).getAttribute('data-species');
  assert.equal(firstSpecies,'sableye_mega','Handoff must populate first blank slot with sableye_mega');
  const handoffRemaining=await page.evaluate(()=>localStorage.getItem('pvpoke_party_handoff_v1'));
  assert.equal(handoffRemaining,null,'Handoff key must be consumed after loading');
  const firstMon=await page.evaluate(()=>getMon()[0]);
  assert.equal(firstMon.species,'sableye_mega');
  assert.equal(firstMon.mega_level,3);
  assert.equal(firstMon.atk,15);
  assert.equal(firstMon.level_override,27);

  assert.deepEqual(errors,[],'No page errors');
  console.log('Party ownership sync browser PASS: API pool load and localStorage handoff (with Mega Sableye) succeeded');
 }finally{
  if(browser)await browser.close();
  server.kill();
 }
})().catch(err=>{console.error(err);process.exitCode=1;});
