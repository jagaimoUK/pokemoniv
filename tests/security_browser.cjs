/* Verify actual Chromium execution under the HTTP CSP, with an anonymous fixture. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { chromium } = require('playwright');

(async () => {
  const server = spawn('python', ['tests/security_browser_server.py'], {
    env: { ...process.env, PVP_API_KEY: 'browser-fixture-' + 'x'.repeat(40) },
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  let browser;
  try {
    const [data] = await once(server.stdout, 'data');
    const port = Number(String(data).trim());
    assert(port > 0, 'fixture port');
    browser = await chromium.launch({
      executablePath: process.env.STRATEGY_CHROMIUM_PATH || undefined,
      headless: true,
      env: { PATH: process.env.PATH, HOME: process.env.HOME, LANG: 'C.UTF-8' },
    });
    for (const [path, selector] of [['/app', '#connect'], ['/app/party', '#login'],
                                    ['/reader-backup', '#issue'], ['/app/migration', '#migrationExport']]) {
      const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(() => {
        window.cspViolations = [];
        document.addEventListener('securitypolicyviolation', e => window.cspViolations.push(e.violatedDirective));
      });
      const response = await page.goto(`http://127.0.0.1:${port}${path}`);
      assert.equal(response.status(), 200);
      await page.waitForFunction(s => typeof document.querySelector(s)?.onclick === 'function', selector);
      assert.deepEqual(await page.evaluate(() => window.cspViolations), [], path);
      assert.deepEqual(errors, [], path);
      await page.close();
    }
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${port}/flashcards`);
    await page.waitForFunction(() => !!window.FLASHCARD_BOOTSTRAP);
    assert.deepEqual(errors, []);
    await page.close();
    // Real IndexedDB + Web Storage roundtrip between separate browser profiles.
    // Only synthetic fixtures; no Railway credentials or production endpoints.
    const sourceContext=await browser.newContext({viewport:{width:390,height:844}});
    const targetContext=await browser.newContext({viewport:{width:390,height:844}});
    const source=await sourceContext.newPage(),target=await targetContext.newPage();
    await source.goto(`http://127.0.0.1:${port}/app/migration`);
    const seed={format:'pokemoniv-browser-backup-v1',local:{'pvpoke-app-movesets-v1':'{"quagsire":[{"fast":"MUD_SHOT","charged1":"AQUA_TAIL","charged2":"STONE_EDGE"}]}'},
      session:{'pvpoke-app-run':'synthetic-run','pvpoke-app-batch':JSON.stringify({jobs:Array.from({length:160},(_,i)=>({ivs:`${i%16}/15/15`,cp:100+i})),results:[]})},
      flashcards:{kv:[['decks',[{id:'synthetic',name:'test'}]],['session',{deck:'synthetic',index:2}],['undo',null]],reviews:[['q1',{due:123,seen:true}]]}};
    await source.evaluate(data=>PokemonIVBrowserMigration.restore(data),seed);
    const exported=await source.evaluate(()=>PokemonIVBrowserMigration.capture());
    assert.equal(JSON.parse(exported.session['pvpoke-app-batch']).jobs.length,160);
    await target.goto(`http://127.0.0.1:${port}/app/migration`);
    await target.locator('#migrationFile').setInputFiles({name:'fixture.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(exported))});
    await target.waitForFunction(()=>!document.getElementById('migrationImport').disabled);
    await target.locator('#migrationImport').click();
    await target.waitForFunction(()=>document.getElementById('migrationStatus').textContent.includes('復元と照合が完了'));
    assert.equal(await target.evaluate(data=>PokemonIVBrowserMigration.capture().then(current=>PokemonIVBrowserMigration.covers(current,data)),exported),true);
    await target.reload();
    assert.equal(await target.evaluate(data=>PokemonIVBrowserMigration.capture().then(current=>PokemonIVBrowserMigration.covers(current,data)),exported),true);
    const conflict=structuredClone(exported);conflict.flashcards.reviews[0][1].due=999;
    assert.equal(await target.evaluate(data=>PokemonIVBrowserMigration.restore(data).then(()=>false,()=>true),conflict),true);
    assert.equal(await target.evaluate(()=>PokemonIVBrowserMigration.capture().then(x=>x.flashcards.reviews[0][1].due)),123);
    const emptyContext=await browser.newContext(),empty=await emptyContext.newPage();
    await empty.goto(`http://127.0.0.1:${port}/app/migration`);
    // A quota failure must leave IndexedDB and earlier Web Storage writes intact.
    await empty.evaluate(()=>{
      const original=Storage.prototype.setItem;
      Storage.prototype.setItem=function(key,value){if(key==='pvpoke-app-run')throw new DOMException('full','QuotaExceededError');return original.call(this,key,value);};
    });
    assert.equal(await empty.evaluate(data=>PokemonIVBrowserMigration.restore(data).then(()=>false,()=>true),exported),true);
    const afterFailure=await empty.evaluate(()=>PokemonIVBrowserMigration.capture());
    assert.equal(afterFailure.local['pvpoke-app-movesets-v1'],null);
    assert.equal(afterFailure.session['pvpoke-app-batch'],null);
    assert.deepEqual(afterFailure.flashcards,{kv:[],reviews:[]});
    await Promise.all([sourceContext.close(),targetContext.close(),emptyContext.close()]);
    console.log('CSP initialization and browser migration: 160 IVs, movesets, IndexedDB, reload, conflict and quota rollback PASS.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
