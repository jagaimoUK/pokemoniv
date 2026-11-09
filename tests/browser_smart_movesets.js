// Real browser fixtures: no production auth and no live battle calculations.
const fs=require('fs'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8').split("HTML = r'''")[1].split("'''")[0];
const candidate={species:'oinkologne',fast:'TACKLE',charged1:'BODY_SLAM',charged2:'DIG'};
const male={name:'Oinkologne',name_ja:'パフュートン',nickname_code:'OinkM',types:['normal'],fastMoves:['TACKLE'],chargedMoves:['BODY_SLAM','DIG','TRAILBLAZE'],default_moves:candidate};
const female={...male,name:'Oinkologne (Female)',name_ja:'パフュートン(メス)',nickname_code:'OinkF',default_moves:{...candidate,species:'oinkologne_female'}};
const calls=[];
function result(c){return {state:'done',complete:true,run_ref:'fixture'+calls.length,candidate:c,meta_sha256:'a'.repeat(64),calculation_version:'e'.repeat(64),batch_mode:calls.at(-1).batch_mode,selection:{english_name:'Oinkologne',candidate_ivs:['0/11/12'],unmatched_focus:[],dominated_by:{},review_candidates:[],recommendations:[{rank:1,ivs:'0/11/12',grade:'S候補',role:'Fixture',evidence:[],evidence_count:0,search_string:'Oinkologne&0attack&3defense&3hp',equivalent_candidates:[]}],moveset_summary:{version:1,axis_sha256:'f'.repeat(64),available_wins:'1',mean_rating:550,iv_mean_ratings:{'0/11/12':550},rating_count:6}}};}
const server=http.createServer(async(req,res)=>{
 res.setHeader('Content-Type',req.url.startsWith('/app-api/')?'application/json':'text/html; charset=utf-8');
 if(!req.url.startsWith('/app-api/')){res.end(html);return;}
 let body='';for await(const chunk of req)body+=chunk;const data=JSON.parse(body||'{}'),path=req.url.slice('/app-api/'.length);let out;
 if(path==='catalog')out={ready:true,species:{oinkologne:male,oinkologne_female:female},app_presets:[{name:'パフュートン',...candidate}]};
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
   await page.addInitScript(profile=>{
    if(!localStorage.getItem('pvpoke-app-movesets-v1')){
     localStorage.setItem('pvpoke-app-movesets-v1',JSON.stringify({oinkologne:[profile]}));
    }
   },candidate);
   const url=`http://127.0.0.1:${server.address().port}/app`;
   async function openSettings(){
    await page.locator('#workspace:not([hidden])').waitFor();
    await page.locator('#selectionSettingsOpen').click();
    await page.locator('#selectionModeFilter').fill('パフュートン');
   }
   await page.goto(url);await openSettings();
   const name=page.getByRole('button',{name:'パフュートン（オス）',exact:true});
   const femaleName=page.getByRole('button',{name:'パフュートン(メス)',exact:true});
   const panel=page.locator('#species-movesets-oinkologne'),femalePanel=page.locator('#species-movesets-oinkologne_female');
   assert.equal(await page.locator('.species-mode-row').count(),2);
   await name.click();assert.equal(await name.getAttribute('aria-expanded'),'true');
   assert.equal(await panel.locator('input:checked').count(),1,'Old browser storage is visible in settings');
   await page.getByRole('switch',{name:'パフュートン（オス）の詳細厳選'}).check();
   assert(await panel.isVisible(),'Changing mode leaves the movesets open');
   await femaleName.click();assert.equal(await femalePanel.locator('input').count(),0);
   await panel.getByRole('button',{name:'＋ 技構成を追加'}).click();
   await panel.getByLabel('ゲージ技2').selectOption('TRAILBLAZE');
   await panel.getByRole('button',{name:'登録',exact:true}).click();
   assert.equal(await panel.locator('input:checked').count(),2);
   assert.match(await panel.getByRole('status').innerText(),/技構成を登録しました/);
   assert.equal(await femalePanel.locator('input').count(),0);
   await name.click();assert.equal(await name.getAttribute('aria-expanded'),'false');
   assert.equal(await panel.isVisible(),false);
   assert(await page.locator('#selectionSettings').evaluate(e=>e.scrollWidth<=e.clientWidth),'Settings fit the viewport');
   await page.reload();await openSettings();await name.click();
   assert.equal(await panel.locator('input:checked').count(),2,'Both profiles survive reload');
   assert(await page.getByRole('switch',{name:'パフュートン（オス）の詳細厳選'}).isChecked());
   assert.equal(await page.getByRole('switch',{name:'パフュートン(メス)の詳細厳選'}).isChecked(),false);
   await page.locator('#selectionSettingsClose').click();
   await page.locator('#ivs').fill('0,11,12');const before=calls.length;await page.locator('#run').click();
   await page.waitForFunction(()=>!document.getElementById('run').disabled&&!document.getElementById('results').hidden);
   assert.deepEqual(calls.slice(before).map(call=>[call.candidate.species,call.candidate.charged2,call.batch_mode]),[
    ['oinkologne','DIG','detailed'],['oinkologne','TRAILBLAZE','detailed'],
   ]);
   assert.equal(await page.locator('#results').evaluate(e=>document.activeElement===e),true);
   assert((await page.locator('#results').innerText()).includes('検索式'));assert((await page.locator('#results').innerText()).includes('2 / 3構成'));
   assert(await page.locator('#results').evaluate(e=>e.getBoundingClientRect().top<document.getElementById('metaManager').getBoundingClientRect().top));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal overflow');assert.deepEqual(errors,[]);
   await context.close();
  }
  console.log('Chromium mobile/desktop: form-specific settings, accordion, legacy and new profiles, mode persistence and calculation requests: OK');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
