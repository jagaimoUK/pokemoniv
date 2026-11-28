// Isolated browser test for /app Mega GL temporary CP downscaling UI and rule transmission
const fs = require('fs'), http = require('http'), assert = require('assert');
const { chromium } = require('playwright');
const html = fs.readFileSync('pvpoke_app_ui.py', 'utf8').split("HTML = r'''")[1].split("'''")[0];

const synthCatalog = {
  altaria: {
    speciesId: 'altaria',
    name: 'Altaria',
    name_ja: 'チルタリス',
    baseStats: { atk: 141, def: 201, hp: 181 },
    fastMoves: ['DRAGON_BREATH'],
    chargedMoves: ['SKY_ATTACK', 'MOONBLAST'],
    default_moves: { species: 'altaria', fast: 'DRAGON_BREATH', charged1: 'SKY_ATTACK', charged2: 'MOONBLAST' },
    tags: []
  },
  altaria_mega: {
    speciesId: 'altaria_mega',
    name: 'Altaria (Mega)',
    name_ja: 'メガチルタリス',
    baseStats: { atk: 222, def: 218, hp: 181 },
    fastMoves: ['DRAGON_BREATH'],
    chargedMoves: ['SKY_ATTACK', 'MOONBLAST', 'DAZZLING_GLEAM'],
    default_moves: { species: 'altaria_mega', fast: 'DRAGON_BREATH', charged1: 'SKY_ATTACK', charged2: 'MOONBLAST' },
    tags: ['mega']
  }
};
const cpms = [0.0939999967813491, 0.135137430784308, 0.166397869586944, 0.192650914456886, 0.215732470154762, 0.236572655026622, 0.255720049142837, 0.273530381100769, 0.29024988412857, 0.306057381335773, 0.321087598800659, 0.335445032295077, 0.349212676286697, 0.36245774877879, 0.375235587358474, 0.387592411085168, 0.399567276239395, 0.41119354951725, 0.422500014305114, 0.432926413410414, 0.443107545375824, 0.453059953871985, 0.46279838681221, 0.472336077786704, 0.481684952974319, 0.490855810259008, 0.499858438968658, 0.508701756943992, 0.517393946647644, 0.525942508771329, 0.534354329109191, 0.542635762230353, 0.550792694091796, 0.558830599438087, 0.566754519939422, 0.574569148039264, 0.582278907299041, 0.589887911977272, 0.59740000963211, 0.604823657502073, 0.61215728521347, 0.61940411056605, 0.626567125320434, 0.633649181622743, 0.640652954578399, 0.647580963301656, 0.654435634613037, 0.661219263506722, 0.667934000492096, 0.674581899290818, 0.681164920330047, 0.687684905887771, 0.694143652915954, 0.700542893277978, 0.706884205341339, 0.713169102333341, 0.719399094581604, 0.725575616972598, 0.731700003147125, 0.734741011137376, 0.737769484519958, 0.740785574597326, 0.743789434432983, 0.746781208702482, 0.749761044979095, 0.752729105305821, 0.75568550825119, 0.758630366519684, 0.761563837528228, 0.764486065255226, 0.767397165298461, 0.77029727397159, 0.77318650484085, 0.776064945942412, 0.778932750225067, 0.781790064808426, 0.784636974334716, 0.787473583646825, 0.790300011634826, 0.792803950958807, 0.795300006866455, 0.79780392148697, 0.800300002098083, 0.802803892322847, 0.805299997329711, 0.807803863460723, 0.81029999256134, 0.812803834895026, 0.815299987792968, 0.817803806620319, 0.820299983024597, 0.822803778631297, 0.825299978256225, 0.827803750922782, 0.830299973487854, 0.832803753381377, 0.835300028324127, 0.837803755931569, 0.840300023555755, 0.842803729034748, 0.845300018787384, 0.847803702398935, 0.850300014019012, 0.852803676019539, 0.85530000925064, 0.857803649892077, 0.860300004482269, 0.862803624012168, 0.865299999713897];

let lastRunRules = null;
let lastRunCandidate = null;

function createMockResult(rules) {
  return {
    run_ref: 'run-mega-ds-1',
    state: 'done',
    complete: true,
    calculation_version: 'a'.repeat(64),
    meta_sha256: 'b'.repeat(64),
    candidate: { species: 'altaria_mega', fast: 'DRAGON_BREATH', charged1: 'SKY_ATTACK', charged2: 'MOONBLAST' },
    rules,
    mega_condition: {
      mega_level: 3,
      super_max_pl_hypothesis_status: 'not_applicable'
    },
    selection: {
      complete: true,
      recommendations: [
        {
          rank: 1,
          ivs: '0/14/15',
          grade: 'Sランク',
          role: '本命',
          needs_power_up: false,
          mega_downscaled: true,
          search_string: '334&cp1800',
          evidence: [],
          equivalent_candidates: []
        }
      ],
      covered_candidates: [],
      additional_candidates: [],
      review_candidates: [],
      unmatched_focus: [],
      dominated_by: {}
    }
  };
}

