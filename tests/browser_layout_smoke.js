// Real DOM/mobile layout smoke test. API responses are fixtures; no user data or battles.
const fs=require('fs'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8').split("HTML = r'''")[1].split("'''")[0];
const raw='個体値厳選\n# ヌオー\n0,11,12 CP717 | ウパー';
const candidate={species:'quagsire',fast:'MUD_SHOT',charged1:'AQUA_TAIL',charged2:'STONE_EDGE'};
const job={name:'ヌオー',candidate,ivs:'0,11,12',candidate_count:1,warnings:[],source_sections:[1],source_records:[{ivs:'0/11/12',cp:717,species:'wooper',search_string:'Wooper&0attack&3defense&3hp&cp717'}]};
let battles=0;
const server=http.createServer((req,res)=>{
 if(req.url.startsWith('/app-api/')){
  const path=req.url.slice('/app-api/'.length);let data;
  if(path==='catalog')data={ready:true,species:{quagsire:{name:'Quagsire',name_ja:'ヌオー',nickname_code:'Quag',fastMoves:['MUD_SHOT'],chargedMoves:['AQUA_TAIL','STONE_EDGE']}},app_presets:[{name:'ヌオー',...candidate}]};
  else if(path==='meta-presets')data={items:[{id:'legacy',name:'標準メタ',rows:87,default:true,available:true,sha256:'a'.repeat(64),source:'legacy'}],default_id:'legacy',revision:0};
  else if(path==='import')data={jobs:[job]};
  else{if(path==='run')battles++;res.writeHead(400);res.end('{}');return;}
  res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));
 }else{res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(html);}
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||undefined});
  for(const viewport of [{width:390,height:844},{width:1280,height:900}]){
   const page=await browser.newPage({viewport});const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(`http://127.0.0.1:${server.address().port}/app#ivdata=${Buffer.from(raw).toString('base64url')}`);
   await page.waitForFunction(()=>document.getElementById('ivs').value==='0,11,12');
   await page.waitForFunction(()=>Math.abs(document.getElementById('comparisonSettings').getBoundingClientRect().top-16)<24);
   assert.equal(await page.evaluate(()=>document.activeElement.id),'comparisonSettings');
   assert.equal(await page.locator('#autoMoves').isChecked(),true);
   assert.equal(await page.locator('#comparisonSettings #moveSettings').count(),1);
   assert(await page.locator('#results').evaluate(e=>Boolean(e.compareDocumentPosition(document.getElementById('metaManager'))&Node.DOCUMENT_POSITION_FOLLOWING)));
   assert.equal(await page.locator('#moveStrategy').inputValue(),'smart');
   assert(await page.locator('#moveSettings').evaluate(e=>e.nextElementSibling.textContent.includes('自動推薦の基準を調整')));
   assert(await page.locator('#metaManager').evaluate(e=>e.nextElementSibling.textContent.includes('1. ポケモンと個体値')));
   assert.equal(await page.locator('#moveSettings #fast').count(),1);
   assert(await page.locator('#run').evaluate(e=>e.getBoundingClientRect().height>=48));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal overflow');
   assert(!page.url().includes('ivdata='));assert.deepEqual(errors,[]);
   await page.close();
  }
  assert.equal(battles,0);console.log('Chromium mobile/desktop: auto-import, focus/scroll, last move settings and touch targets: OK');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
