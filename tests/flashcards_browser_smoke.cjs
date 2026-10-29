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
  await page.click('#undo');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('1 /'));assert(await page.locator('#answer').isVisible());
  await page.click('#correct');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('2 /'));
  await page.reload();await page.locator('#home').waitFor({state:'visible'});await page.click('#resume');await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('2 /'));
  await page.click('#card');const box=await page.locator('#card').boundingBox();await page.mouse.move(box.x+box.width*.35,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.8,box.y+box.height*.5);await page.mouse.up();await page.waitForFunction(()=>document.querySelector('#progress').textContent.startsWith('3 /'));
  await page.click('#homeBtn');await page.click('#create');await page.fill('#deckName','技の練習');await page.fill('#search','nidoqueen');await page.locator('#results button').first().click();assert(await page.locator('#fastOptions input').count()>1);assert(await page.locator('#chargedOptions input').count()>2);
  await page.locator('#fastOptions input').first().check();await page.locator('#chargedOptions input').last().check();await page.click('#addMon');await page.click('#saveDeck');await page.locator('#home').waitFor({state:'visible'});assert(await page.locator('#deck option').count()===11);
  await page.reload();await page.locator('#home').waitFor({state:'visible'});assert(await page.locator('#deck option').count()===11);
  await page.click('#create');await page.fill('#search','ニドクイン');assert(await page.locator('#results button').count()>0);await page.click('#cancelEdit');
  const geometry=await page.locator('#start').boundingBox();assert(geometry.height>=48);assert.deepEqual(errors,[]);
  if(viewport.width===390)await page.screenshot({path:'/tmp/flashcards-home.png'});
  console.log('Mobile/desktop persistence, reveal/grade/undo/swipe/resume, bilingual search, custom multi-moves, no overflow: PASS',viewport.width);
  await page.close();
 }
 console.log({privateCalls,publicCalls});
}finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}})().catch(e=>{console.error(e);process.exitCode=1});
