// Real browser fixtures: no production auth and no live battle calculations.
const fs=require('fs'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8').split("HTML = r'''")[1].split("'''")[0];
const candidate={species:'quagsire',fast:'MUD_SHOT',charged1:'AQUA_TAIL',charged2:'STONE_EDGE'};
const species={name:'Quagsire',name_ja:'ヌオー',nickname_code:'Quag',types:['water','ground'],fastMoves:['MUD_SHOT'],chargedMoves:['AQUA_TAIL','STONE_EDGE','ICE_BEAM'],default_moves:candidate};
const calls=[];
function result(c){return {state:'done',complete:true,run_ref:'fixture'+calls.length,candidate:c,meta_sha256:'a'.repeat(64),calculation_version:'e'.repeat(64),batch_mode:'simple',selection:{english_name:'Quagsire',candidate_ivs:['0/11/12'],unmatched_focus:[],dominated_by:{},review_candidates:[],recommendations:[{rank:1,ivs:'0/11/12',grade:'S候補',role:'Fixture',evidence:[],evidence_count:0,search_string:'Quagsire&0attack&3defense&3hp',equivalent_candidates:[]}],moveset_summary:{version:1,axis_sha256:'f'.repeat(64),available_wins:'1',mean_rating:550,iv_mean_ratings:{'0/11/12':550},rating_count:6}}};}
const server=http.createServer(async(req,res)=>{
 res.setHeader('Content-Type',req.url.startsWith('/app-api/')?'application/json':'text/html; charset=utf-8');
 if(!req.url.startsWith('/app-api/')){res.end(html);return;}
 let body='';for await(const chunk of req)body+=chunk;const data=JSON.parse(body||'{}'),path=req.url.slice('/app-api/'.length);let out;
 if(path==='catalog')out={ready:true,species:{quagsire:species},app_presets:[{name:'ヌオー',...candidate}]};
 else if(path==='meta-presets')out={items:[{id:'legacy',name:'標準メタ',rows:1,default:true,available:true,sha256:'a'.repeat(64),source:'legacy'}],default_id:'legacy',revision:0};
 else if(path==='run'){calls.push(data);out=result(data.candidate);}
 else{res.statusCode=400;out={error:'Unexpected fixture call '+path};}
 res.end(JSON.stringify(out));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||undefined});
  for(const viewport of [{width:390,height:844},{width:1280,height:900}]){
   const context=await browser.newContext({viewport}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
   const url=`http://127.0.0.1:${server.address().port}/app`;await page.goto(url);await page.waitForSelector('#workspace:not([hidden])');
   await page.locator('#moveSettings summary').first().click();await page.locator('#addMoveset').click();await page.selectOption('#charged2','ICE_BEAM');await page.locator('#addMoveset').click();
   assert.equal(await page.locator('#savedMovesets input').count(),2);
   await page.reload();await page.waitForSelector('#workspace:not([hidden])');await page.locator('#moveSettings summary').first().click();assert.equal(await page.locator('#savedMovesets input').count(),2,'Saved profiles survive reload');
   await page.locator('#autoMoves').uncheck();await page.locator('#ivs').fill('0,11,12');const before=calls.length;await page.locator('#run').click();
   await page.waitForFunction(()=>!document.getElementById('run').disabled&&!document.getElementById('results').hidden);
   assert.equal(calls.length-before,2);assert.equal(await page.locator('#results').evaluate(e=>document.activeElement===e),true);
   assert((await page.locator('#results').innerText()).includes('検索式'));assert((await page.locator('#results').innerText()).includes('2 / 3構成'));
   assert(await page.locator('#results').evaluate(e=>e.getBoundingClientRect().top<document.getElementById('metaManager').getBoundingClientRect().top));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal overflow');assert.deepEqual(errors,[]);
   await context.close();
  }
  console.log('Chromium mobile/desktop: register multiple profiles, reload, execute exactly two, render searches before custom meta and focus results: OK');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
