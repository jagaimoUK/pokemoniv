const {chromium}=require('playwright'),assert=require('assert'),http=require('http'),fs=require('fs');
const html=fs.readFileSync('/tmp/flashcards-preview.html','utf8'),data=JSON.parse(fs.readFileSync('data/flashcard_catalog.json','utf8'));
let privateCalls=0,publicCalls=0;
const server=http.createServer((req,res)=>{
 if(req.url==='/reader-api/v1/flashcards'){publicCalls++;res.writeHead(304);res.end();return;}
 if(req.url==='/app-api/flashcards'){privateCalls++;res.writeHead(401);res.end('{}');return;}
 res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(html);
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;try{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||undefined});
 for(const viewport of [{width:390,height:844},{width:320,height:640},{width:1280,height:900}]){
  const page=await browser.newPage({viewport});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const start=performance.now();await page.goto(`http://127.0.0.1:${server.address().port}/flashcards`);await page.locator('#home').waitFor({state:'visible'});
  console.log('Fresh home ms',viewport.width,Math.round(performance.now()-start));
  assert.equal(await page.locator('#deck option').count(),10);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.click('#start');await page.locator('#card').waitFor({state:'visible'});assert(await page.locator('#correct').isDisabled());
  await page.click('#card');await page.click('#again');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('2 /'));
  assert((await page.locator('#status').textContent()).includes('見直し'));await page.click('#undo');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('1 /'));assert(await page.locator('#answer').isVisible());
  await page.click('#correct');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('2 /'));
  await page.reload();await page.locator('#home').waitFor({state:'visible'});await page.click('#resume');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('2 /'));
  await page.click('#card');const box=await page.locator('#card').boundingBox();await page.mouse.move(box.x+box.width*.35,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.8,box.y+box.height*.5);await page.mouse.up();await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('3 /'));
  assert((await page.locator('#status').textContent()).includes('正解'));
  const before=await page.evaluate(()=>new Promise(resolve=>{const req=indexedDB.open('pokemon-move-flashcards',1);req.onsuccess=()=>{const q=req.result.transaction('kv').objectStore('kv').get('session');q.onsuccess=()=>{resolve(q.result.cards.map(c=>[c.species,c.fast,c.charged].join('|')));req.result.close();};};}));
  for(let i=2;i<10;i++){await page.click('#card');assert.equal((await page.locator('#answer').textContent()).split(' → ').length,4);await page.click('#correct');await page.waitForFunction(index=>document.querySelector('#progress').textContent.startsWith(index<10?`${index+1} /`:'10問'),i+1);}
  await page.locator('#completed').waitFor({state:'visible'});assert(await page.locator('#finishHome').isVisible());assert(await page.locator('#replay').isVisible());
  await page.click('#replay');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('1 /'));
  const after=await page.evaluate(()=>new Promise(resolve=>{const req=indexedDB.open('pokemon-move-flashcards',1);req.onsuccess=()=>{const q=req.result.transaction('kv').objectStore('kv').get('session');q.onsuccess=()=>{resolve(q.result.cards.map(c=>[c.species,c.fast,c.charged].join('|')));req.result.close();};};}));
  assert.deepEqual([...before].sort(),[...after].sort());assert.notDeepEqual(before,after);
  await page.click('#homeBtn');await page.click('#create');await page.fill('#deckName','技の練習');await page.fill('#search','nidoqueen');await page.locator('#results button').first().click();assert(await page.locator('#fastOptions input').count()>1);assert(await page.locator('#chargedOptions input').count()>2);
  await page.locator('#fastOptions input').first().check();await page.locator('#chargedOptions input').last().check();await page.click('#addMon');await page.click('#saveDeck');await page.locator('#home').waitFor({state:'visible'});assert(await page.locator('#deck option').count()===11);
  await page.reload();await page.locator('#home').waitFor({state:'visible'});assert(await page.locator('#deck option').count()===11);
  await page.click('#create');await page.fill('#search','ニドクイン');assert(await page.locator('#results button').count()>0);await page.click('#cancelEdit');
  const geometry=await page.locator('#start').boundingBox();assert(geometry.height>=48);assert.deepEqual(errors,[]);
  await page.evaluate(()=>new Promise((resolve,reject)=>{const open=indexedDB.open('pokemon-move-flashcards',1);open.onsuccess=()=>{const db=open.result,read=db.transaction('kv').objectStore('kv').get('decks');read.onsuccess=()=>{let chosen,deck;for(const d of read.result){chosen=Flashcards.deckCards(d,FLASHCARD_BOOTSTRAP).items.find(c=>Flashcards.alternatives(c,FLASHCARD_BOOTSTRAP.moves).length);if(chosen){deck=d;break;}}if(!chosen){reject(Error('No heavy-first fixture'));return;}const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put({deck:deck.id,cards:[chosen],index:0},'session');tx.objectStore('kv').put(null,'undo');tx.oncomplete=()=>{db.close();resolve();};};};}));
  await page.reload();await page.locator('#home').waitFor({state:'visible'});await page.click('#resume');await page.click('#card');
  assert(await page.locator('.alternate-counts').count()>0);for(const row of await page.locator('.alternate-counts').allTextContents())assert.equal(row.split(' → ').length,4);
  await page.click('#correct');await page.locator('#completed').waitFor({state:'visible'});await page.click('#finishHome');await page.locator('#home').waitFor({state:'visible'});
  if(viewport.width===390)await page.screenshot({path:'/tmp/flashcards-home.png'});
  console.log('Mobile/desktop persistence, reveal/grade/undo/swipe/resume, bilingual search, custom multi-moves, no overflow: PASS',viewport.width);
  await page.close();
 }
 console.log({privateCalls,publicCalls});
}finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}})().catch(e=>{console.error(e);process.exitCode=1});
