// Rendering and input only. Battle calculations run on the server.
function strategyTargets(){
 const own=getMon();let enemies=[];try{enemies=partyRosterRows('strategyEnemy')}catch(_){}
 const fill=(id,rows,fallback)=>{const el=$(id),value=el.value;el.replaceChildren();rows.forEach((m,i)=>el.append(new Option((i+1)+': '+name(m.species||'未指定'),String(i))));el.value=[...el.options].some(o=>o.value===value)?value:String(fallback)};
 fill('strategySelf',own,0);fill('strategyLead',own,1);fill('strategyCloser',own,2);fill('strategyOpponent',enemies,0);strategyWorkMoves();
}
function strategyWorkMoves(){
 const m=getMon()[Number($('strategySelf').value)]||{};const el=$('workMove'),old=el.value;el.replaceChildren();
 [m.charged1,m.charged2].filter(Boolean).forEach(x=>el.append(new Option(partyMoveNames[x]?.name||x,x)));
 if([...el.options].some(x=>x.value===old))el.value=old;
}
function manualValues(id){const raw=$(id).value.trim();if(!raw)return [];const a=raw.split(',').map(x=>x.trim());if(a.length>24||a.some(x=>!['0','1'].includes(x)))throw Error('手動方針は0または1をカンマ区切りで24回まで指定してください');return a.map(x=>x==='1')}
function getStrategy(){
 const work={kind:$('workKind').value};if(work.kind==='charged')work.move_id=$('workMove').value||getMon()[Number($('strategySelf').value)||0]?.charged1;
 if(work.kind==='fast_damage')work.hp_fraction=Number($('workFraction').value)/100;
 return {self_index:Number($('strategySelf').value),opponent_index:Number($('strategyOpponent').value),lead_index:Number($('strategyLead').value),closer_index:Number($('strategyCloser').value),
 self_bait:$('selfBait').value==='1',opponent_bait:$('opponentBait').value==='1',public_moves:$('publicMoves').value==='1',
 manual_self:manualValues('manualSelf'),manual_opponent:manualValues('manualOpponent'),danger_ratio:Number($('dangerRatio').value),reserve:Number($('reserve').value),
 include_branch:$('includeBranch').checked,lead_turns:Number($('leadTurns').value),chase_delay_turns:Number($('chaseDelay').value),work};
}
function restoreStrategy(c){if(!c)return;$('strategyEnemy').value=c.enemy_csv||'';strategyTargets();
 const pairs={self_index:'strategySelf',opponent_index:'strategyOpponent',lead_index:'strategyLead',closer_index:'strategyCloser',lead_turns:'leadTurns',chase_delay_turns:'chaseDelay',danger_ratio:'dangerRatio',reserve:'reserve'};
 Object.entries(pairs).forEach(([k,id])=>{if(c[k]!=null)$(id).value=c[k]});strategyWorkMoves();
 ['self_bait','opponent_bait','public_moves'].forEach((k,i)=>{if(c[k]!=null)$(['selfBait','opponentBait','publicMoves'][i]).value=c[k]?'1':'0'});
 if(c.include_branch!=null)$('includeBranch').checked=c.include_branch;
 ['manual_self','manual_opponent'].forEach((k,i)=>{if(c[k])$(['manualSelf','manualOpponent'][i]).value=c[k].map(Number).join(',')});
 if(c.work){$('workKind').value=c.work.kind;if(c.work.move_id)$('workMove').value=c.work.move_id;if(c.work.hp_fraction)$('workFraction').value=c.work.hp_fraction*100}
}
const outcomes={self_ko_win:'突破',opponent_ko_win:'自分が倒れる',simultaneous_ko:'同時落ち',timeout:'時間切れ',boundary:'交代境界'};
function resourceText(p){return 'HP '+p.hp+'/'+p.max_hp+' / E '+p.energy_points+'点 / 残シールド '+p.shields+'枚'}
function battleTable(parent,rows){
 const wrap=node('div');wrap.style.overflowX='auto';const table=node('table');table.style.width='100%';table.style.fontSize='13px';
 const head=node('tr');['固定した方針','結果 / Rating','ターン数','自分の終端','相手の終端'].forEach(t=>head.append(node('th',t)));const thead=node('thead');thead.append(head);table.append(thead);
 const body=node('tbody');rows.forEach(({name,battle:b})=>{const tr=node('tr');[name,(outcomes[b.outcome]||b.outcome)+' / '+b.rating,b.turns,resourceText(b.terminal[0]),resourceText(b.terminal[1])].forEach(t=>{const td=node('td',t);td.style.padding='10px 5px';td.style.borderBottom='1px solid #557769';tr.append(td)});body.append(tr)});table.append(body);wrap.append(table);parent.append(wrap);
}
function showStrategy(r){
 const root=$('strategyResult');root.dataset.calculated='true';root.replaceChildren();const edit=node('button','条件へ移動');edit.onclick=()=>$('strategyConfig').scrollIntoView({block:'start',behavior:'smooth'});root.append(edit);root.append(node('h3',name(r.subject.species)+' 対 '+name(r.opponent.species)));
 const cov=r.coverage;addLine(root,'詳細条件 '+cov.calculated_detail_conditions+'/'+cov.detail_conditions+' / 後追い '+cov.calculated_branches+'/'+cov.branch_conditions+'。未計算・未対応はunknown。');
 const fast=r.pressure.fast_only,normal=r.pressure.standard,f=fast.pressure;
 root.append(node('h3','通常技のゴリ押し性能'));
 addLine(root,'1発 '+f.damage_per_fast+'ダメージ / '+f.fast_turns+'ターン / 相手最大HP '+f.opponent_max_hp+'。1ターンあたり '+pct(f.hp_fraction_per_turn)+'。開始状態での指標です。');
 battleTable(root,[{name:'標準2-2',battle:normal},{name:'自分は通常技限定・相手は通常攻撃',battle:fast}]);
 addLine(root,'通常技限定での実ダメージ '+fast.damage[0].fast+' / 消費シールド '+fast.shields_used[0]+'枚。通常技限定は削り性能を測る比較条件です。');
 root.append(node('h3','受けた後の仕事'));
 for(const a of r.absorb){const box=node('div',null,'result'),w=a.work;box.append(node('strong','開始HP '+pct(a.start_hp_fraction)+' / シールド0-2'));
 const crit=w.criterion.kind==='charged'?w.criterion.move_id+'を撃つ':w.criterion.kind==='fast_damage'?'通常技で相手最大HPの'+pct(w.criterion.hp_fraction)+'を削る':'相手にシールドを使わせる';
 addLine(box,'事前条件: '+crit+'。仕事 '+(w.achieved===null?'unknown（相手ゲージ技未観測）':w.achieved?'達成':'未達成')+' / 最初の被弾後生存 '+(w.survived_first_hit===null?'unknown':w.survived_first_hit?'はい':'いいえ')+' / 対面終了時生存 '+(w.survived_battle?'はい':'いいえ'));
 addLine(box,resourceText(a.battle.terminal[0])+' / 受けた後の通常技ダメージ '+w.fast_damage_after_hit+' / 奪ったシールド '+w.opponent_shields_taken_total+'枚（受けた後 '+w.shields_taken_after_hit+'枚）');
 addLine(box,'安全な引き先: unknown。耐える能力と交代後の安全性は別に評価します。');root.append(box)}
 root.append(node('h3','シールド方針とブラフの比較'));battleTable(root,r.comparisons);
 for(const row of r.comparisons.filter(x=>x.battle.decisions.length)){
 const d=node('details');d.append(node('summary',row.name+'：判断理由を見る'));const list=node('ul');
 for(const entry of row.battle.decisions){const o=entry.observation;const max=Math.max(0,...o.possible_charged.map(m=>m.damage_upper));
 const actual=row.battle.events.find(e=>e.actor===1-entry.defender&&e.kind==='charged'&&e.turn===entry.turn);
 list.append(node('li',(entry.defender===0?'自分':'相手')+' '+entry.turn+'ターン目 / '+o.incoming_number+'発目: '+(entry.shield?'貼る':'受ける')+'。判断時HP '+o.self.hp+'、観測通常技 '+o.observed_fast.count+'回、推定エネルギー '+o.estimated_energy_range.join('〜')+'、可能な被害上限 '+max+'。'+(entry.policy.kind==='manual'?'事前の手動指定。':'公開情報による温存ルール。')+(actual?' 事後に判明した技: '+actual.move_id:'')))}d.append(list);root.append(d)}
 root.append(node('h3','初手→交代→後追い'));
 if(!r.branches.length)addLine(root,'unknown：相手6体を入力して分岐を有効にすると計算します。');
 for(const entry of r.branches){const b=entry.branch,box=node('div',null,'result');box.append(node('strong','後追い '+name(entry.chaser_species)));
 addLine(box,'初手2-2の標準単独診断 Rating '+entry.lead_diagnostic_rating+' / '+(entry.lead_disadvantage_2_2?'初手不利':'初手不利は未成立'));
 if(b.status==='unknown'){addLine(box,'unknown: '+b.reason)}else{
 addLine(box,'実現した初手経過 '+b.realized.lead_turns+'ターン / 後追い遅延 '+b.realized.chase_delay_turns+'ターン / 各交代で1ターン使用。後追い開始HP '+b.realized.safe_hp+'・先行エネルギー '+b.realized.safe_energy_points+'点・共有シールド '+b.realized.shared_shields_at_chase.join('-'));
 battleTable(box,[{name:'後追い対面',battle:b.chase}]);addLine(box,'チーム全体の残シールド '+b.team_shields_remaining.join('-')+'。退避した初手: '+resourceText(b.benched.self_lead)+'。残り1体: '+name(r.remaining_two[1].species)+'（未出場）。');
 addLine(box,'残り2体への展開: 資源の記録まで。再登場時の能力変化リセット、次の交代・削り直し・実際の3対3はunknown。')}
 root.append(box)}
 addLine(root,'キャッシュ再利用 '+r.cache.hits+' / 新規条件 '+r.cache.computed+'（内部の新規対戦 '+r.cache.new_battles+'） / 新規計算 '+r.cache.compute_seconds.toFixed(3)+'秒 / 再利用読込 '+r.cache.cache_seconds.toFixed(3)+'秒 / Node最大RSS '+(r.cache.node_peak_rss_mb??'未起動')+' MiB');
 r.notes.forEach(t=>addLine(root,t));addLine(root,'未検証: '+r.unknown.join('、'));tab('strategy');root.scrollIntoView({block:'start',behavior:'smooth'});
}
$('strategySelf').onchange=strategyWorkMoves;
$('strategyEnemy').onchange=strategyTargets;
$('copyEnemy').onclick=()=>{$('strategyEnemy').value=$('enemy').value;inputRevision++;rosterEditors.strategyEnemy?.refresh();strategyTargets()};
$('runStrategy').onclick=()=>{strategyTargets();wrap('strategy')};
