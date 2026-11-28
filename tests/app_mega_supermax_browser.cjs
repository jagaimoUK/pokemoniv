// Isolated browser test for /app Mega Super MAX comparison UI
const fs = require('fs'), http = require('http'), assert = require('assert');
const { chromium } = require('playwright');
const html = fs.readFileSync('pvpoke_app_ui.py', 'utf8').split("HTML = r'''")[1].split("'''")[0];

const synthCatalog = {
  sableye_mega: {
    speciesId: 'sableye_mega',
    name: 'Sableye (Mega)',
    name_ja: 'メガヤミラミ',
    baseStats: { atk: 141, def: 136, hp: 137 },
    fastMoves: ['SHADOW_CLAW', 'FEINT_ATTACK'],
    chargedMoves: ['FOUL_PLAY', 'POWER_GEM', 'SHADOW_SNEAK'],
    default_moves: { species: 'sableye_mega', fast: 'SHADOW_CLAW', charged1: 'FOUL_PLAY', charged2: 'POWER_GEM' },
    tags: ['mega']
  }
};
const cpms = [0.0939999967813491, 0.135137430784308, 0.166397869586944, 0.192650914456886, 0.215732470154762, 0.236572655026622, 0.255720049142837, 0.273530381100769, 0.29024988412857, 0.306057381335773, 0.321087598800659, 0.335445032295077, 0.349212676286697, 0.36245774877879, 0.375235587358474, 0.387592411085168, 0.399567276239395, 0.41119354951725, 0.422500014305114, 0.432926413410414, 0.443107545375824, 0.453059953871985, 0.46279838681221, 0.472336077786704, 0.481684952974319, 0.490855810259008, 0.499858438968658, 0.508701756943992, 0.517393946647644, 0.525942508771329, 0.534354329109191, 0.542635762230353, 0.550792694091796, 0.558830599438087, 0.566754519939422, 0.574569148039264, 0.582278907299041, 0.589887911977272, 0.59740000963211, 0.604823657502073, 0.61215728521347, 0.61940411056605, 0.626567125320434, 0.633649181622743, 0.640652954578399, 0.647580963301656, 0.654435634613037, 0.661219263506722, 0.667934000492096, 0.674581899290818, 0.681164920330047, 0.687684905887771, 0.694143652915954, 0.700542893277978, 0.706884205341339, 0.713169102333341, 0.719399094581604, 0.725575616972598, 0.731700003147125, 0.734741011137376, 0.737769484519958, 0.740785574597326, 0.743789434432983, 0.746781208702482, 0.749761044979095, 0.752729105305821, 0.75568550825119, 0.758630366519684, 0.761563837528228, 0.764486065255226, 0.767397165298461, 0.77029727397159, 0.77318650484085, 0.776064945942412, 0.778932750225067, 0.781790064808426, 0.784636974334716, 0.787473583646825, 0.790300011634826, 0.792803950958807, 0.795300006866455, 0.79780392148697, 0.800300002098083, 0.802803892322847, 0.805299997329711, 0.807803863460723, 0.81029999256134, 0.812803834895026, 0.815299987792968, 0.817803806620319, 0.820299983024597, 0.822803778631297, 0.825299978256225, 0.827803750922782, 0.830299973487854, 0.832803753381377, 0.835300028324127, 0.837803755931569, 0.840300023555755, 0.842803729034748, 0.845300018787384, 0.847803702398935, 0.850300014019012, 0.852803676019539, 0.85530000925064, 0.857803649892077, 0.860300004482269, 0.862803624012168, 0.865299999713897];

const mockResult = {
  candidate: { species: 'sableye_mega', fast: 'SHADOW_CLAW', charged1: 'FOUL_PLAY', charged2: 'POWER_GEM' },
  mega_condition: {
    mega_level: 4,
    super_max_pl_hypothesis_status: 'unconfirmed_deferred'
  },
  selection: {
    recommendations: [
      {
        rank: 1,
        ivs: '0,15,15',
        grade: 'Sランク',
        role: '本命',
        needs_power_up: true,
        level: 49.5,
        mega_downscaled: false,
        evidence: [],
        equivalent_candidates: []
      }
    ]
  }
};

