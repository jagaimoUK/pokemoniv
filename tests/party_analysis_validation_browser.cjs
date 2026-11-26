'use strict';
// Isolated real-Chromium party validation test. Synthetic Mega lives only in the fixture.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');

(async()=>{
 const server=spawn('python',['tests/party_strategy_fixture_server.py'],{
  stdio:['ignore','pipe','pipe'],
  env:{...process.env,PARTY_TEST_SYNTHETIC_MEGA:'1'}
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
  const errors=[];let requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',request=>{
   if(request.url().endsWith('/app-api/party/start')) requests.push(request.postDataJSON());
  });

  await page.goto(config.url+'/app/party');
  await page.fill('#key',config.key);
  await page.click('#login');
  await page.waitForSelector('#workspace:not([hidden])');

  // Case 1: the page initially has six blank cards. The API must not be called.
  await page.click('#analyze');
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('1枠目のポケモンが未選択'));
  assert.equal(requests.length,0,'Blank party must not call party/start');

  // Load a real fixture party so the next checks use the actual UI and engine.
  await page.selectOption('#saved',await page.locator('#saved option').nth(1).getAttribute('value'));
  await page.click('#load');
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('読み込みました'));
  const speciesInputs=page.locator('#members [data-field=species]');
  assert.equal(await speciesInputs.count(),6);
  const original=await page.evaluate(()=>getMon());

  // Case 1b: editing the fourth card to blank must identify slot 4.
  await page.locator('#members details.mon').nth(3).evaluate(e=>e.open=true);
  await speciesInputs.nth(3).fill('');
  await page.click('#analyze');
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('4枠目のポケモンが未選択'));
  assert.equal(requests.length,0,'Fourth blank must not call party/start');

  // Restore the original six via the existing saved-party UI.
  await page.click('#load');
  await page.waitForFunction(ids=>getMon().every((p,i)=>p.species===ids[i]),original.map(p=>p.species));
  const restored=await page.evaluate(()=>getMon());
  assert.deepEqual(restored.map(p=>p.species),original.map(p=>p.species));

  // Case 2/3: regular six, visible input IDs and server request match.
  async function startAndInspect(){
   const before=requests.length;
   const visible=await page.locator('#members [data-field=species]').evaluateAll(
    inputs=>inputs.map(x=>({display:x.value,id:x.dataset.species}))
   );
   const started=page.waitForResponse(r=>r.url().endsWith('/app-api/party/start'));
   await page.click('#analyze');
   const response=await started;
   assert.equal(response.status(),200,await response.text());
   const result=await response.json();
   assert.equal(result.status,'queued');
   assert.equal(requests.length,before+1);
   const sent=requests[before].members;
   assert.deepEqual(sent.map(x=>x.species),visible.map(x=>x.id));
   assert(visible.every(x=>x.id&&x.display),'Every sent ID has a visible name');
   return {result,visible,sent};
  }
  const regular=await startAndInspect();
  assert.equal(regular.sent.length,6);
  // Wait for the worker to release its active-job lock before submitting Mega.
  await page.waitForFunction(()=>activeJob===null,null,{timeout:90000});
  assert(!/未登録ポケモン/.test(await page.textContent('#status')));

  // Use the real selection UI, not a fabricated POST body.
  await page.locator('#members details.mon').nth(0).evaluate(e=>e.open=true);
  await speciesInputs.nth(0).fill('Synthetic Mega Quagsire');
  await page.locator('#members details.mon').nth(0)
   .locator('.suggestions button').filter({hasText:'Synthetic Mega Quagsire'}).first().click();
  assert.equal(await speciesInputs.nth(0).getAttribute('data-species'),'quagsire_mega');
  await page.selectOption('#partyRuleset','great_mega');
  const mega=await startAndInspect();
  assert.equal(mega.sent[0].species,'quagsire_mega');
  assert.equal(mega.sent[0].mega_level,3,'Mega level must remain in its own field');
  assert.equal(mega.sent.length,6);
  await page.waitForFunction(()=>activeJob===null,null,{timeout:90000});
  assert(!/未登録ポケモン/.test(await page.textContent('#status')));
  assert.deepEqual(errors,[],'No page errors');
  console.log('Party browser validation PASS: blank slots suppress POST; normal and synthetic Mega six start; visible names match sent IDs');
 }finally{
  if(browser)await browser.close();
  server.kill();
 }
})().catch(err=>{console.error(err);process.exitCode=1;});