const server = http.createServer(async (req, res) => {
  const path = req.url;
  if (path === '/app-api/session') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  if (path === '/app-api/catalog') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ready: true, species: synthCatalog, cpms, app_presets: [], presets: [], moves: {} }));
    return;
  }
  if (path === '/app-api/meta-presets' || path === '/app-api/meta') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      default_id: 'great',
      items: [{ id: 'great', name: '通常GL', available: true, count: 50, sha256: 'b'.repeat(64), default: true }]
    }));
    return;
  }
  if (path === '/app-api/import') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      jobs: [{
        name: 'メガチルタリス',
        candidate_count: 1,
        candidate: { species: 'altaria_mega', fast: 'DRAGON_BREATH', charged1: 'SKY_ATTACK', charged2: 'MOONBLAST', mega_level: 3, level_override: 35.0 },
        ivs: '0,14,15',
        source_records: [{ ivs: '0/14/15', cp: 1800, species: 'altaria', search_string: '334&cp1800', level_override: 35.0 }],
        source_sections: ['手持ち'],
        pokemon_status: 'normal'
      }]
    }));
    return;
  }
  if (path === '/app-api/run') {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      const parsed = JSON.parse(body || '{}');
      lastRunRules = parsed.rules;
      lastRunCandidate = parsed.candidate;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(createMockResult(parsed.rules)));
    });
    return;
  }
  if (path === '/app') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
    return;
  }
  res.writeHead(404);
  res.end('not found');
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const candidatePath = process.env.STRATEGY_CHROMIUM_PATH || process.env.CHROME_BIN || '/opt/ms-playwright/chromium-1255/chrome-linux64/chrome';
  const execPath = fs.existsSync(candidatePath) ? candidatePath : chromium.executablePath();
  const browser = await chromium.launch({
    headless: true,
    executablePath: execPath
  });
  try {
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${port}/app`);
    await page.waitForSelector('#workspace:not([hidden])');

    // Import an owned Altaria at CP 1800 (exceeds 1500 cap)
    await page.fill('#importText', '個体値厳選\n\n# チルタリス\n0,14,15');
    await page.click('#importInput');
    await page.waitForFunction(() => document.querySelector('#species').value === 'altaria_mega');

    // 1. Select Mega GL (allow_cp_downscaling = true)
    await page.selectOption('#battleRuleset', 'great_mega');
    await page.click('#run');
    await page.waitForSelector('#results .recommendation');

    assert.strictEqual(lastRunRules.cup_id, 'great_mega');
    assert.strictEqual(lastRunRules.allow_cp_downscaling, true);
    assert.strictEqual(lastRunCandidate.mega_level, 3);
    assert.strictEqual(lastRunCandidate.level_override, 35.0);

    const megaText = await page.textContent('#results');
    assert.ok(megaText.includes('一時ダウンスケーリング適用（参加可）'), `Expected downscaled badge, got: ${megaText}`);
    assert.ok(megaText.includes('実CP1800'), `Expected source CP1800 in notes, got: ${megaText}`);
    assert.ok(megaText.includes('対戦CP14'), `Expected downscaled battle CP around 14xx in notes, got: ${megaText}`);

    // 2. Switch to Standard GL (allow_cp_downscaling = false) and rerun
    await page.selectOption('#battleRuleset', 'cp1500-lv50');
    await page.click('#run');
    await page.waitForFunction(() => document.querySelector('#results').textContent.includes('CP上限超過'));

    assert.strictEqual(lastRunRules.cup_id, 'all');
    assert.strictEqual(lastRunRules.allow_cp_downscaling, false);
    assert.strictEqual(lastRunCandidate.level_override, 35.0);

    const strictText = await page.textContent('#results');
    assert.ok(strictText.includes('CP上限超過（無補正不可）'), `Expected strict ineligible badge, got: ${strictText}`);
    assert.ok(strictText.includes('無補正ルールでは参加不可（実CP1800）'), `Expected strict ineligible note, got: ${strictText}`);

    console.log('App Mega GL downscaling browser test PASS: Mega GL downscaling vs Strict GL cap check verified successfully');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => {
  console.error(e);
  process.exit(1);
});