const server = http.createServer(async (req, res) => {
  const path = req.url;
  if (path === '/app-api/session') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true }));
  } else if (path === '/app-api/catalog') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      ready: true,
      species: synthCatalog,
      moves: {},
      presets: [{ species: 'sableye_mega', fast: 'SHADOW_CLAW', charged1: 'FOUL_PLAY', charged2: 'POWER_GEM', name: 'メガヤミラミ' }],
      cpms: cpms
    }));
  } else if (path === '/app-api/meta-presets') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ revision: 0, default_id: 'gl', items: [{ id: 'gl', name: 'スーパーリーグ', source: 'pvpoke', rows: 1, sha256: 'a'.repeat(64), available: true }] }));
  } else if (path === '/app-api/meta-status') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ready', selected_id: 'gl' }));
  } else if (path === '/app-api/run') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(mockResult));
  } else {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
  }
});

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  let browser;
  try {
    const execPath = process.env.STRATEGY_CHROMIUM_PATH || process.env.CHROME_BIN || '/opt/ms-playwright/chromium-1255/chrome-linux64/chrome';
    browser = await chromium.launch({ headless: true, executablePath: execPath });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));

    await page.goto('http://127.0.0.1:' + server.address().port + '/app');
    await page.locator('#workspace:not([hidden])').waitFor({ timeout: 5000 });

    // Simulate result rendering directly to verify UI rendering of recommendation & supermax table
    await page.evaluate((resData) => {
      renderRecommendation(resData.selection.recommendations[0], document.getElementById('results'), resData);
      document.getElementById('results').hidden = false;
    }, mockResult);

    // Verify recommendation card was created
    const card = page.locator('#results article.recommendation');
    assert.equal(await card.count(), 1);
    const text = await card.innerText();
    assert(text.includes('1位｜0,15,15｜Sランク'), 'Rank & IV header rendered');
    assert(text.includes('スーパー MAX PL+2 仮説保留'), 'Super max badge rendered');

    // Verify Mega Super MAX comparison table details
    const cmpDetails = card.locator('.mega-supermax-comparison');
    assert.equal(await cmpDetails.count(), 1, 'Comparison details rendered');
    const cmpSummary = await cmpDetails.locator('summary').innerText();
    assert(cmpSummary.includes('育成目標・スーパーMAX（PL+2）比較'), 'Summary text matches');

    // Verify comparison table rows and CP values
    const rows = cmpDetails.locator('table.mega-cmp-table tbody tr');
    assert.equal(await rows.count(), 4, '4 rows (PL50, PL51, Hyp1 PL52, Hyp2 PL53)');

    const row0 = await rows.nth(0).textContent();
    assert(row0.includes('通常 MAX（PL50）') && row0.includes('1508') && row0.includes('1668') && row0.includes('90.4%'));

    const row1 = await rows.nth(1).textContent();
    assert(row1.includes('相棒ブースト（PL51）') && row1.includes('1526') && row1.includes('1688') && row1.includes('90.4%'));

    const row2 = await rows.nth(2).textContent();
    assert(row2.includes('スーパーMAX 仮説1（PL50+2=52）') && row2.includes('1544') && row2.includes('1708') && row2.includes('90.4%'));

    const row3 = await rows.nth(3).textContent();
    assert(row3.includes('スーパーMAX 仮説2（PL51+2=53）') && row3.includes('53.0'));

    const costRows = cmpDetails.locator('table.mega-cost-table tbody tr');
    assert.equal(await costRows.count(), 3, '3 cap cost rows (Base, Hyp1, Hyp2)');
    assert((await costRows.nth(1).textContent()).includes('199 (-77)'));
    assert((await costRows.nth(2).textContent()).includes('165 (-111)'));
    assert((await cmpDetails.textContent()).includes('未確定参考値'));

    assert.deepEqual(errors, [], 'No page errors occurred');
    console.log('App Mega Super MAX browser test PASS: PL50/51 vs PL+2 comparison table and achievement ratios verified successfully');
  } finally {
    if (browser) await browser.close();
    await new Promise(r => server.close(r));
  }
})().catch(e => {
  console.error(e);
  process.exitCode = 1;
});
