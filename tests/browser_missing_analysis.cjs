// Mobile UI smoke with synthetic responses and no production services.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const {chromium} = require('playwright');
const rows = require('./fixtures/strategy_rows.json');

const html = fs.readFileSync('pvpoke_missing_ui.py', 'utf8').split("HTML = r'''")[1].split("'''")[0]
  .replace('data-sandbox="0"', 'data-sandbox="1"')
  .replace('data-tactic-search="0"', 'data-tactic-search="1"')
  .replace('data-observed-search="0"', 'data-observed-search="1"');
const digest = text => crypto.createHash('sha256').update(text).digest('base64');
const inline = tag => digest(html.split('<' + tag + '>')[1].split('</' + tag + '>')[0]);
const csp = "default-src 'none'; connect-src 'self'; script-src 'sha256-" + inline('script')
  + "'; style-src 'sha256-" + inline('style') + "'";
const species = Object.fromEntries(rows.map(r => [r.species, {
  name: r.species,
  fastMoves: [r.fast],
  chargedMoves: [r.charged1, r.charged2],
  default_moves: {fast: r.fast, charged1: r.charged1, charged2: r.charged2},
}]));

async function fillBuild(page, selector, row) {
  await page.locator(selector + ' input[type=text]').fill(row.species);
  const controls = page.locator(selector + ' input[type=number]');
  for (const [i, value] of [row.atk, row.def, row.hp, row.level].entries()) {
    await controls.nth(i).fill(String(value));
  }
}

