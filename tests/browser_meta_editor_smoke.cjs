// Real browser, synthetic catalogs/HTTP responses only; no live battle or user data.
const fs=require('fs'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8').split("HTML = r'''")[1].split("'''")[0];
const a={species:'corviknight',fast:'SAND_ATTACK',charged1:'IRON_HEAD',charged2:'AIR_CUTTER'},b={species:'corsola_galarian',fast:'ASTONISH',charged1:'NIGHT_SHADE',charged2:'POWER_GEM'};
const species={corviknight:{name:'Corviknight',name_ja:'アーマーガア',fastMoves:['SAND_ATTACK','STEEL_WING'],chargedMoves:['IRON_HEAD','AIR_CUTTER'],default_moves:a},corsola_galarian:{name:'Corsola (Galarian)',name_ja:'サニーゴ（ガラル）',aliases:['サニーゴ(ガラル)'],fastMoves:['ASTONISH'],chargedMoves:['NIGHT_SHADE','POWER_GEM'],default_moves:b}};
const labels={SAND_ATTACK:['すなかけ','Sand Attack'],STEEL_WING:['はがねのつばさ','Steel Wing'],IRON_HEAD:['アイアンヘッド','Iron Head'],AIR_CUTTER:['エアカッター','Air Cutter'],ASTONISH:['おどろかす','Astonish'],NIGHT_SHADE:['ナイトヘッド','Night Shade'],POWER_GEM:['パワージェム','Power Gem']};
const moves=Object.fromEntries(Object.entries(labels).map(([id,[name_ja,name]])=>[id,{name_ja,name}]));
const csv=[a,b].map(x=>[x.species,x.fast,x.charged1,x.charged2].join(',')).join('\n')+'\n';
const calls=[];let conflict=false;const item={id:'official',name:'テストメタ',source:'pvpoke',rows:2,sha256:'a'.repeat(64),available:true};
const server=http.createServer(async(req,res)=>{let body='';for await(const chunk of req)body+=chunk;const data=body?JSON.parse(body):{};const path=req.url;calls.push({path,data});let out;
 if(path==='/app-api/catalog')out={ready:true,species,moves,presets:[{...a,name:'アーマーガア'}]};
 else if(path==='/app-api/meta-presets')out={revision:0,default_id:'official',items:[item]};
 else if(path==='/app-api/meta-preset-export')out={id:'official',sha256:item.sha256,csv,rows:2};
 else if(path==='/app-api/meta-preview')out={sha256:'b'.repeat(64),rows:data.csv.trim().split('\n').length};
 else if(path==='/app-api/meta-preset-save'){if(conflict){res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'別の画面で更新されました'}));return;}out={revision:1,default_id:'official',saved_id:'custom:edited',items:[item,{id:'custom:edited',name:data.name,source:'custom',rows:1,sha256:'b'.repeat(64)}]};}
 else if(path.startsWith('/app-api/')){res.writeHead(400,{'Content-Type':'application/json'});res.end('{}');return;}
 else{res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(html);return;}
 res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(out));});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;try{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||process.env.STRATEGY_CHROMIUM_PATH||undefined});
 for(const width of [390,1280]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/app');await page.locator('#metaEdit').click();
  await page.locator('#metaEditorRows .meta-edit-row').first().waitFor();
  assert.equal(await page.locator('#metaEditorRows .meta-edit-row').count(),2);
  assert(await page.locator('#metaEditorRows').innerText().then(s=>s.includes('サニーゴ')));
  const first=page.locator('.meta-edit-row').first();
  await first.locator('input').nth(1).fill('Steel Wing');await first.locator('input').nth(1).dispatchEvent('change');
  await page.locator('.meta-edit-row').nth(1).getByRole('button',{name:/削除/}).click();
  assert.equal(await page.locator('.meta-edit-row').count(),1);
  await page.locator('#metaEditorUndo').click();assert.equal(await page.locator('.meta-edit-row').count(),2);
  await page.locator('.meta-edit-row').nth(1).getByRole('button',{name:/削除/}).click();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal overflow');
  if(width===390){fs.mkdirSync('meta-editor-qa',{recursive:true});await page.locator('#metaEditor').screenshot({path:'meta-editor-qa/mobile.png'});}
  conflict=true;await page.locator('#metaEditorSave').click();await page.waitForFunction(()=>document.getElementById('metaEditorStatus').textContent.includes('保存できません'));
  assert(await page.locator('#metaEditor').isVisible());assert.equal(await page.locator('.meta-edit-row').count(),1);
  conflict=false;await page.locator('#metaEditorSave').click();await page.waitForFunction(()=>document.getElementById('metaEditor').hidden);
  const saved=calls.filter(c=>c.path==='/app-api/meta-preset-save').at(-1).data;
  assert.equal(saved.action,'create');assert.equal(saved.exact_rows,true);assert.equal(saved.csv,'corviknight,STEEL_WING,IRON_HEAD,AIR_CUTTER\n');
  assert.deepEqual(errors,[]);await page.close();
 }
 assert(!calls.some(c=>c.path==='/app-api/run'));console.log('Meta editor mobile/desktop: Japanese labels, English move entry, delete/undo, exact copied save, conflict retention, no battle: OK');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}})().catch(e=>{console.error(e);process.exitCode=1});