async function checkWidth(browser, width) {
  const page = await browser.newPage({viewport: {width, height: 844}, isMobile: true});
  const errors = [];
  const requests = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.addInitScript(() => {
      sessionStorage.setItem('pokemoniv:tactic-evidence-link-v1',
        JSON.stringify({evaluation_id:'e'.repeat(64),build_id:'b'.repeat(64),search_ids:['f'.repeat(64)]}));
      sessionStorage.setItem('pokemoniv:observed-evidence-link-v1',
        JSON.stringify({evaluation_id:'e'.repeat(64),build_id:'b'.repeat(64),search_id:'d'.repeat(64)}));
    });
    let savedScopes = [];
    const sampleInstanceId = 'inst-smoke-1';
    let sampleRevision = 1;
    let sampleCp = 1476;
    let listCalls = 0;
    let tacticEvidenceCalls = 0;
    await page.route('http://127.0.0.1:9876/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === '/app/missing') {
        return route.fulfill({contentType: 'text/html', body: html, headers: {'Content-Security-Policy': csp}});
      }
      if (path === '/app/sandbox') {
        return route.fulfill({contentType: 'text/html', body: '<!doctype html><meta charset="utf-8"><p>sandbox</p>'});
      }
      if (path === '/favicon.ico') return route.fulfill({status: 404, body: ''});
      const payload = request.postDataJSON();
      requests.push({path, payload});
      if (path === '/app-api/catalog') return route.fulfill({json: {ready: true, species}});
      if (path === '/app-api/meta-presets') {
        return route.fulfill({json: {
          default_id: 'custom:smoke', revision: 1,
          items: [{id: 'custom:smoke', name: 'テスト用メタ', rows: 1,
                   sha256: 'a'.repeat(64), available: true}],
        }});
      }
      if (path === '/app-api/meta-preset-export') {
        assert.equal(payload.id, 'custom:smoke');
        assert.equal(payload.expected_sha256, 'a'.repeat(64));
        return route.fulfill({json: {
          id: 'custom:smoke', sha256: 'a'.repeat(64),
          csv: [rows[3].species, rows[3].fast, rows[3].charged1, rows[3].charged2].join(','),
        }});
      }
      if (payload.action === 'evaluation_history') {
        assert.equal(payload.limit, 24);
        const common={comparison_key:'f'.repeat(64), role_id:'lead',role_revision:1,
          priority:1,analysis_id:'c'.repeat(64),evidence_state:'partial',
          versions_current:true,ledger_revision:2};
        return route.fulfill({json:{
          items:[
            {...common,evaluation_id:'e'.repeat(64),created_at:1795000100,state:'covered'},
            {...common,evaluation_id:'d'.repeat(64),created_at:1795000000,state:'evidence_pending'},
            {...common,evaluation_id:'c'.repeat(64),created_at:1795000000,state:'gap'},
          ],has_more:false,next_after:null,
        }});
      }
      if (payload.action === 'tactic_search_list') {
        assert.equal(payload.limit, 24);
        const build0 = {species_id: rows[0].species, ivs: {attack: rows[0].atk, defense: rows[0].def, hp: rows[0].hp},
          level: rows[0].level, moves: {fast: rows[0].fast, charged: [rows[0].charged1, rows[0].charged2]}};
        const build2 = {species_id: rows[2].species, ivs: {attack: rows[2].atk, defense: rows[2].def, hp: rows[2].hp},
          level: rows[2].level, moves: {fast: rows[2].fast, charged: [rows[2].charged1, rows[2].charged2]}};
        return route.fulfill({json: {
          items: [
            {search_id: 'f'.repeat(64), build_id: 'b'.repeat(64), self: build0, opponent: build2,
             shields: [1, 1], energy: 0, planned_scripts: 4, attempted_scripts: 1, complete_scripts: 1, version_current: true},
            {search_id: 'a'.repeat(64), build_id: 'b'.repeat(64), self: build0, opponent: build2,
             shields: [0, 1], energy: 12, planned_scripts: 4, attempted_scripts: 2, complete_scripts: 2, version_current: false},
          ],
          has_more: false, next_after: null,
        }});
      }
      if (payload.action === 'observed_search_list') {
        assert.equal(payload.limit, 24);
        const build0 = {species_id: rows[0].species, ivs: {attack: rows[0].atk, defense: rows[0].def, hp: rows[0].hp},
          level: rows[0].level, moves: {fast: rows[0].fast, charged: [rows[0].charged1, rows[0].charged2]}};
        const build2 = {species_id: rows[2].species, ivs: {attack: rows[2].atk, defense: rows[2].def, hp: rows[2].hp},
          level: rows[2].level, moves: {fast: rows[2].fast, charged: [rows[2].charged1, rows[2].charged2]}};
        return route.fulfill({json: {
          items: [{
            search_id: 'b'.repeat(64), work: 4, paused: false, scenario_count: 2, world_count: 2,
            worlds: [{self: build0, opponent: build2, shields: [1, 1], energy: 0}],
            worlds_truncated: false, roles: ['win'], version_current: true,
          }],
          has_more: false, next_after: null,
        }});
      }
      if (payload.action === 'sandbox_tactic_list') {
        const build0 = {species_id: rows[0].species, ivs: {attack: rows[0].atk, defense: rows[0].def, hp: rows[0].hp},
          level: rows[0].level, moves: {fast: rows[0].fast, charged: [rows[0].charged1, rows[0].charged2]}};
        const build2 = {species_id: rows[2].species, ivs: {attack: rows[2].atk, defense: rows[2].def, hp: rows[2].hp},
          level: rows[2].level, moves: {fast: rows[2].fast, charged: [rows[2].charged1, rows[2].charged2]}};
        return route.fulfill({json: {
          items: [{
            tactic_id: '1'.repeat(32), revision: 2, name: 'テスト戦術', saved_at: 1795000000,
            self: build0, opponent: build2, shields: [1, 1], energy: 0,
            action_count: 3, shield_decision_count: 1, version_current: true,
          }],
        }});
      }

      if (payload.action === 'evaluate') {
        const candidate = payload.candidates[0];
        const opponent = payload.scenarios[0].opponent;
        const condition = {opponent, shields: [1, 1], state: 'unknown', meets: null,
                           battle_key: 'c'.repeat(64),
                           spec: {combatants: [{initial: {energy: 0}}, opponent]}};
        const reference = {build_id: 'b'.repeat(64), species_id: candidate.species_id};
        return route.fulfill({json: {
          state: 'evidence_pending', evaluation_id: 'e'.repeat(64), reference,
          role: {role_id: 'lead', priority: 1}, can_calculate: width > 320,
          candidates: [{...candidate, ...reference, status: 'pending', party_substitution: 'pending',
                        conditions: [condition],
                        owned_instances: [{
                          instance_id: sampleInstanceId,
                          state: 'confirmed_owned',
                          revision: sampleRevision,
                          build_match: 'unverified',
                        }]}],
        }});
      }
      if (payload.action === 'tactic_evidence') {
        tacticEvidenceCalls += 1;
        assert.equal(payload.evaluation_id,'e'.repeat(64));
        assert.deepEqual(payload.search_ids, tacticEvidenceCalls === 1 ? ['f'.repeat(64)] : ['a'.repeat(64)]);
        return route.fulfill({json:{schema:'missing-tactic-evidence-v1',standard_state:'evidence_pending',
          searched_count:1,new_battles:0,builds:[{build_id:'b'.repeat(64),
          theoretical_all_conditions:false,advisory:{evidence_order:1,role_priority:3,
          required_conditions:1,tested_conditions:1,theoretical_supported_conditions:0,
          unfavorable_shield_conditions:0,only_observed_complete_build:false},
          conditions:[{standard:{meets:null},tested_scripts:1,
          matching_scripts:0,truncated:false,
          response_sensitivity:[{strategy:'original',tested_scenarios:2,
            matching_scenarios:1,nonmatching_scenarios:1,unverified_scenarios:0,
            observed_disagreement:true,opponent_scenarios_exhaustive:false,
            live_reproducibility:'not_verified'}],paths:[{strategy:'original',
          opponent_response:'alternate_charged',meets:null,
          observation_conditioned:false,information_assumptions:[
            'fixed_timed_self_actions','prespecified_opponent_actions',
            'unrevealed_opponent_charged_move_assumed']}]}]}]}});
      }
      if (payload.action === 'observed_evidence') {
        assert.equal(payload.evaluation_id, 'e'.repeat(64));
        assert.deepEqual(payload.search_ids, ['d'.repeat(64)]);
        return route.fulfill({json: {
          schema:'missing-observed-evidence-v1', evaluation_id:payload.evaluation_id,
          new_battles:0, standard_assessment_unchanged:true,
          information_fairness:'not_established', live_reproducibility:'not_verified',
          practical_role_covered:false, links:[{
            search_id:'d'.repeat(64), build_id:'b'.repeat(64), matching_worlds:1,
            additional_worlds:1, scenario_count:2, work:4, observed_status:'stopped',
            stop_reason:'policy_found', policy_scope_truncated:false, evaluation_count:1,
            conditions:[{opponent:{species_id:rows[2].species},shields:[1,1],
              standard_meets:null,aligned_role_ids:['win'],scenario_count:2,
              policy_scenarios:[{scenario_count:2,outcomes:{
                self_ko_win:1,opponent_ko_win:0,simultaneous_ko:0,timeout:0,unknown:1
              },aligned_roles:[{id:'win',passed:1,failed:0,unknown:1,meets:null}]}]}],
            policies:[{role:true, tested:2, failed:0, unknown:0,
              roles:[{id:'win',meets:true,passed:2,failed:0,unknown:0,
                resource_floor:{hp:3,energy:9,shields:0}}]}]
          }]
        }});
      }
      if (payload.action === 'explore') {
        assert.ok([0, 32].includes(payload.budget));
        assert.ok(Array.isArray(payload.iv_floors) && payload.iv_floors.length === 3);
        const filtered = payload.iv_floors.every(n => n === 10);
        const eligible = filtered ? 216 : 4096;
        const count = filtered ? 1 : (payload.budget === 32 ? 2 : 1);
        const qualifying = filtered
          ? [{attack: 10, defense: 14, hp: 15, level: 26.5, cp: 1492,
              owned_instances: [{instance_id: 'inst-smoke-10', state: 'confirmed_owned', revision: 1, build_match: 'exact'}],
              inventory_match_count: 1}]
          : [{attack: 0, defense: 15, hp: 15, level: rows[0].level, cp: rows[0].cp,
              owned_instances: [{instance_id: sampleInstanceId, state: 'confirmed_owned', revision: sampleRevision, build_match: 'unverified'}],
              inventory_match_count: 1}];
        return route.fulfill({json: {
          raw_iv_count: 4096, iv_floors: payload.iv_floors,
          candidate: {species_id: rows[0].species, moves: {fast: rows[0].fast, charged: [rows[0].charged1, rows[0].charged2]}},
          completed_iv_count: count, eligible_iv_count: eligible,
          qualifying_count: 1, not_fully_tested_iv_count: eligible - count,
          fully_tested_nonqualifying_iv_count: count - 1,
          retry_needed: payload.budget === 32, new_battles: count - 1,
          boundary_counts: {hp: 4, cmp: 2, breakpoint: 6, bulkpoint: 3,
            charged_1: 2, charged_2: 1, incoming_charged_1: 2, incoming_charged_2: 2},
          conditions: [{condition_id: 'a'.repeat(64), opponent: {species_id: rows[2].species, ivs: {attack: rows[2].atk, defense: rows[2].def, hp: rows[2].hp}},
            shields: [1, 1], energy: 0, completed_count: count, remaining_count: eligible - count,
            eligible_iv_count: eligible,
            boundary_counts: {hp: 4, cmp: 2, breakpoint: 6, bulkpoint: 3,
              charged_1: 2, charged_2: 1, incoming_charged_1: 2, incoming_charged_2: 2}}],
          ownership_summary: {
            confirmed_owned_exact_count: filtered ? 1 : 0,
            confirmed_owned_count: 1,
            confirmed_absent_recorded_count: 0,
            unconfirmed_count: 0,
            species_confirmed_owned_count: 1,
          },
          qualifying,
        }});
      }
      if (payload.action === 'opponent_boundaries') {
        assert.equal(payload.evaluation_id,'e'.repeat(64));
        assert.equal(payload.build_id,'b'.repeat(64));
        assert.equal(payload.battle_key,'c'.repeat(64));
        assert.deepEqual(payload.iv_floors, [0, 0, 0]);
        return route.fulfill({json:{
          raw_iv_count:4096, profiled_iv_count:4096, distinct_static_profile_count:17,
          native_battles_run:0, battle_outcomes_verified:false,
          boundary_counts:{hp:4,cmp:2,breakpoint:6,bulkpoint:3,
            charged_1:2,charged_2:1,incoming_charged_1:2,incoming_charged_2:2},
          representatives:[{attack:0,defense:15,hp:15}]
        }});
      }
      if (payload.action === 'ownership') {
        assert.equal(payload.instance_id, sampleInstanceId);
        assert.equal(payload.expected_revision, 1);
        assert.equal(payload.state, 'confirmed_owned');
        assert.equal(payload.register, false);
        assert.equal(payload.observation.current_cp, 1492);
        assert.equal(Object.hasOwn(payload.observation, 'current_level'), false);
        assert.equal(Object.hasOwn(payload.observation, 'current_moves'), false);
        sampleRevision = 2;
        sampleCp = 1492;
        return route.fulfill({json: {
          instance_id: sampleInstanceId,
          state: 'confirmed_owned',
          revision: sampleRevision,
        }});
      }
      if (payload.action === 'ownership_list') {
        listCalls += 1;
        if (listCalls === 1) {
          return route.fulfill({json: {
            ledger_revision: 2,
            items: [],
            has_more: true,
            next_after: 'i-0511',
            ...(payload.include_scopes ? {scopes: savedScopes, scopes_truncated: false} : {}),
          }});
        }
        const record = {
          instance_id: sampleInstanceId,
          species_id: rows[0].species,
          ivs: {attack: rows[0].atk, defense: rows[0].def, hp: rows[0].hp},
          current_cp: sampleCp,
          current_level: rows[0].level,
          current_moves: {fast: rows[0].fast, charged: [rows[0].charged1, rows[0].charged2]},
          state: 'confirmed_owned',
          revision: sampleRevision,
          confirmed_at: '2026-11-19T00:00:00Z',
        };
        return route.fulfill({json: {
          ledger_revision: 2,
          items: [record],
          has_more: false,
          next_after: null,
          ...(payload.include_scopes ? {scopes: savedScopes, scopes_truncated: false} : {}),
        }});
      }
      if (payload.action === 'ownership_history') {
        assert.equal(payload.instance_id, sampleInstanceId);
        return route.fulfill({json: {
          instance: {
            instance_id: sampleInstanceId,
            species_id: rows[0].species,
            ivs: {attack: rows[0].atk, defense: rows[0].def, hp: rows[0].hp},
            current_cp: sampleCp,
            current_level: rows[0].level,
            current_moves: {fast: rows[0].fast, charged: [rows[0].charged1, rows[0].charged2]},
            state: 'confirmed_owned',
            revision: sampleRevision,
          },
          events: [{
            event_id: 'ev-smoke-1',
            kind: 'instance',
            instance_id: sampleInstanceId,
            previous_state: 'unknown',
            new_state: 'confirmed_owned',
            input_revision: 0,
            output_revision: 1,
            confirmed_at: '2026-11-19T00:00:00Z',
            instance: {current_cp: 1476, current_level: rows[0].level},
          }],
          has_more: false,
        }});
      }
      if (payload.action === 'ownership_scope') {
        assert.equal(payload.expected_ledger_revision, 2);
        assert.equal(payload.species_id, rows[0].species);
        assert.deepEqual(payload.box_range, [1, 100]);
        assert.equal(payload.complete, true);
        assert.equal(payload.absence_confirmed, true);
        const event = {
          event_id: payload.event_id,
          kind: 'scope',
          scope: {species_id: payload.species_id, search: payload.search, box_range: payload.box_range},
          complete: payload.complete,
          absence_confirmed: payload.absence_confirmed,
          ledger_revision: payload.expected_ledger_revision,
          confirmed_at: '2026-11-19T00:05:00Z',
          current: true,
        };
        savedScopes = [event];
        return route.fulfill({json: event});
      }
      throw Error('Unexpected request ' + path);
    });
    await page.goto('http://127.0.0.1:9876/app/missing');
    await page.locator('#workspace').waitFor({state: 'visible'});
    await fillBuild(page, '#reference', rows[0]);
    await fillBuild(page, '#scenarios', rows[2]);
    await page.locator('#evaluate').click();
    await page.getByText('対戦証拠待ち', {exact: true}).waitFor();
    await page.locator('summary').filter({hasText: '重要IVを探索'}).click();
    await page.getByRole('button', {name: '探索範囲を確認'}).click();
    await page.getByText('達成を確認したIV　0/15/15', {exact: true}).waitFor();
    await page.getByText(/全条件の検証が未完了 4095通り/).waitFor();
    assert.equal(await page.getByRole('button', {name: '追加検証', exact: true}).count(),
      width > 320 ? 1 : 0);
    assert.equal(await page.getByRole('combobox', {name: '追加検証数'}).count(),
      width > 320 ? 1 : 0);
    assert.equal(await page.getByRole('button', {name: 'この対面だけ計算'}).count(), 0);
    if (width > 320) {
      await page.getByRole('combobox', {name: '追加検証数'}).selectOption('32');
      await page.getByRole('button', {name: '追加検証', exact: true}).click();
      await page.getByText(/全条件を計算済み 2 \/ 4096通り/).waitFor();
      await page.getByText(/全条件を検証して未達成 1通り/).waitFor();
      await page.getByText(/全条件の検証が未完了 4094通り/).waitFor();
      await page.locator('p.muted').filter({hasText: /途中の対戦結果を確定できませんでした/}).waitFor();
      await page.getByRole('button', {name:'相手IV境界を確認'}).click();
      await page.getByText(/静的境界のみ（勝敗未検証）/).waitFor();
      await page.getByText(/代表例（最大32件・勝敗未検証）：0\/15\/15/).waitFor();
    }
    // Step 2: iv_floors preset, static boundaries & per-condition progress, ownership match, and candidate reflection.
    await page.getByLabel('よく使う個体値下限').selectOption('10,10,10');
    await page.getByRole('button', {name: '探索範囲を確認'}).click();
    await page.getByText(/適用IV下限 10\/10\/10（全4096通り中 216通りが探索対象）/).waitFor();
    await page.getByText(/達成確認済みIVの所持照合：完全一致を所持確認 1件/).waitFor();
    await page.getByText('10/14/15 · Lv26.5 · CP 1492', {exact: true}).waitFor();
    await page.locator('summary').filter({hasText: '静的境界と対面別の探索進捗（静的境界は勝敗未検証）'}).click();
    await page.getByText(/全体の静的境界（HP・CMP・ダメージ変化境界／勝敗未検証）/).waitFor();
    await page.getByText(/対戦進捗：計算済み 1 \/ 216通り（未計算 215通り）/).waitFor();
    await page.getByRole('button', {name: '比較候補へ追加'}).first().click();
    assert.equal(await page.locator('#alternatives details.edit').count(), 1);
    assert.equal(await page.locator('#edited').isVisible(), true);
    await page.locator('#tactic-evidence-read').click();
    await page.getByText(/理論上の戦術であり、観測情報に基づく実戦再現性は未検証です/).waitFor();
    await page.getByText(/以下は保存済み戦術だけの参考順です/).waitFor();
    await page.locator('#tactic-evidence-results details.candidate').first().evaluate(el => {el.open = true});
    await page.getByText(/代替の実用性：未検証/).waitFor();
    // Information-assumption warnings live under a collapsed matchup detail,
    // not the outer candidate detail. Open both levels before asserting.
    await page.locator('#tactic-evidence-results details.match').first()
      .evaluate(el => {el.open = true});
    await page.getByText(/相手の未来の行動を仮定/).waitFor();
    await page.getByText(/相手側の条件で結果が変わっています/).waitFor();
    await page.getByText(/代替の実用性：未検証/).waitFor();
    await page.locator('summary').filter({hasText:'観測戦術の参考結果を確認'}).click();
    await page.getByRole('button', {name:'この個体の保存結果を照合'}).click();
    await page.getByText('有限シナリオの参考結果').waitFor();
    await page.getByText(/分析外の追加候補 1件/).waitFor();
    await page.getByText(/実戦再現性は未検証/).first().waitFor();
    // The observed-policy box nests a matchup detail. Open the inner detail,
    // not the already-open outer summary, before asserting its visible contents.
    await page.locator('#results details.match summary')
      .filter({hasText:/^対面 /}).first().click();
    await page.getByText(/同じ役割条件で比べられる観測役割：win/).waitFor();
    await page.getByText(/方策 1：この対面の有限条件 2件/).waitFor();
    await page.getByText(/条件 win：未確認が残る/).waitFor();
    // P1 candidate-card CP-only update: Lv blank and candidate-moves unchecked must omit current_level/current_moves.
    await page.locator('#result-tree details.record > summary').first().click();
    const candidateUpdateForm = page.locator('#result-tree details.record').first().locator('form').first();
    await candidateUpdateForm.locator('input[type="number"]').nth(0).fill('1492');
    await candidateUpdateForm.locator('input[type="checkbox"]').last().check();
    await candidateUpdateForm.locator('button:not([type="button"])').click();
    await page.locator('#result-tree small').filter({hasText: 'rev 2'}).waitFor({state: 'attached'});
    await page.locator('#result-tree details.record > summary').first().click();
    await page.locator('#result-tree small').filter({hasText: 'rev 2'}).waitFor();
    // Step 1 ownership ledger (including P2 empty-with-has_more page), history, and box-scope confirmation smoke.
    await page.locator('#inventory-panel > summary').click();
    await page.locator('#inventory-load').click();
    await page.locator('#inventory-items').getByText(/この範囲には該当個体はありません（続きあり）/).waitFor();
    await page.locator('#inventory-more').click();
    await page.getByText('台帳リビジョン 2 ／ 表示 1件', {exact: true}).waitFor();
    await page.locator('#inventory-items details.record > summary').first().click();
    await page.locator('#inventory-items').getByRole('button', {name: '履歴を表示'}).click();
    await page.getByText('rev 1：未確認 → 所持確認済み', {exact: true}).waitFor();
    await page.locator('#scope-panel > summary').click();
    assert.equal(await page.locator('#scope-absence').isDisabled(), true);
    await page.locator('#scope-species').fill(rows[0].species);
    await page.locator('#scope-search').fill('0attack');
    await page.locator('#scope-complete').check();
    assert.equal(await page.locator('#scope-absence').isDisabled(), false);
    await page.locator('#scope-absence').check();
    await page.locator('#scope-submit').click();
    await page.locator('#scope-list').getByText('範囲内に不在を確認', {exact: true}).waitFor();
    await page.locator('#scope-list').getByText(/検索「0attack」/).waitFor();
    // Step 3: history stays read-only and trend compares only matching snapshot conditions.
    await page.locator('#evaluation-history-panel > summary').click();
    await page.locator('#history-load').click();
    await page.locator('#history-items').getByText(/同条件の前回記録から：対戦証拠待ち → 所持確認済みの個体で充足/).waitFor();
    await page.locator('#history-items').getByText(/同時刻の別スナップショットあり（前後順は確定できません）/).waitFor();
    await page.locator('#meta-import-panel > summary').click();
    await page.locator('#meta-import-load').click();
    await page.locator('#meta-import-open').click();
    await page.locator('#meta-import-items').getByRole('button', {name: 'この相手を対面に追加'}).first().click();
    assert.equal(await page.locator('#scenarios details.edit').count(), 2);
    // Imported meta rows carry species/moves but must not invent IV or level.
    const imported = page.locator('#scenarios details.edit').nth(1);
    assert.equal(await imported.locator('input[type=number]').nth(0).inputValue(), '');
    assert.equal(await imported.locator('input[type=number]').nth(3).inputValue(), '');
    // Step 4: read-only selection of saved fixed/observed searches and Sandbox tactic listing + transfer.
    await page.locator('#tactic-search-load').click();
    await page.locator('#tactic-search-summary').getByText(/表示 2件 ／ 選択中 1 \/ 6件/).waitFor();
    const fixedChecks = page.locator('#tactic-search-items input[type=checkbox]');
    assert.equal(await fixedChecks.nth(0).isChecked(), true);
    assert.equal(await fixedChecks.nth(1).isChecked(), false);
    await fixedChecks.nth(0).uncheck();
    await fixedChecks.nth(1).check();
    await page.locator('#tactic-evidence-read').click();
    await page.locator('#observed-search-load').click();
    await page.locator('#observed-search-items').getByRole('button', {name: 'この観測IDを選択'}).click();
    assert.equal(await page.locator('#observed-search-id').inputValue(), 'b'.repeat(64));
    await page.locator('#sandbox-tactic-load').click();
    await page.locator('#sandbox-tactic-items').getByText(/テスト戦術（版 2/).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
    assert.deepEqual(errors, []);
    // Base requests (5 at 320px, 7 at 390px) + Step 2 (1) + update (2) + inventory/scope (5) + Step 3 (5) + Step 4 (4).
    assert.equal(requests.length, width > 320 ? 22 : 20);
    await page.locator('#sandbox-tactic-items').getByRole('button', {name: 'Sandboxで参照を開く'}).click();
    await page.waitForURL('**/app/sandbox');
    assert.equal(await page.evaluate(() => sessionStorage.getItem('pokemoniv:sandbox-input-v1')), null);
    assert.deepEqual(
      await page.evaluate(() => JSON.parse(sessionStorage.getItem('pokemoniv:sandbox-tactic-load-v1'))),
      {tactic_id: '1'.repeat(32), revision: 2}
    );
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined});
  try {
    for (const width of [320, 390]) await checkWidth(browser, width);
    console.log('Mobile missing analysis and read-only IV exploration passed');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
