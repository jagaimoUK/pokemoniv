"""Browser-only entry point. Root credentials are never persisted in the browser.
An optional HttpOnly app-only cookie supports remembered browser sessions.
"""
HTML = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>個体値厳選</title><style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#e8eef9;background:#101723;color-scheme:dark}*{box-sizing:border-box}body{margin:0}html{scroll-behavior:smooth;scroll-padding-top:16px}
.quick-nav{position:fixed;right:12px;top:44vh;z-index:30;display:flex;flex-direction:column;gap:6px;align-items:center}
.quick-nav a{display:flex;align-items:center;justify-content:center;min-height:48px;min-width:54px;padding:8px 7px;border:1px solid #76b1dc;border-radius:12px;background:#1d4768;color:#fff;font-size:12px;font-weight:650;text-decoration:none;box-shadow:0 4px 14px #0008}
.quick-nav a:focus-visible{outline:3px solid #90ddbc;outline-offset:3px}
@media(max-width:560px){.quick-nav{right:6px;top:58vh;bottom:auto}.quick-nav a{min-height:48px;min-width:48px;padding:9px 5px;font-size:11px}}
main{max-width:820px;margin:auto;padding:28px 16px 64px}h1{font-size:30px;margin:4px 0 8px}h2{font-size:20px;margin:0 0 12px}p{line-height:1.65;color:#afc0d6}.eyebrow{color:#90ddbc;font-size:12px;letter-spacing:.15em}.card{background:#1a2637;border:1px solid #33465d;border-radius:16px;padding:20px;margin-top:18px}label{display:block;font-size:14px;margin:14px 0 6px}input,select,textarea,button{font:inherit;border-radius:9px}input,select,textarea{width:100%;padding:12px;border:1px solid #49627d;background:#101c2b;color:#ecf3ff}input[type=checkbox]{width:auto;margin:0 8px 0 0;accent-color:#90ddbc}.checkline{display:flex;align-items:center;gap:3px;cursor:pointer}textarea{min-height:142px;line-height:1.7}button{min-height:48px;padding:12px 18px;border:1px solid #76b1dc;background:#266b9b;color:white;cursor:pointer}button:disabled{opacity:.5;cursor:wait}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}.secondary{background:transparent;border-color:#597086}.note{font-size:13px}.status{background:#21374a;border-radius:10px;padding:14px;white-space:pre-wrap;line-height:1.7}.error{background:#5a303a}.badge{color:#96e8c4;font-size:13px}.recommendation{border-top:1px solid #3c5068;padding-top:18px;margin-top:18px}.search{display:block;background:#0d1726;padding:12px;border-radius:8px;overflow-wrap:anywhere;font-size:14px;color:#b1e5ff}summary{cursor:pointer;color:#a4cdff}details{margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font-size:12px}[hidden]{display:none!important}@media(max-width:560px){.row{grid-template-columns:1fr}.card{padding:16px}main{padding-top:22px}.actions button{flex:1}}
.low-score-list{display:grid;gap:12px;margin-top:14px}.low-score-item{padding:12px;border-radius:16px;background:#202f3d;border:1px solid #41594f}.low-score-item code{white-space:pre-wrap;overflow-wrap:anywhere;color:#d1ebd8;display:block;margin:8px 0}.low-score-item button{border-radius:999px;background:#536e61;border-color:#749783}.low-score-tools{display:grid;grid-template-columns:2fr 1fr;gap:10px}@media(max-width:560px){.low-score-tools{grid-template-columns:1fr}}

.meta-presets{margin-bottom:18px}.meta-current{display:flex;align-items:center;flex-wrap:wrap;gap:6px 9px;padding:0 0 10px}.meta-caption{font-size:12px;color:#afc0d6}.meta-current-name{font-size:16px;font-weight:650;line-height:1.5;margin:0;color:#ecf3ff;overflow-wrap:anywhere}.meta-count{font-size:12px;color:#afc0d6;white-space:nowrap}.meta-badges{display:inline-flex;align-items:center;flex-wrap:wrap;gap:5px}.meta-tag{display:inline-flex;align-items:center;font-size:11px;font-weight:600;line-height:1.5;padding:2px 7px;border-radius:999px;background:#263d3a;color:#b9e6cf;white-space:nowrap}.meta-star{color:#e8cc85;background:#3c372b}
.meta-toolbar,.meta-quick,.meta-settings{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.meta-toolbar button,.meta-settings button{flex:0 1 auto;min-height:44px;padding:9px 12px;font-size:13px;border-radius:12px;max-width:100%}.meta-toolbar{margin-bottom:8px}.meta-settings{margin-top:12px}.meta-settings button[aria-pressed=true],.meta-settings .is-set{border-color:#83bba5;background:#233d35;color:#caeedb}.meta-presets button:focus-visible{outline:3px solid #b9e6cf;outline-offset:3px}.meta-presets button:not(:disabled):active{filter:brightness(1.18)}
.meta-chooser{margin-top:10px;padding:14px;border:1px solid #41586b;border-radius:16px;background:#142130}.meta-hint{font-size:12px;line-height:1.5;margin:0 0 9px;color:#afc0d6}.meta-quick{align-items:flex-start}.meta-chip{display:inline-flex;align-items:center;justify-content:flex-start;gap:7px;flex:0 1 auto;max-width:100%;min-height:44px;padding:9px 11px;border:1px solid #526979;border-radius:13px;background:#1b2d3d;color:#e8eef9;text-align:left;font-size:13px;line-height:1.5}.meta-chip[aria-pressed=true]{border-color:#91cbb0;background:#29483c;color:#e4f8eb}.meta-chip-mark{flex:none;width:15px;color:#b1c5d4;text-align:center}.meta-chip[aria-pressed=true] .meta-chip-mark{color:#c5f2d8}.meta-chip-name{min-width:0;overflow-wrap:anywhere}.meta-chip .meta-tag{font-size:10px;padding:1px 6px;flex:none}.meta-all-row{display:flex;align-items:center;gap:8px}.meta-all-row select{min-width:0;flex:1;font-size:13px}.meta-all-row button{flex:none;width:44px;min-height:44px;padding:8px;border-radius:12px;font-size:21px}.meta-help{margin:8px 0;font-size:12px}.meta-help summary{color:#afc0d6}.meta-presets .note:empty{display:none}.meta-presets .note{line-height:1.6}
.meta-edit-row{position:relative;border:1px solid #486252;border-radius:16px;padding:14px 60px 14px 14px;margin:10px 0;background:#192e2b}.meta-edit-heading{font-weight:650;margin-bottom:8px}.meta-edit-remove{position:absolute;right:8px;top:8px;width:44px;padding:6px;border-radius:50%;min-height:44px}.meta-edit-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.meta-edit-fields label{margin:0;font-size:12px}.meta-edit-fields input{margin-top:4px;min-width:0;font-size:14px}.meta-edit-error{color:#ffb6b6;font-size:12px;margin:6px 0 0}@media(max-width:420px){.meta-edit-fields{grid-template-columns:1fr}.meta-edit-row{padding-right:55px}}
.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.page-heading h1{font-size:clamp(22px,5vw,30px)}.settings-button{flex:none;min-width:72px}.selection-settings{position:fixed;inset:6vh 12px;z-index:60;max-width:720px;width:calc(100% - 24px);color:inherit;margin:auto;overflow:auto;box-shadow:0 0 0 100vmax #0009}.selection-settings .actions{position:sticky;bottom:0;background:#1a2637;padding:10px 0}.species-mode-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-top:1px solid #33465d}.species-mode-name{flex:1;min-width:0;min-height:44px;padding:6px 0;background:transparent;color:#a4cdff;text-align:left;overflow-wrap:anywhere}.species-mode-name::before{content:"";display:inline-block;margin:0 8px 1px 3px;width:6px;height:6px;border:solid currentColor;border-width:0 2px 2px 0;transform:rotate(-45deg)}.species-mode-name[aria-expanded="true"]::before{transform:rotate(45deg)}.species-mode-row input{width:24px;height:24px;flex:none}.species-mode-state{font-size:13px;color:#afc0d6;flex:none}
.species-movesets{padding:0 0 12px 12px;border-left:2px solid #41586b}
.species-moveset-row{display:flex;gap:8px;align-items:center;justify-content:space-between;margin:8px 0}
.species-moveset-row label{margin:0;overflow-wrap:anywhere}.species-moveset-row button{flex:none;padding:8px 10px}
.species-moveset-add{width:100%;text-align:left;margin-top:8px}.species-moveset-form .row{align-items:end}
.species-moveset-form .form-buttons{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
</style></head><body><nav class="quick-nav" aria-label="ページ内の移動"><a href="/app/party" aria-label="パーティ作成">6/3<br>構築</a><a href="#pageTop" aria-label="ページ上部に戻る">↑<br>上へ</a></nav><main id="pageTop">
<header><div class="eyebrow">PVP IV SELECTION</div><div class="page-heading"><h1>役割から選ぶ、個体値厳選</h1><button id="selectionSettingsOpen" class="secondary settings-button" type="button" aria-controls="selectionSettings" aria-expanded="false" hidden>⚙ 設定</button></div><p>対戦計算からおすすめ・理由・検索式まで。アプリの自動推薦と、これまでのGPT評価を使い分けられます。</p></header>
<section class="card" id="login"><h2>アプリに接続</h2><p class="note">初回だけ接続キー、または有効なアクセストークンを入力してください。APIキー自体は端末へ保存しません。</p><label for="credential">接続キー</label><input id="credential" type="password" autocomplete="off"><label class="checkline" for="remember"><input id="remember" type="checkbox" checked>このブラウザのログインを30日間維持する</label><p class="note">共有端末ではチェックを外してください。短期アクセストークンは元の期限まで有効です。ログアウトでこのブラウザのセッションを失効できます。</p><div class="actions"><button id="connect">接続する</button></div></section>
<p class="note"><a href="/app/migration" style="color:#a4cdff">ブラウザ保存データのバックアップ・復元</a></p>
<div id="message" class="status" role="status" aria-live="polite" hidden></div>
<dialog id="selectionSettings" class="card selection-settings" role="dialog" aria-modal="true" aria-labelledby="selectionSettingsTitle" hidden>
<h2 id="selectionSettingsTitle">ポケモンごとの厳選設定</h2><p class="note">未設定は通常厳選（6条件）です。トグルをONにしたポケモンだけ詳細厳選（24条件）にします。ポケモン名をタップすると、計算に使う技構成を確認・追加できます。厳選モードと技構成は姿・シャドウごとに、このブラウザへ保存します。</p>
<label for="selectionModeFilter">日本語・英語で検索</label><input id="selectionModeFilter" type="search" autocomplete="off" placeholder="例：サニーゴ / Corsola">
<p id="selectionModeStatus" class="note" aria-live="polite"></p><div id="selectionModeRows"></div><button id="selectionModeMore" class="secondary" type="button" hidden>さらに50件を表示</button>
<div class="actions"><button id="selectionSettingsClose" type="button">閉じる</button></div></dialog>
<div id="workspace" hidden>
<section class="card" id="lowScorePanel" hidden>
<h2>非厳選判定の内訳（診断）</h2>
<p class="note">読み取りアプリの「⋯ → 非厳選を取得・コピー」から直接検索式を生成・コピーします。この画面は除外理由の確認専用で、検索式の手動転送は不要です。候補は博士送りの保証ではありません。</p>
<div class="low-score-tools"><div><label for="lowMode">判定基準</label><select id="lowMode"><option value="practical">推奨：総合＋実戦5役割すべて70未満</option><option value="overall">総合スコアだけ70未満</option><option value="battle">総合＋先発・終盤・交代すべて70未満</option><option value="strict">全7項目すべて70未満</option></select></div>
<div><label for="lowThreshold">スコア未満</label><input id="lowThreshold" type="number" value="70" min="1" max="100" step="0.1"></div></div>
<label class="checkline" for="lowExcludeFavorites"><input id="lowExcludeFavorites" type="checkbox">診断用：お気に入り除外（任意）</label>
<div class="actions"><button id="lowSearchRun">判定理由を確認</button></div>
<p class="note">Pokémon GOの「Show Evolutionary Line」はOFF推奨。ランキング未掲載の個体は低スコアと断定できません。進化先が低スコアでも、元の個体が未評価なら別の要確認候補です。</p>
<p id="lowScoreSummary" class="note" aria-live="polite">データの判定内容を確認できます。</p>
<p id="lowExclusionSummary" class="note"></p>
<details id="lowEvolutionProtected" hidden><summary>進化先を考慮して保護した個体</summary><div id="lowEvolutionNames" class="note" style="white-space:pre-wrap"></div></details>
<details id="lowManual" hidden><summary>姿・検索名などで安全に検索できない個体</summary><div id="lowManualNames" class="note" style="white-space:pre-wrap"></div></details>
<details id="lowUnrankedReview" hidden><summary>ランキング未掲載の要確認候補（ゴチム等）</summary><div id="lowUnrankedNames" class="note" style="white-space:pre-wrap"></div></details>
</section>
<section class="card"><h2>まとめて貼り付け</h2><p class="note">ポケモン・技・個体値をまとめて取り込めます。読み取りCP付きの「0,11,12 CP717 | ヌオー」にも対応します。日本語の種名、技省略、複数の進化先を含む「個体値リスト」「個体値厳選」、CSVに対応します。</p><label for="importText">コマンドまたはCSV</label><textarea id="importText" spellcheck="false" placeholder="個体値厳選&#10;quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE&#10;0,11,12&#10;3,13,8&#10;2,15,13"></textarea><div class="actions"><button id="importInput" class="secondary">貼り付けた内容を取り込む</button></div><p class="note">取り込みだけでは計算を開始しません。# クルマユ ハハコモリ のような見出しは、次の個体値を両方へ割り当てます。省略した技は種類ごとに補って表示します。</p></section>
<section class="card" id="queuePanel" hidden><h2>連続計算するポケモン</h2><pre id="queuePreview"></pre><p class="note">表示した順にすべて計算します。複数種の内容は上の貼り付け欄から編集できます。</p><button id="singleForm" class="secondary">単一種のフォームに戻す</button></section>
<section class="card" id="comparisonSettings" tabindex="-1"><h2>2. 比較と推薦の設定</h2>
<div class="meta-presets"><div class="meta-current"><span class="meta-caption">使用中</span><p id="selectedMeta" class="meta-current-name" aria-live="polite">メタプリセットを読み込み中です。</p><span id="metaCurrentCount" class="meta-count"></span><span id="metaCurrentBadges" class="meta-badges"></span></div>
<div class="meta-toolbar"><button id="metaChoose" class="secondary" aria-expanded="false" aria-controls="metaChooser">プリセットを選ぶ</button><button id="metaDownload" class="secondary" type="button">CSVをダウンロード</button><button id="metaCompact" class="secondary" type="button">自動追加を見直す</button><button id="metaExport" class="secondary" disabled>PvPoke用にコピー</button></div>
<p id="metaExportStatus" class="note" aria-live="polite"></p><div id="metaExportParts" class="actions" hidden></div>
<div id="metaExportFallback" hidden><label for="metaExportText">PvPoke貼り付け用（手動コピー）</label><textarea id="metaExportText" readonly spellcheck="false"></textarea></div>
<details class="meta-help"><summary>PvPokeへの貼り付け方</summary><p class="note">PvPokeのBattle → Multi／Matrixで、対戦相手一覧のImport/Exportへ貼り付けてImportを押します。リーグはCP1500にしてください。100件超は分割して確認します。編集後は下の「カスタムメタを追加」へ直接貼り付けるか、TXT・CSVで読み込めます。レベル・個体値付きの8列も種と技だけを保存します。</p></details>
<button id="metaEdit" class="secondary" type="button">選択中のメタの内容を編集</button>
<section id="metaEditor" class="meta-chooser" hidden aria-label="メタのポケモンと技を編集">
<p class="meta-hint">ポケモンと技を日本語・英語の候補から変更できます。右の×で削除。変更は保存するまで反映されません。</p>
<div id="metaEditorCopyName"><label for="metaEditorName">編集用コピーの名前</label><input id="metaEditorName" maxlength="60"></div>
<label for="metaEditorFilter">一覧内を絞り込む</label><input id="metaEditorFilter" type="search" autocomplete="off">
<datalist id="metaEditorSpecies"></datalist><p id="metaEditorCount" class="note"></p><div id="metaEditorRows"></div>
<button id="metaEditorMore" class="secondary" type="button" hidden>さらに50件を表示</button>
<div class="actions"><button id="metaEditorAdd" class="secondary" type="button">ポケモンを追加</button><button id="metaEditorUndo" class="secondary" type="button" disabled>削除を戻す</button></div>
<p id="metaEditorStatus" class="note" role="status" aria-live="polite"></p>
<div class="actions"><button id="metaEditorSave" type="button">変更を保存</button><button id="metaEditorCancel" class="secondary" type="button">変更を破棄して閉じる</button></div></section>
<div id="metaChooser" class="meta-chooser" hidden>
<p class="meta-hint">よく使うプリセット</p><div id="metaQuick" class="meta-quick" role="group" aria-label="よく使うメタ"></div>
<label for="metaAll">すべてのメタプリセット</label><div class="meta-all-row"><select id="metaAll"></select><button id="metaReload" class="secondary" aria-label="一覧を再取得" title="一覧を再取得">↻</button></div>
<div class="meta-settings"><button id="metaFavorite" class="secondary" aria-pressed="false">☆ お気に入り</button><button id="metaDefault" class="secondary">デフォルトにする</button></div>
<p id="metaPresetNote" class="note"></p>
</div><p class="note">カップ別の対戦相手一覧を切り替えます。CP1500対応。出場できるポケモンかどうかはカップのルールも確認してください。</p></div><p class="note">計算条件は右上の「設定」でポケモンごとに指定できます。未設定は通常厳選です。</p><select id="batchMode" hidden aria-hidden="true"><option value="simple">簡易：Default × 6条件</option><option value="detailed">詳細：4つの相手IV × 6条件</option></select>
<select id="evaluation" hidden aria-hidden="true"><option value="app">アプリで自動推薦</option></select>
<label for="focus">重要な相手（英語名・1行1つ、省略可）</label><textarea id="focus" style="min-height:80px" placeholder="Corviknight&#10;Feraligatr"></textarea><p class="note">名前が一致する技構成をすべて重視します。省略時は独自の役割を全対面から探します。</p>
<details  id="moveSettings"><summary>技の設定</summary>
<label class="checkline" for="autoMoves"><input id="autoMoves" type="checkbox"> 有力な技構成も自動で比較</label>
<label for="moveStrategy">自動比較の範囲</label><select id="moveStrategy"><option value="smart">推奨：有力で役割の違う構成に絞る（自動選択は最大6構成）</option><option value="all">全組み合わせを比較（時間がかかります）</option></select>
<p class="note">推奨では威力・エネルギー効率から有力候補を選び、タイプ・発動の速さ・能力変化の違いを優先します。登録した構成と入力で指定した構成は省きません。選外の構成の勝敗は未計算です。</p>
<label for="moveThreshold">残す平均Ratingの下限（500付近の目安）</label><input id="moveThreshold" type="number" min="0" max="1000" value="450" step="1">
<p class="note">全構成が下限未満でも最高平均の構成は表示します。自動比較OFFでは、右上の「設定」で計算対象にした構成をすべて使います。計算対象の登録がない場合は、今回の入力で指定した技を使います。個体ごとのコピー名には採用技の略号を付けます。</p>
<div class="row" id="inputMoves"><div><label for="fast">通常技</label><select id="fast"></select></div><div><label for="charged1">ゲージ技1</label><select id="charged1"></select></div><div><label for="charged2">ゲージ技2</label><select id="charged2"></select></div></div>
<p id="movePlanSummary" class="note" aria-live="polite"></p>
</details>
<details><summary>自動推薦の基準を調整</summary><label for="lead">勝ち方向で採用するRating差（既定20）</label><input id="lead" type="number" min="1" max="1000" step="1" value="20"><p class="note">500の境界を越える役割は差にかかわらず確認します。負けたままのRating差は自動推薦にしません。</p></details>
<label class="checkline" for="forceRecalculate"><input type="checkbox" id="forceRecalculate"> 保存結果を使わず再計算</label><p class="note">同じ対戦条件では過去の結果を再利用します。ゲームデータ・計算コードの更新時は自動で再計算します。</p>
<div class="actions"><button id="run">計算して推薦を表示</button><button id="cancelRun" class="secondary" type="button" hidden>計算を中止</button><button id="resume" class="secondary" hidden>前の計算を再開</button><button id="disconnect" class="secondary">接続を解除</button></div><p class="note">CP1500以下・最大Lv50。自分0/相手1、自分0/相手2、自分1/相手2も比較します。</p></section>
<section class="card" id="results" tabindex="-1" hidden></section>
<details class="card" id="metaManager">
<summary>カスタムメタを追加</summary>
<p class="note">貼り付けたメタやTXT・CSVを名前付きで最大50件保存できます。追加・置換は選択中のカスタムメタへ保存します。公式プリセットは別名で保存してください。自動追加は手動構成にない対応が増える場合だけ、各種1構成・全体8構成までです。先頭8種・相手32種・追加候補各6構成の標本で判定し、全技の対応保証はしません。普段使うメタは選択欄からデフォルトに指定してください。</p>
<p class="note" id="metaStatus">現在のメタを確認しています。</p>
<label for="metaSaveMode">保存方法</label><select id="metaSaveMode"><option value="create">別のプリセットとして保存</option><option value="append">選択中の手動構成へ追加</option><option value="replace">選択中のメタを全置換</option></select><label for="metaName">保存するプリセット名</label><input id="metaName" maxlength="60" placeholder="普段使うメタ">
<label for="metaText">メタを貼り付け</label><textarea id="metaText" spellcheck="false" aria-describedby="metaInputHelp" placeholder="quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE"></textarea>
<div class="meta-toolbar"><button id="metaTextPreview" class="secondary" type="button">貼り付けた内容を確認</button></div>
<details><summary>ファイルから読み込む（TXT／CSV）</summary><label for="metaFile">メタ一覧（最大80KB）</label><input id="metaFile" type="file" accept=".txt,.csv,text/plain,text/csv"></details>
<p class="note" id="metaInputHelp">species,fast,charged1,charged2 の4列、または level,atk,def,hp を加えた8列を貼り付けできます。保存するのは種と技だけです。入力のレベル・個体値は使わず、計算時は選択した対戦相手の個体値条件を使います。同じ種と技構成はまとめ、最大500技構成まで。保存方法と対象メタを選び、「内容を確認」→保存の順に操作してください。追加では同種の別技も保持し、全置換では入力にない構成を除きます。</p>
<div id="metaPreview" class="status" hidden></div>
<div class="actions"><button id="metaApply" class="secondary" disabled>別のプリセットとして保存</button><button id="metaCancel" class="secondary" type="button">選択を取り消す</button></div>
<p id="metaNotice" class="note" aria-live="polite"></p>
</details>
<section class="card"><h2>1. ポケモンと個体値</h2><label for="preset">登録プリセット（任意）</label><select id="preset"></select><p class="note" id="presetHint"></p><label for="allSpecies">全ポケモンから選ぶ</label><select id="allSpecies"></select><label for="species">ポケモン名・英語ID（直接入力）</label><input id="species" list="speciesList" value="quagsire" autocomplete="off"><datalist id="speciesList"></datalist>
<div class="actions" role="group" aria-label="登録区分を一括変更"><button id="bulkNormal" class="secondary">すべて通常に変更</button><button id="bulkShadow" class="secondary">すべてシャドウに変更</button><button id="bulkPurified" class="secondary">すべてリトレーンに変更</button><button id="bulkStatusUndo" class="secondary" hidden>区分変更を元に戻す</button></div><p class="note" id="bulkStatusNote">対象：フォーム、または取り込み済みの全種類。区分だけを修正し、個体値・CPは変えません。リトレーン済みの個体値・CPを入力してください。変更後に再計算します。</p>
<label for="ivs">攻撃,防御,HP（1行1体・最大4,096通り）</label><textarea id="ivs" spellcheck="false" placeholder="0,11,12&#10;3,13,8&#10;2,15,13"></textarea></section>
</div></main><script>
'use strict';
const el=id=>document.getElementById(id);let calculating=false,stopRequested=false,stopPromise=null,stopError=null;
let importedSingle=null;let credential='',catalog={},presets=[],active=false,runRef=null,lastResult=null,importedJobs=null,batchState=null,metaPending=null,metaWorking=false;let metaState=null,selectedMetaId=null,metaExportWorking=false;let moveCatalog={},readerImportPending=false,readerImportInFlight=false,readerInputText=null;
function message(s,error=false){const x=el('message');x.hidden=false;x.textContent=s;x.className='status'+(error?' error':'');}
const SELECTION_MODE_STORAGE='pvpoke-app-selection-modes-v1';
function readSelectionModes(){
 try{const raw=localStorage.getItem(SELECTION_MODE_STORAGE);if(!raw||raw.length>200000)return Object.create(null);
  const value=JSON.parse(raw),out=Object.create(null);if(!value||typeof value!=='object'||Array.isArray(value))return out;
  for(const [id,mode] of Object.entries(value))if(/^[a-z0-9_]+$/.test(id)&&!['__proto__','constructor','prototype'].includes(id)&&mode==='detailed')out[id]='detailed';return out;
 }catch{return Object.create(null);}
}
let selectionModes=readSelectionModes(),selectionModeLimit=50;
function speciesSelectionMode(id){return selectionModes[id]==='detailed'?'detailed':'simple';}
function selectionModeLabel(id){return speciesSelectionMode(id)==='detailed'?'詳細厳選':'通常厳選';}
function freezeSelectionModes(jobs){return jobs.map(job=>({...job,batch_mode:speciesSelectionMode(job.candidate.species)}));}
function setSpeciesSelectionMode(id,detailed){
 if(!Object.hasOwn(catalog,id))return false;
 if(detailed)selectionModes[id]='detailed';else delete selectionModes[id];
 let saved=true;try{localStorage.setItem(SELECTION_MODE_STORAGE,JSON.stringify(selectionModes));}catch{saved=false;}
 el('selectionModeStatus').textContent=saved?'設定を保存しました。次の計算から適用します。':'保存できませんでした。現在の画面では使えますが、再読込すると失われます。';
 refreshQueuePreview();
 return saved;
}
function queuePreviewText(jobs){
 return jobs.map((job,i)=>{
  const sid=job.candidate.species,registered=enabledMovesets(sid),auto=el('autoMoves').checked;
  const profiles=auto?[job.candidate,...registered]:(registered.length?registered:[job.candidate]);
  const labels=[...new Set(profiles.map(moveLabel))];
  const heading=(i+1)+'. '+job.name+'：'+job.candidate_count+'個体 ｜ '+selectionModeLabel(sid);
  const source=auto?'指定技（自動比較の候補を追加）':registered.length?'登録技':'入力の技';
  return [heading,'   '+source+'：'+labels.join(' ｜ '),...(job.warnings||[])].join('\n');
 }).join('\n\n');
}
function refreshQueuePreview(){if(importedJobs)el('queuePreview').textContent=queuePreviewText(importedJobs);}
function settingsSpeciesName(id){
 const pokemon=catalog[id],name=pokemon.name_ja||pokemon.name||id;
 return id==='oinkologne'&&catalog.oinkologne_female&&!catalog.oinkologne_male?name+'（'+(pokemon.name_ja?'オス':'Male')+'）':name;
}
function renderSelectionModes(){
 const normalize=value=>String(value||'').normalize('NFKC').toLowerCase().trim();
 const query=normalize(el('selectionModeFilter').value);
 const ids=Object.keys(catalog).filter(id=>[id,settingsSpeciesName(id),catalog[id].name,...(catalog[id].aliases||[])].some(v=>normalize(v).includes(query)))
  .sort((a,b)=>settingsSpeciesName(a).localeCompare(settingsSpeciesName(b),'ja'));
 const rows=el('selectionModeRows');rows.replaceChildren();
 if(!ids.length)node('p','一致するポケモンはありません。',rows,'note');
 for(const id of ids.slice(0,selectionModeLimit)){
  const item=node('div','',rows),row=node('div','',item,'species-mode-row');
  const name=settingsSpeciesName(id),title=node('button',name,row,'species-mode-name');
  title.type='button';title.setAttribute?.('aria-expanded','false');title.setAttribute?.('aria-controls','species-movesets-'+id);
  const state=node('span',selectionModeLabel(id),row,'species-mode-state'),toggle=document.createElement('input');
  toggle.type='checkbox';toggle.id='species-mode-'+id;toggle.checked=speciesSelectionMode(id)==='detailed';toggle.disabled=active;
  toggle.setAttribute?.('role','switch');toggle.setAttribute?.('aria-label',name+'の詳細厳選');
  toggle.onchange=()=>{if(active){toggle.checked=speciesSelectionMode(id)==='detailed';return;}setSpeciesSelectionMode(id,toggle.checked);state.textContent=selectionModeLabel(id);};row.append(toggle);
  const panel=node('div','',item,'species-movesets');panel.id='species-movesets-'+id;panel.hidden=true;
  title.onclick=()=>{
   panel.hidden=!panel.hidden;
   title.setAttribute?.('aria-expanded',String(!panel.hidden));
   if(!panel.hidden)renderSpeciesMovesets(id,panel);
   else panel.replaceChildren();
  };
 }
 el('selectionModeMore').hidden=ids.length<=selectionModeLimit;
}
el('selectionSettingsOpen').onclick=()=>{el('selectionSettings').hidden=false;el('selectionSettings').showModal?.();el('selectionSettingsOpen').setAttribute?.('aria-expanded','true');selectionModeLimit=50;renderSelectionModes();el('selectionModeFilter').focus?.();};
el('selectionSettingsClose').onclick=()=>{el('selectionSettings').close?.();el('selectionSettings').hidden=true;el('selectionSettingsOpen').setAttribute?.('aria-expanded','false');el('selectionSettingsOpen').focus?.();};
el('selectionSettings').oncancel=()=>{el('selectionSettings').hidden=true;el('selectionSettingsOpen').setAttribute?.('aria-expanded','false');};
el('selectionModeFilter').oninput=()=>{selectionModeLimit=50;renderSelectionModes();};
el('selectionModeMore').onclick=()=>{selectionModeLimit+=50;renderSelectionModes();};
function calculationRequestId(){return 'web-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+'-'+Math.random().toString(36).slice(2);}
const retryableReads=new Set(['catalog','result','meta-presets','meta-preset-export','meta-status','meta-preview','low-score','import']);
async function api(path,data={}){
 const payload=path==='run'?{...data,request_id:data.request_id||calculationRequestId()}:data;
 const safe=retryableReads.has(path)||(path==='run'&&!!payload.request_id);
 for(let attempt=0;;attempt++){
  const headers={'Content-Type':'application/json'};if(credential)headers.Authorization='Bearer '+credential;
  const controller=typeof AbortController!=='undefined'?new AbortController():null;
  const timer=controller?setTimeout(()=>controller.abort(),45000):null;
  try{
   const r=await fetch('/app-api/'+path,{method:'POST',credentials:'same-origin',headers,body:JSON.stringify(payload),...(controller?{signal:controller.signal}:{})});
   if(r.status===401){const e=Error('ログインの有効期限が切れました。接続キーで再接続してください。');e.status=401;throw e;}
   let out;try{out=await r.json();}catch{const e=Error('応答の途中で通信が切れました');e.transient=true;throw e;}
   if(!r.ok){const e=Error(out.error||'通信エラー');e.status=r.status;e.transient=[408,429,500,502,503,504].includes(r.status);throw e;}
   return out;
  }catch(e){
   const temporary=e.transient||e.name==='TypeError'||e.name==='AbortError'||/failed to fetch|network|fetch failed/i.test(e.message);
   if(!safe||!temporary||attempt>=5)throw e;
   if(calculating)message('通信を再接続しています（'+(attempt+1)+' / 5）。完了済みの結果と実行中の計算は保持しています。');
   await new Promise(resolve=>typeof setTimeout==='function'?setTimeout(resolve,Math.min(5000,750*2**attempt)):resolve());
  }finally{if(timer!==null)clearTimeout(timer);}
 }
}
// Keep the legacy cleanup tool accessible by explicit URL only.
// The ordinary IV selection screen no longer advertises low-score cleanup.
function updateLowScorePanelVisibility(){
 el('lowScorePanel').hidden=new URLSearchParams(location.search||'').get('tool')!=='low-score';
}
let lowScoreResults=null;
async function loadLowScores(){
 const button=el('lowSearchRun');button.disabled=true;button.textContent='確認中…';
 try{
  const result=await api('low-score',{mode:el('lowMode').value,threshold:Number(el('lowThreshold').value),exclude_favorites:el('lowExcludeFavorites').checked});
  lowScoreResults=result;
  el('lowScoreSummary').textContent='保存データ '+result.source_date+' / 評価済みの対象 '+result.selected_count+'件 / 検索可能 '+result.searchable_count+'件（内部検索式 '+result.queries.length+'個） / 未掲載・要確認 '+(result.unranked_review_count||0)+'種類。';
  const why=result.exclusion_reasons||{};
  el('lowExclusionSummary').textContent='対象から保護・除外した理由：他の実戦役割で70点以上 '+(why.specialist_preserved||0)+'件 / 進化先が高スコア・未評価 '+(why.evolution_protected||0)+'件 / 姿・英語名の検索が不確実 '+(why.form_or_name_unsearchable||0)+'件 / 未掲載で低評価を確認できない '+(why.unranked_not_verified||0)+'種類 / 未掲載で進化先に高評価あり '+(why.unranked_strong_evolution||0)+'種類 / 未掲載で姿・名前を区別できない '+(why.unranked_uncertain_form_or_name||0)+'種類。未掲載候補は低スコア確定ではありません。';
  el('lowEvolutionProtected').hidden=!result.evolution_protected_count;
  el('lowEvolutionNames').textContent=(result.evolution_protected||[]).map(x=>x.name+' → '+x.evolves_to.join('、')+'：'+x.reason).join('\n');
  el('lowManual').hidden=!result.manual_review_count;
  el('lowManualNames').textContent=(result.manual_review||[]).map(x=>x.name+'（総合'+x.overall+'）：'+x.reason).join('\n');
  el('lowUnrankedReview').hidden=!(result.unranked_review_count>0);
  el('lowUnrankedNames').textContent=(result.unranked_review||[]).map(x=>x.name+'（No.'+x.dex+'）→ '+x.evolves_to.join('、')+'：'+x.reason).join('\n');
 }catch(e){el('lowScoreSummary').textContent='判定理由を取得できませんでした：'+e.message;}
 finally{button.disabled=false;button.textContent='判定理由を確認';}
}
el('lowSearchRun').onclick=()=>loadLowScores();
el('lowExcludeFavorites').onchange=()=>loadLowScores();
function option(select,values,selected,label=v=>v){select.replaceChildren();for(const v of values){const o=document.createElement('option');o.value=v;o.textContent=label(v);select.append(o);}if(values.includes(selected))select.value=selected;}
function fillMoveFields(sid,row,[fast,charged1,charged2],label){
 const p=catalog[sid]||{},charges=p.chargedMoves||[];
 option(fast,p.fastMoves||[],row.fast,label);
 option(charged1,charges,row.charged1,label);
 option(charged2,charges,row.charged2,label);
 if(charged1.value===charged2.value){
  const alternative=charges.find(move=>move!==charged1.value);
  if(alternative)charged2.value=alternative;
 }
}
function moves(row={},sid=el('species').value){fillMoveFields(sid,row,['fast','charged1','charged2'].map(el));}
function presetKey(p){return p.key||[p.species,p.fast,p.charged1,p.charged2].join('|');}
function currentCandidate(){return {species:el('species').value.trim(),fast:el('fast').value,charged1:el('charged1').value,charged2:el('charged2').value};}
function setCandidate(p){inputPokemonStatus=null;el('species').value=p.species;el('allSpecies').value=p.species;moves(p);const found=presets.find(x=>['species','fast','charged1','charged2'].every(k=>x[k]===p[k]));el('preset').value=found?presetKey(found):'';}
function setPreset(){const p=presets.find(x=>presetKey(x)===el('preset').value);if(p)setCandidate(p);}
function resolveTypedSpecies(){const raw=el('species').value.normalize('NFKC').trim().toLowerCase();if(['gourgeist','pumpkaboo','パンプジン','バケッチャ'].includes(raw)){message('このポケモンはサイズごとに能力が異なります。こだましゅ/XS、ちゅうだましゅ/通常、おおだましゅ/XL、ギガだましゅ/XXLを指定してください。',true);return;}const found=Object.entries(catalog).filter(([sid,p])=>[sid,p.name,p.name_ja,...(p.aliases||[])].some(x=>x&&String(x).normalize('NFKC').trim().toLowerCase()===raw));if(found.length===1)el('species').value=found[0][0];else if(found.length>1)message('複数のフォルムが一致しました。サイズやフォルムを指定してください。',true);}

function setBusy(value){active=value;for(const id of ['bulkNormal','bulkShadow','bulkPurified','bulkStatusUndo'])el(id).disabled=value;for(const id of ['run','resume','disconnect','importInput','singleForm','forceRecalculate','autoMoves','moveStrategy','moveThreshold','fast','charged1','charged2'])el(id).disabled=value;for(const id of ['preset','allSpecies','species','ivs'])el(id).disabled=value||!!importedJobs;el('metaFile').disabled=value;el('metaApply').disabled=value||!metaPending||metaWorking;el('run').textContent=value?'計算を確認中…':'計算して結果を表示';el('cancelRun').hidden=!(value&&calculating);el('cancelRun').disabled=!(value&&calculating)||stopRequested;if(!el('selectionSettings').hidden)renderSelectionModes();syncMetaControls();if(!value&&readerImportPending&&!readerImportInFlight)Promise.resolve().then(autoImportReader);}
function node(tag,text,parent,cls=''){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;parent.append(n);return n;}
async function copy(text,button){try{await navigator.clipboard.writeText(text);button.textContent='コピーしました';}catch{const root=el('message');message('コピーできませんでした。下の欄から選択してコピーしてください。',true);const area=node('textarea',text,root);area.value=text;area.readOnly=true;area.focus();area.select();}}
// Result labels are resolved against the active catalog, including form names.
let nameEntries=[],displayedResults=[],opponentLabels=new Map(),nicknameBindings=[];
function prepareLabels(){opponentLabels.clear();nameEntries=Object.entries(catalog).map(([sid,p])=>({sid,...p})).sort((a,b)=>(b.name||'').length-(a.name||'').length);}
function opponentLabel(value){const text=String(value||'');if(opponentLabels.has(text))return opponentLabels.get(text);const found=nameEntries.find(p=>p.name&&(text===p.name||text.startsWith(p.name+' ')));const label=found?{name:found.name_ja||found.name,code:found.nickname_code||null,detail:text.slice(found.name.length)}:{name:text,code:null,detail:''};opponentLabels.set(text,label);return label;}
function shieldCode(shield){return {s0:'00',s1:'11',s2:'22',i0y1:'01',i0y2:'02',i1y2:'12'}[shield]||'';}
function conditionLabel(e){const code=shieldCode(e.shield);const mode={default:'標準IV',rank1:'SCP1位IV',attack:'攻撃重視IV',defense:'防御重視IV'}[e.mode]||e.mode;return mode+'・'+(code?'自分シールド'+code[0]+' / 相手'+code[1]:e.shield);}
function outcome(e){return e.rating>500?'勝ち':e.rating===500?'引き分け':'負け';}
function evidenceText(e){const label=opponentLabel(e.opponent);return label.name+label.detail+'｜'+conditionLabel(e)+'｜'+outcome(e)+'・Rating '+e.rating+'（他候補の最高 '+(e.next_best??'比較なし')+'）';}
function matchupNames(row,win){return [...new Set((row.evidence||[]).filter(e=>win?e.rating>500:e.rating===500).map(e=>opponentLabel(e.opponent).name))];}
function primaryEvidence(row){return (row.evidence||[]).find(e=>e.rating>500)||(row.evidence||[])[0];}
function summaryEvidence(row){
 const seen=new Set(),summary=[];
 // Evidence is already ordered by focus, uniqueness and shield relevance.
 for(const e of row.evidence||[]){
  if(e.rating<500)continue;
  const name=opponentLabel(e.opponent).name;
  if(seen.has(name))continue;
  seen.add(name);summary.push(e);
  if(summary.length===3)break;
 }
 return summary;
}
// Check assembled nicknames as well as individual codes; reject unknown patterns.
const blockedNickname=/(anal|ass|bitch|cunt|dick|fuck|nazi|porn|sex|shit|slut)/i;
function validNickname(t){return t.length<=12&&/^[A-Za-z0-9><=]+$/.test(t)&&!blockedNickname.test(t.replace(/[^A-Za-z]/g,''));}
function codeChoices(sid,width){
 const seed=String(catalog[sid]?.nickname_code||'').replace(/[^A-Za-z0-9]/g,'');
 const name=sid.split('_')[0].replace(/[^A-Za-z]/g,'');
 if(!seed||!name)return [];
 const opts=[seed.slice(0,width),name.slice(0,width),
  seed[0]+seed.slice(1).slice(-Math.max(0,width-1)),
  name[0]+name.slice(1).slice(-Math.max(0,width-1)),
  seed[0]+seed.slice(2,2+width-1),name[0]+name.slice(2,2+width-1)];
 return [...new Set(opts.filter(x=>x.length>=Math.min(2,width)&&x.length<=width&&/^[A-Za-z0-9]+$/.test(x)))];
}
function nicknameMembers(result,row,ivs){
 const members=[{result,row,sid:result.candidate.species}];
 const sections=result.source_sections||[];
 if(!sections.length)return members;
 for(const other of displayedResults){
  if(other===result||other.candidate?.species===result.candidate.species||
   (isGourgeist(result.candidate.species)&&isGourgeist(other.candidate?.species))||
   !(other.source_sections||[]).some(x=>sections.includes(x)))continue;
  const match=(other.selection?.recommendations||[]).find(r=>
   r.ivs===ivs||(r.equivalent_candidates||[]).some(x=>x.ivs===ivs));
  if(match)members.push({result:other,row:match,sid:other.candidate.species});
 }
 members.sort((a,b)=>displayedResults.indexOf(a.result)-displayedResults.indexOf(b.result));
 return members;
}
function nicknameFor(result,row,ivs=row.ivs){
 const members=nicknameMembers(result,row,ivs);
 if(members.some(m=>m.row.chosen_moves))return movesetNickname(members);
 // Only documented PvPoke evidence is compared; unseen battles are not inferred.
 const matches=members.flatMap(member=>(member.row.evidence||[])
  .filter(e=>Number.isFinite(e.rating)&&opponentLabel(e.opponent).code&&shieldCode(e.shield))
  .map(e=>({member,e,opponent:opponentLabel(e.opponent)})))
  .sort((a,b)=>(b.e.rating>500)-(a.e.rating>500)||b.e.rating-a.e.rating||
    Number(String(b.member.row.grade||'').startsWith('S'))-Number(String(a.member.row.grade||'').startsWith('S')));
 const best=matches[0];
 if(!best||members.length>3)return null;
 const grade=String(best.member.row.grade||'?').startsWith('S')?'S':String(best.member.row.grade||'?').startsWith('A')?'A':'?';
 const sign=best.e.rating>500?'>':best.e.rating===500?'=':'<', suffix=sign+best.opponent.code+shieldCode(best.e.shield);
 // Two stages: 3 letters for the best-Rating stage, 2 for the other.
 // Three stages: 2 per stage, grade omitted to retain opponent and shields.
 const labelBudget=12-grade.length-suffix.length;
 const primaryWidth=Math.min(3,labelBudget-2);
 const widths=members.length===1?[4]:members.length===2?
  members.map(m=>m===best.member?primaryWidth:2):[2,2,2];
 if(members.length===2&&primaryWidth<2)return null;
 const candidates=members.map((m,i)=>codeChoices(m.sid,members.length===1?
  Math.min(4,String(catalog[m.sid]?.nickname_code||'').length):widths[i]));
 if(candidates.some(x=>!x.length))return null;
 const prefix=members.length===3?'':grade;
 function select(i,codes){
  if(i===members.length){
   if(new Set(codes.map(x=>x.toLowerCase())).size!==codes.length)return null;
   const text=prefix+codes.join('')+suffix;
   return validNickname(text)?{text,codes}:null;
  }
  for(const code of candidates[i]){
   const picked=select(i+1,[...codes,code]);
   if(picked)return picked;
  }
  return null;
 }
 const picked=select(0,[]);
 if(!picked)return null;
 const stages=members.map((m,i)=>picked.codes[i]+'＝'+(catalog[m.sid]?.name_ja||catalog[m.sid]?.name||m.sid));
 return {text:picked.text,description:grade+'＝優先候補評価 / '+stages.join(' / ')+
  ' / '+sign+'＝'+outcome(best.e)+' / '+best.opponent.code+'＝'+best.opponent.name+
  ' / '+conditionLabel(best.e)+' / Rating '+best.e.rating+
  (members.length>1?'（同じ個体値・同じ入力区間の'+members.length+'種類を比較）':'')};
}
// Source records describe the physical Pokemon before powering up/evolving.
// Repair old saved selection results too, without changing the source CP or IV.
// New server-generated searches already use &alola / &galar / &hisui / &paldea.
function normalizedRegionalSearch(search){
 if(typeof search!=='string')return search;
 const terms={alolan:'alola',galarian:'galar',hisuian:'hisui',paldean:'paldea'};
 search=search.replace(/^Nidoran\s*(?:\(\s*(Female|Male)\s*\)|([♀♂])|(?:_|\s+)(Female|Male))(?=&|$)/i,(_,a,b,c)=>'Nidoran&'+(['female','♀'].includes((a||b||c).toLowerCase())?'female':'male'));
 return search.replace(/^flab(?:é|e\u0301|e)b(?:é|e\u0301|e)(?=&|$)/i,'669').replace(/^(.+?)\s*\(\s*(Alolan|Galarian|Hisuian|Paldean)\s*\)(?:\s*\(\s*Shadow\s*\))?(?=&|$)/i,
  (_match,base,adjective)=>base.trim()+'&'+terms[adjective.toLowerCase()]);
}
function statusSearch(search,status){
 if(!status)return normalizedRegionalSearch(search);
 const parts=normalizedRegionalSearch(search).split('&').filter(x=>!['shadow','!shadow','purified','!purified'].includes(x.toLowerCase()));
 if(status==='shadow')parts.push('shadow');
 else if(status==='purified')parts.push('purified');
 else parts.push('!shadow','!purified');
 return parts.join('&');
}
function xxlProtectedSearch(search){
 if(!search||typeof search!=='string')return search;
 // Ordinary XXL individuals must remain in exact-IV search results.
 const parts=search.split('&');
 // Pumpkin average form genuinely needs size exclusions; ordinary individuals do not.
 if(/^(Pumpkaboo|Gourgeist)$/i.test(parts[0])&&['!xxs','!xs','!xl'].every(x=>parts.includes(x)))return search;
 return parts.filter(term=>term.trim().toLowerCase()!=='!xxl').join('&');
}
function individualSearches(result,iv){
 const matches=(result.source_records||[]).filter(r=>r.ivs===iv.ivs);
 // A size-group slot represents one owned Pokémon when the reader supplies CP.
 const records=result.gourgeist_group?matches.slice(0,1):matches;
 return records.length?records.map(r=>({search:xxlProtectedSearch(statusSearch(r.search_string,result.pokemon_status)),cp:r.cp,species:r.species})):[{search:xxlProtectedSearch(statusSearch(iv.search_string,result.pokemon_status))}];
}
function overlayExport(results){
 recommendationExportText(results); // Validate every pair before writing anything.
 const items=results.flatMap(result=>(result.selection?.recommendations||[]).flatMap(row=>
  [row,...(row.equivalent_candidates||[])].flatMap(iv=>individualSearches(result,iv).map(source=>({
   search:source.search,nickname:nicknameFor(result,row,iv.ivs).text,ivs:iv.ivs,
   cp:source.cp||null,species:source.species||result.candidate.species,
   target_species:result.candidate.species,
   target_name:catalog[result.candidate.species]?.name_ja||result.display_name||catalog[result.candidate.species]?.name||result.candidate.species
  })))));
 return JSON.stringify({format:'pokemoniv-overlay-v2',items});
}
async function copyOverlay(results,button){try{await copy(overlayExport(results),button);}catch(e){message(e.message,true);}}
function recommendationExport(result){
 return (result.selection?.recommendations||[]).flatMap(row=>
  [row,...(row.equivalent_candidates||[])].flatMap(iv=>{
   const nick=nicknameFor(result,row,iv.ivs);
   if(!nick)throw Error('ニックネームを安全に生成できません。種名・略号を確認してください。');
   if(!iv.search_string)throw Error('検索式を確認できない個体があります。結果を再取得してください。');
   return individualSearches(result,iv).map(source=>{
    if(!source.search)throw Error('検索式が欠けています。再度取り込んでください。');
    return source.search+'\n'+nick.text;
   });
  })).join('\n');
}
function recommendationExportText(results){
 const available=results.filter(r=>r.selection?.recommendations?.length);
 if(!available.length)throw Error('共有する推薦個体がありません。');
 return available.map(recommendationExport).join('\n');
}
async function copyRecommendations(results,button){try{await copy(recommendationExportText(results),button);}catch(e){message(e.message,true);}}
// Chrome on Android can open an installed reader directly from the user's click.
// Keep the Sharesheet path for other browsers and payloads that are too long for an Intent URL.
function launchAndroidOverlay(text){
 if(!/Android/i.test(navigator.userAgent||'')||!/Chrome|EdgA/i.test(navigator.userAgent||''))return false;
 if(typeof window==='undefined'||typeof window.location?.assign!=='function'||typeof TextEncoder==='undefined'||typeof btoa!=='function')return false;
 const bytes=new TextEncoder().encode(text);
 if(bytes.length>26000)return false;
 let binary='';
 for(let i=0;i<bytes.length;i+=4096)binary+=String.fromCharCode(...bytes.subarray(i,i+4096));
 const payload=btoa(binary).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
 const url='intent://import?payload='+payload+
  '#Intent;scheme=pokemonivreader;package=com.example.pokemonivreader;end';
 window.location.assign(url);
 return true;
}
async function shareRecommendations(results,button){
 let text;
 try{text=overlayExport(results);}catch(e){message(e.message,true);return;}
 try{if(launchAndroidOverlay(text))return;}catch(e){/* use the standard Sharesheet */}
 if(typeof navigator.share!=='function'){
  await copy(text,button);
  message('このブラウザは直接共有に対応していません。コピーした内容をAndroidの「厳選コピーリスト」で貼り付けてください。');
  return;
 }
 try{
  await navigator.share({title:'厳選コピーリスト',text});
  message('Androidの共有先で「厳選コピーリスト」を選ぶと、自動保存してオーバーレイを表示します。');
 }catch(e){
  if(e?.name==='AbortError')return;
  message('Androidへの共有を開始できませんでした。既存の「すべてコピー」ボタンから取り込めます。',true);
 }
}
function renderSearch(row,parent,result){if(!row.search_string)return;for(const source of individualSearches(result||{},row)){node('label',source.cp?'検索式（読み取り時CP'+source.cp+'）':'検索式',parent);node('code',source.search,parent,'search');const b=node('button','検索式をコピー',parent);b.onclick=()=>copy(source.search,b);}}
function refreshNicknames(){
 for(const item of nicknameBindings){
  const nick=nicknameFor(item.result,item.row,item.ivs);
  item.label.textContent=nick?'ニックネーム（'+nick.text.length+'/12文字）':'ニックネーム（自動生成不可）';
  item.code.textContent=nick?nick.text:'';
  item.button.disabled=!nick;
  item.button.textContent='ニックネームをコピー';
  item.note.textContent=nick?nick.description:'安全な12文字以内の略号を生成できません。個体値と略号を確認してください。';
 }
}
function renderNickname(result,row,parent,ivs=row.ivs){
 const label=node('label','',parent),code=node('code','',parent,'search');
 const button=node('button','ニックネームをコピー',parent);
 const explanation=node('details','',parent);node('summary','ニックネームの意味',explanation);
 const note=node('p','',explanation,'note');
 nicknameBindings.push({result,row,ivs,label,code,button,note});
 button.onclick=()=>{const nick=nicknameFor(result,row,ivs);if(nick)copy(nick.text,button);};
}
function updateAllCopy(){
 const available=displayedResults.filter(r=>r.selection?.recommendations?.length);
 const ordinary=available.filter(r=>!r.gourgeist_group).length;
 el('allCopyActions').hidden=ordinary+Number(ordinary<available.length)<2;
}
function renderCopyActions(parent,results,all=false){
 const actions=node('div','',parent,'actions');
 const copyPairs=node('button',all?'全種類の検索式とニックネームをコピー':'検索式とニックネームをすべてコピー',actions);
 copyPairs.onclick=()=>copyRecommendations(results,copyPairs);
 const overlayCopy=node('button','オーバーレイ用にコピー',actions,'secondary');
 overlayCopy.onclick=()=>copyOverlay(results,overlayCopy);
 const share=node('button','Androidへ送る',actions,'secondary');
 share.onclick=()=>shareRecommendations(results,share);
 return actions;
}
function resetResults(){
 const root=el('results');
 root.replaceChildren();displayedResults=[];nicknameBindings=[];
 const actions=renderCopyActions(root,displayedResults,true);actions.id='allCopyActions';actions.hidden=true;
}
function render(result,append=false){
 lastResult=result;const root=el('results');
 if(!append)resetResults();
 displayedResults.push(result);updateAllCopy();root.hidden=false;
 const panel=node('div','',root),sid=result.candidate.species;
 node('h2',result.display_name||catalog[sid]?.name_ja||result.selection?.english_name||sid,panel);
 if(result.result_cache?.reused)node('p','過去の対戦結果を再利用しました。推薦は今回の条件で確認しています。',panel,'note');
 if(result.meta_preset)node('p','対戦メタ：'+result.meta_preset.name+' / SHA256 '+result.meta_sha256.slice(0,12)+'…',panel,'note');
 node('p',[result.candidate.fast,result.candidate.charged1,result.candidate.charged2].join(' / '),panel,'note');const selection=result.selection;
 if(!selection){node('h2','GPT評価用の比較情報',panel);node('p','今回の比較情報をコピーしてGPTに評価を依頼できます。',panel);const b=node('button','比較情報をコピー',panel);b.onclick=()=>copy('以下のPvPoke実測比較を、個体値厳選の基準で評価してください。おすすめ個体と英語検索式を示してください。\n'+JSON.stringify(result),b);return;}
 if(result.moveset_comparison)renderMovesetComparison(result,panel);
 node('h2','おすすめ個体',panel);
 node('p','検索式ではXXLの実際の身長を比較できないため、通常の検索式からXXLを除外します。XXLは手動で比較し、最大の個体を残してください。サイズがフォルムそのものを表す場合は例外です。',panel,'note');
 if(selection.input_notices)selection.input_notices.forEach(n=>node('p',n,panel,'note'));
 if(selection.minior_experimental)node('p','メテノの戦術比較（試験版）：流星で即撃ち／コアまで温存／状況判断を同じ条件で比較。表示Ratingは各対面で最良の戦術を選んだ上限値です。実機のCP・レベル調整が未検証のため、この結果だけで個体を博士に送らないでください。',panel,'note');
 node('p',(result.moveset_comparison?'技ごとの推薦を統合しています。同じ個体値は1回だけ表示し、その個体の採用技を名前に略します。':'')+'Sは総合本命、Aはその本命にない実戦上の役割を補う個体です。1構成では通常最大4体に絞ります。S/Aは入力候補内の暫定評価で、実際の勝敗を保証するものではありません。',panel,'note');
 if(selection.policy?.version&&selection.policy.version!=='box-first-v3'){
  node('p','保存済みの結果は以前の推薦基準です。最新のS本命・少数厳選を使うには、同じ入力を再計算してください。',panel,'note');
 }
 if(selection.recommendations.length){renderCopyActions(panel,[result]);node('p','検索式→改行→ニックネームの順で、同じ性能の代替個体も含めてコピーします。Androidへの送信は共有先で「厳選コピーリスト」を選んでください。Android Chromeではインストール済みの読み取りアプリを直接開きます。その他は共有メニューを使います。個体値の見出しを引き継ぐ場合は「Androidへ送る」か「オーバーレイ用にコピー」を使ってください。',panel,'note');}
 if(selection.excluded&&(!Array.isArray(selection.excluded)||selection.excluded.length))node('p','計算対象から除外された対面があります：'+JSON.stringify(selection.excluded),panel);
 const searchCounts=new Map();for(const r of selection.recommendations)for(const item of [r,...(r.equivalent_candidates||[])]){for(const source of individualSearches(result,item)){const v=searchCounts.get(source.search)||new Set();v.add(item.ivs);searchCounts.set(source.search,v);}}if([...searchCounts.values()].some(x=>x.size>1))node('p','注意：同じ検索式に異なる個体値が含まれます。検索式は範囲指定なので、名前を付ける前に各個体の攻撃・防御・HPを確認してください。',panel,'note');
 if(selection.unmatched_focus.length)node('p','一致しなかった重要相手：'+selection.unmatched_focus.map(x=>opponentLabel(x).name).join('、'),panel);
 if(!selection.recommendations.length)node('p','自動推薦の根拠が十分な個体はありません。下の保留個体を確認してください。',panel);
 for(const row of selection.recommendations)renderRecommendation(row,panel,result);
 if(selection.covered_candidates?.length){const d=node('details','',panel);node('summary','役割が重複する個体（'+selection.covered_candidates.length+'）',d);for(const row of selection.covered_candidates){node('p',row.ivs+' → '+row.covered_by+'で全条件をカバー',d);if(row.equivalent_candidates?.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 if(selection.additional_candidates?.length){const d=node('details','',panel);node('summary','参考：今回は保存を見送る候補（'+selection.additional_candidates.length+'）',d);node('p','細かな勝敗差も計算していますが、ボックス整理を優先して一括コピーには含めません。',d,'note');for(const row of selection.additional_candidates){node('p',row.ivs+'：'+row.reason+(row.new_viable_conditions?'（追加の互角以上 '+row.new_viable_conditions+'条件）':''),d);if(row.equivalent_candidates?.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 if(selection.review_candidates.length){const d=node('details','',panel);node('summary','保留：'+selection.review_candidates.length+'個体',d);for(const row of selection.review_candidates){node('p',row.ivs+'：'+row.reason,d);if(row.equivalent_candidates.length)node('p','同じ性能：'+row.equivalent_candidates.map(x=>x.ivs).join(', '),d);}}
 const rejected=Object.entries(selection.dominated_by);if(rejected.length){const d=node('details','',panel);node('summary','全条件で他候補以下の個体（'+rejected.length+'）',d);for(const [iv,rivals] of rejected)node('p',iv+' → '+rivals.join(', '),d);}
 refreshNicknames();
}
function renderRecommendation(row,panel,result){
  const card=node('article','',panel,'recommendation');node('h2',row.rank+'位｜'+row.ivs+'｜'+row.grade,card);node('div',row.role,card,'badge');
  if(result.gourgeist_group)node('p',result.display_name||catalog[result.candidate.species]?.name_ja||result.candidate.species,card,'note');
  if(row.gourgeist_gains?.length){
   const list=node('ul','',card,'matchup-summary');
   for(const g of row.gourgeist_gains)node('li',opponentLabel(g.opponent).name+'：'+g.outcome+'（'+conditionLabel(g)+'）',list);
  }
  if(row.chosen_moves)node('p','採用技：'+moveLabel(row.chosen_moves)+' / 平均Rating '+row.moveset_mean.toFixed(1),card,'note');
  if(row.minior_strategy){
   const m=row.minior_strategy,parts=[];
   if(m.hold_win_flip_count)parts.push('コアまでゲージ温存で新たに勝ち '+m.hold_win_flip_count+'条件');
   if(m.adaptive_win_flip_count)parts.push('状況判断で新たに勝ち '+m.adaptive_win_flip_count+'条件');
   if(parts.length){
    node('p',parts.join(' ／ ')+'（戦術選択の試験的評価）',card,'note');
    if(m.hold_win_flip_examples?.length){
     const details=node('details','',card);
     node('summary','ゲージ温存で逆転する対面（例）',details);
     for(const e of m.hold_win_flip_examples)node('p',opponentLabel(e.opponent).name+'・'+e.shield+'：即撃ち '+e.instant+' → 温存 '+e.hold,details,'note');
    }
   }
  }
  // Prefer the actual WIN/DRAW differences from a similar higher-ranked IV.
  // Sharing a displayed opponent or even Rating 511 is not a distinct role.
  const comparison=Boolean(row.comparison_peer),seenNames=new Set(),summary=[];
  for(const e of comparison?(row.comparison_differences||[]):summaryEvidence(row)){
   const name=opponentLabel(e.opponent).name;
   if(seenNames.has(name))continue;
   seenNames.add(name);summary.push(e);
   if(summary.length===3)break;
  }
  if(comparison)node('p','最も似た上位個体 '+row.comparison_peer+' と勝敗が異なる条件（最大3件）',card,'note');
  if(summary.length){const list=node('ul','',card,'matchup-summary');
   for(const e of summary){
    const relative=comparison?'［'+row.comparison_peer+'：'+outcome({rating:e.peer_rating})+'］':'';
    node('li',opponentLabel(e.opponent).name+'：'+outcome(e)+'（'+conditionLabel(e)+'）'+relative,list);
   }
  }
  if(comparison&&!summary.length)node('p','比較根拠を表示できません。結果の再計算をお願いします。',card,'note');
  renderSearch(row,card,result);
  renderNickname(result,row,card);
  if(row.equivalent_candidates.length){const d=node('details','',card);node('summary','全条件で同じ性能の代替個体',d);for(const e of row.equivalent_candidates){node('p',e.ivs,d);renderSearch(e,d,result);renderNickname(result,row,d,e.ivs);}}
  if(row.evidence.length||row.tradeoff){
   const details=node('details','',card);node('summary','推薦根拠をすべて見る（'+row.evidence_count+'条件）',details);node('pre',row.evidence.map(evidenceText).join('\n'),details);
   if(row.tradeoff){const e=row.tradeoff;node('p','苦手になる対面：'+opponentLabel(e.opponent).name+'・'+conditionLabel(e)+' は '+outcome(e)+'（Rating '+e.rating+' / '+e.best_iv+' は '+e.best_rating+'）。',details,'note');}
  }
}
function metaNotice(text,error=false){el('metaNotice').textContent=text;el('metaNotice').style.color=error?'#ffb6b6':'';}
function resetMetaUpload(){metaPending=null;el('metaApply').disabled=true;el('metaPreview').hidden=true;el('metaPreview').textContent='';el('metaFile').value='';el('metaText').value='';}
let metaDraft=null,metaEditorLimit=50;
function metaEditorBlocked(){return active||metaWorking||!!batchState||!!runRef;}
function metaSpeciesLabel(sid){const p=catalog[sid]||{};return [p.name_ja,p.name].filter(Boolean).join(' / ')||sid;}
function metaMoveLabel(id){const m=moveCatalog[id]||{};return [m.name_ja,m.name].filter(Boolean).join(' / ')||id;}
function metaInputKey(value){return String(value||'').normalize('NFKC').toLowerCase().replace(/[\s（）()]/g,'');}
function metaResolveSpecies(value){const key=metaInputKey(value);const matches=Object.entries(catalog).filter(([sid,p])=>[sid,p.name,p.name_ja,...(p.aliases||[]),metaSpeciesLabel(sid)].some(v=>v&&metaInputKey(v)===key));return matches.length===1?matches[0][0]:null;}
function metaResolveMove(value,ids){const key=metaInputKey(value);const matches=ids.filter(id=>[id,moveCatalog[id]?.name,moveCatalog[id]?.name_ja,metaMoveLabel(id)].some(v=>v&&metaInputKey(v)===key));return matches.length===1?matches[0]:null;}
function syncMetaEditor(){
 el('metaEdit').disabled=metaEditorBlocked()||!chosenMeta()||!!metaDraft;
 el('metaEditorSave').disabled=metaEditorBlocked()||!metaDraft;
 el('metaEditorCancel').disabled=metaWorking;
 el('metaEditorAdd').disabled=metaEditorBlocked()||!metaDraft||metaDraft.rows.length>=500;
 el('metaEditorUndo').disabled=metaEditorBlocked()||!metaDraft?.undo;
}
function metaEditorError(text){el('metaEditorStatus').textContent=text;}
async function openMetaEditor(){
 if(metaEditorBlocked()||!chosenMeta()||metaDraft)return;
 const target={...chosenMeta()},revision=metaState.revision;metaWorking=true;syncMetaControls();
 try{
  const data=await api('meta-preset-export',{id:target.id,expected_sha256:target.sha256});
  if(chosenMeta()?.id!==target.id||chosenMeta()?.sha256!==target.sha256)throw Error('メタが変わりました。もう一度開いてください。');
  if(data.id!==target.id||data.sha256!==target.sha256)throw Error('取得したメタが一致しません');
  const rows=String(data.csv||'').trim().split(/\r?\n/).filter(Boolean).map(line=>{
   const fields=line.split(',').map(x=>x.trim());if(fields.length!==4)throw Error('メタの列を読み取れません');
   return {species:fields[0].replace(/-shadow$/,''),fast:fields[1],charged1:fields[2],charged2:fields[3],invalid:{}};
  });
  if(!rows.length||rows.length>500)throw Error('編集対象は1〜500構成です');
  metaDraft={target,revision,rows,dirty:false,undo:null};metaEditorLimit=50;
  el('metaEditorName').value=target.name.slice(0,54)+'（編集）';el('metaEditorCopyName').hidden=['custom','legacy'].includes(target.source);
  el('metaEditorSave').textContent=['custom','legacy'].includes(target.source)?'変更を保存':'編集したコピーを保存';
  el('metaEditor').hidden=false;renderMetaEditor();metaEditorError('保存するまで計算には反映されません。保存後は、この一覧だけを計算対象にします。');
 }catch(e){metaNotice(e.message,true);}finally{metaWorking=false;syncMetaControls();syncMetaEditor();if(metaDraft)renderMetaEditor();}
}
function renderMetaEditor(){
 if(!metaDraft)return;
 const root=el('metaEditorRows');root.replaceChildren();
 const filter=metaInputKey(el('metaEditorFilter').value);
 const filtered=metaDraft.rows.map((row,index)=>({row,index})).filter(({row})=>!filter||metaInputKey(metaSpeciesLabel(row.species)).includes(filter));
 el('metaEditorCount').textContent=metaDraft.rows.length+'構成 / 表示 '+Math.min(filtered.length,metaEditorLimit)+'件'+(metaDraft.dirty?'・未保存':'');
 const speciesList=el('metaEditorSpecies');speciesList.replaceChildren();for(const sid of Object.keys(catalog)){const o=node('option','',speciesList);o.value=metaSpeciesLabel(sid);}
 for(const {row,index} of filtered.slice(0,metaEditorLimit)){
  const card=node('div','',root,'meta-edit-row'),heading=node('div',(index+1)+'. '+metaSpeciesLabel(row.species),card,'meta-edit-heading');
  const remove=node('button','×',card,'secondary meta-edit-remove');remove.type='button';remove.setAttribute?.('aria-label',metaSpeciesLabel(row.species)+'の構成を削除');remove.disabled=metaEditorBlocked();
  remove.onclick=()=>{if(metaEditorBlocked())return;metaDraft.undo={index,row};metaDraft.rows.splice(index,1);metaDraft.dirty=true;renderMetaEditor();syncMetaEditor();};
  const fields=node('div','',card,'meta-edit-fields'),error=node('p','',card,'meta-edit-error');
  function field(label,value,listId,onchange){const wrap=node('label',label,fields),input=node('input','',wrap);input.value=value;input.setAttribute?.('list',listId);input.setAttribute?.('autocomplete','off');input.disabled=metaEditorBlocked();input.oninput=()=>{row.invalid[label]=true;metaDraft.dirty=true;};input.onchange=()=>{if(metaEditorBlocked())return;const ok=onchange(input.value);row.invalid[label]=!ok;error.textContent=ok?'':'候補から正しい'+label+'を選んでください。';};return input;}
  field('ポケモン',catalog[row.species]?metaSpeciesLabel(row.species):'', 'metaEditorSpecies',value=>{
   const sid=metaResolveSpecies(value);if(!sid)return false;const p=catalog[sid];row.species=sid;
   const d=p.default_moves||{};row.fast=p.fastMoves.includes(row.fast)?row.fast:(d.fast||p.fastMoves[0]||'');
   row.charged1=p.chargedMoves.includes(row.charged1)?row.charged1:(d.charged1||p.chargedMoves[0]||'');
   row.charged2=p.chargedMoves.includes(row.charged2)&&row.charged2!==row.charged1?row.charged2:((p.chargedMoves||[]).find(x=>x===d.charged2&&x!==row.charged1)||(p.chargedMoves||[]).find(x=>x!==row.charged1)||'');
   row.invalid={};metaDraft.dirty=true;renderMetaEditor();return true;
  });
  for(const [key,label,pool] of [['fast','技1','fastMoves'],['charged1','技2A','chargedMoves'],['charged2','技2B','chargedMoves']]){
   const ids=catalog[row.species]?.[pool]||[],listId='meta-edit-'+index+'-'+key,list=node('datalist','',card);list.id=listId;
   for(const id of ids){const o=node('option','',list);o.value=metaMoveLabel(id);}
   field(label,metaMoveLabel(row[key]),listId,value=>{const id=metaResolveMove(value,ids);if(!id)return false;row[key]=id;metaDraft.dirty=true;return true;});
  }
  if(Object.values(row.invalid).some(Boolean))error.textContent='候補から種と技を選んでください。';
 }
 el('metaEditorMore').hidden=filtered.length<=metaEditorLimit;syncMetaEditor();
}
async function saveMetaEditor(){
 if(metaEditorBlocked()||!metaDraft)return;
 const draft=metaDraft;
 if(!draft.rows.length||draft.rows.some(r=>!validMoveset(r)||Object.values(r.invalid).some(Boolean))){metaEditorError('各行のポケモン・通常技・異なるゲージ技2つを確認してください。空の一覧は保存できません。');return;}
 const content=draft.rows.map(r=>[r.species,r.fast,r.charged1,r.charged2].join(',')).join('\n')+'\n';
 metaWorking=true;syncMetaControls();syncMetaEditor();renderMetaEditor();
 try{
  const preview=await api('meta-preview',{csv:content});
  const update=['custom','legacy'].includes(draft.target.source);
  const saved=await api('meta-preset-save',{action:update?'update':'create',id:draft.target.id,revision:draft.revision,
   expected_previous_sha256:draft.target.sha256,expected_sha256:preview.sha256,csv:content,
   name:el('metaEditorName').value.trim(),exact_rows:true});
  metaState=saved;selectedMetaId=saved.saved_id;metaDraft=null;el('metaEditor').hidden=true;clearMetaExport();renderMetaChoices();
  metaNotice('保存しました。'+preview.rows+'構成を計算対象にします。削除した構成は自動補完しません。');
 }catch(e){metaEditorError('保存できませんでした。編集内容は残っています：'+e.message);}
 finally{metaWorking=false;syncMetaControls();syncMetaEditor();if(metaDraft)renderMetaEditor();}
}
el('metaEdit').onclick=openMetaEditor;
el('metaEditorSave').onclick=saveMetaEditor;
el('metaEditorCancel').onclick=()=>{if(metaWorking)return;metaDraft=null;el('metaEditor').hidden=true;syncMetaControls();syncMetaEditor();};
el('metaEditorFilter').oninput=()=>{metaEditorLimit=50;renderMetaEditor();};
el('metaEditorMore').onclick=()=>{metaEditorLimit+=50;renderMetaEditor();};
el('metaEditorAdd').onclick=()=>{if(!metaDraft||metaEditorBlocked())return;metaDraft.rows.push({species:'',fast:'',charged1:'',charged2:'',invalid:{}});metaDraft.dirty=true;el('metaEditorFilter').value='';metaEditorLimit=500;renderMetaEditor();};
el('metaEditorUndo').onclick=()=>{if(!metaDraft?.undo||metaEditorBlocked())return;metaDraft.rows.splice(metaDraft.undo.index,0,metaDraft.undo.row);metaDraft.undo=null;metaDraft.dirty=true;renderMetaEditor();};

function chosenMeta(){return metaState?.items.find(p=>p.id===selectedMetaId);}
function syncMetaControls(){
 el('metaDefault').disabled=!!chosenMeta()?.default||active||metaWorking||!!batchState||!!runRef;
 el('metaDownload').disabled=metaExportWorking||!chosenMeta();
 el('metaCompact').disabled=active||metaWorking||!!batchState||!!runRef||!['custom','legacy'].includes(chosenMeta()?.source);
 el('metaExport').disabled=metaExportWorking||!chosenMeta()||chosenMeta().available===false;
 const blocked=active||metaWorking||!!batchState||!!runRef||!!metaDraft;
 el('metaFavorite').disabled=blocked;el('metaDefault').disabled=el('metaDefault').disabled||!!metaDraft;
 for(const id of ['metaSaveMode','metaChoose','metaAll','metaFavorite','metaName','metaFile','metaText','metaTextPreview','metaApply'])el(id).disabled=blocked;
 for(const button of el('metaQuick').children)button.disabled=blocked;
 el('metaReload').disabled=active||metaWorking||!!metaDraft;
 el('metaApply').disabled=blocked||!metaPending||!metaState;
 el('run').disabled=active||metaWorking||!metaState||!!metaDraft;syncMetaEditor();
}
function renderMetaChoices(){
 if(!metaState)return;
 const current=chosenMeta();
 el('selectedMeta').textContent=current?current.name:'メタプリセットを選択してください';
 el('metaCurrentCount').textContent=current?current.rows+'構成':'';
 el('metaCurrentBadges').replaceChildren();
 if(current?.default)node('span','デフォルト',el('metaCurrentBadges'),'meta-tag');
 if(current?.favorite)node('span','★ お気に入り',el('metaCurrentBadges'),'meta-tag meta-star');
 el('metaStatus').textContent='公式プリセット取得日：'+metaState.retrieved+' / カスタム '+metaState.items.filter(p=>p.source==='custom').length+'件';
 el('metaFavorite').textContent=current?.favorite?'★ お気に入り':'☆ お気に入り';
 el('metaFavorite').setAttribute?.('aria-pressed',String(!!current?.favorite));
 el('metaFavorite').setAttribute?.('aria-label',current?.favorite?'お気に入りから外す':'お気に入りに追加');
 el('metaDefault').textContent=current?.default?'✓ デフォルト':'デフォルトにする';
 el('metaDefault').className='secondary'+(current?.default?' is-set':'');
 el('metaPresetNote').textContent=current?.note||'デフォルトは次回接続時の初期値です。今回だけ選び替えてもデフォルトは変わりません。';
 const ordered=metaState.items.filter(p=>p.available!==false).slice().sort((a,b)=>Number(b.default)-Number(a.default)||Number(b.favorite)-Number(a.favorite));
 el('metaQuick').replaceChildren();
 for(const p of ordered.slice(0,4)){
  const button=document.createElement('button');button.type='button';button.className='meta-chip';button.title=p.name;
  const mark=node('span',p.id===selectedMetaId?'✓':'○',button,'meta-chip-mark');mark.setAttribute?.('aria-hidden','true');
  node('span',p.name,button,'meta-chip-name');
  if(p.default)node('span','既定',button,'meta-tag');
  if(p.favorite)node('span','★',button,'meta-tag meta-star');
  button.setAttribute?.('aria-label',p.name+(p.default?'、デフォルト':'')+(p.favorite?'、お気に入り':''));
  button.setAttribute?.('aria-pressed',String(p.id===selectedMetaId));button.onclick=()=>chooseMeta(p.id);el('metaQuick').append(button);
 }
 el('metaAll').replaceChildren();
 for(const p of [...ordered,...metaState.items.filter(p=>p.available===false)]){
  const option=document.createElement('option');option.value=p.id;option.textContent=(p.default?'既定 · ':p.favorite?'★ ':'')+p.name+' / '+p.rows+'構成'+(p.available===false?'（利用不可：'+p.unavailable_reason+'）':'');option.disabled=p.available===false;el('metaAll').append(option);
 }
 el('metaAll').value=selectedMetaId||'';syncMetaControls();
}
function chooseMeta(id){
 if(active||metaWorking||batchState||runRef||metaDraft)return;
 const p=metaState?.items.find(x=>x.id===id);
 if(!p||p.available===false)return;
 selectedMetaId=id;clearMetaExport();renderMetaChoices();el('metaChooser').hidden=true;el('metaChoose').setAttribute?.('aria-expanded','false');
}
async function refreshMetaStatus(initial=false){
 try{
  const previous=chosenMeta();const next=await api('meta-presets');
  metaState=next;
  if(initial||!next.items.some(p=>p.id===selectedMetaId))selectedMetaId=next.default_id;
  if(batchState?.meta_preset_id)selectedMetaId=batchState.meta_preset_id;
  if(previous?.id!==selectedMetaId||previous?.sha256!==chosenMeta()?.sha256)clearMetaExport();
  renderMetaChoices();
 }catch(e){el('selectedMeta').textContent='メタ一覧を取得できません：'+e.message;throw e;}
}
el('metaChoose').onclick=()=>{if(active||metaWorking||batchState||runRef)return;el('metaChooser').hidden=!el('metaChooser').hidden;el('metaChoose').setAttribute?.('aria-expanded',String(!el('metaChooser').hidden));};
el('metaAll').onchange=()=>chooseMeta(el('metaAll').value);
el('metaReload').onclick=async()=>{try{await refreshMetaStatus();metaNotice('一覧を再取得しました。');}catch(e){metaNotice(e.message,true);}};
async function saveMetaPreference(action){
 if(active||metaWorking||batchState||runRef||!chosenMeta()||(action==='default'&&chosenMeta().default))return;
 metaWorking=true;syncMetaControls();
 try{metaState=await api('meta-preset-save',{action,id:selectedMetaId,favorite:!chosenMeta().favorite,revision:metaState.revision});renderMetaChoices();metaNotice('設定を保存しました。');}
 catch(e){metaNotice(e.message,true);}
 finally{metaWorking=false;syncMetaControls();}
}
el('metaFavorite').onclick=()=>saveMetaPreference('favorite');
el('metaDefault').onclick=()=>saveMetaPreference('default');
function clearMetaExport(){
 el('metaExport').textContent='PvPoke用にコピー';el('metaExportStatus').textContent='';
 el('metaExportParts').replaceChildren();el('metaExportParts').hidden=true;
 el('metaExportFallback').hidden=true;el('metaExportText').value='';
}
async function copyMetaPart(csv,button,label){
 el('metaExportFallback').hidden=true;el('metaExportText').value='';
 try{await navigator.clipboard.writeText(csv);button.textContent='コピーしました';el('metaExportStatus').textContent=label+'をコピーしました。PvPokeのImport/Exportに貼り付けてください。';}
 catch{button.textContent='手動コピー欄を表示中';el('metaExportFallback').hidden=false;const area=el('metaExportText');area.value=csv;area.focus?.();area.select?.();el('metaExportStatus').textContent='自動コピーできませんでした。下の欄を選択してコピーしてください。';}
}
el('metaExport').onclick=async()=>{
 if(metaExportWorking||!chosenMeta()||chosenMeta().available===false)return;
 const selected={...chosenMeta()};clearMetaExport();metaExportWorking=true;syncMetaControls();
 el('metaExportStatus').textContent='PvPoke用のデータを準備しています。';
 try{
  const data=await api('meta-preset-export',{id:selected.id,expected_sha256:selected.sha256});
  if(selectedMetaId!==selected.id||chosenMeta()?.sha256!==selected.sha256)return;
  if(data.id!==selected.id||data.sha256!==selected.sha256)throw Error('コピー内容が選択中のメタと一致しません。再取得してください。');
  if(!Array.isArray(data.parts)||!data.parts.length||data.parts.some(p=>typeof p.csv!=='string'||!p.csv.trim()))throw Error('コピー用データが不完全です。一覧を再取得してください。');
  if(data.parts.length===1){await copyMetaPart(data.parts[0].csv,el('metaExport'),data.name+'（'+data.rows+'件）');}
  else{
   el('metaExportStatus').textContent=data.name+'は'+data.rows+'件です。PvPokeの取り込み上限に合わせ、'+data.parts.length+'組に分けています。各組を別のグループとして確認してください。';
   el('metaExportParts').hidden=false;
   data.parts.forEach((part,i)=>{
    const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=(i+1)+' / '+data.parts.length+'（'+part.start+'〜'+part.end+'件）をコピー';
    button.onclick=()=>{if(chosenMeta()?.id!==selected.id||chosenMeta()?.sha256!==selected.sha256){el('metaExportStatus').textContent='メタが変わりました。もう一度PvPoke用にコピーしてください。';return;}return copyMetaPart(part.csv,button,data.name+' '+(i+1)+' / '+data.parts.length+'組目');};el('metaExportParts').append(button);
   });
  }
 }catch(e){if(selectedMetaId===selected.id)el('metaExportStatus').textContent='コピーできませんでした：'+e.message;}
 finally{metaExportWorking=false;syncMetaControls();}
};
el('metaDownload').onclick=async()=>{
 if(metaExportWorking||!chosenMeta())return;
 const selected={...chosenMeta()};metaExportWorking=true;syncMetaControls();
 try{
  const d=await api('meta-preset-export',{id:selected.id,expected_sha256:selected.sha256});
  if(chosenMeta()?.id!==selected.id||chosenMeta()?.sha256!==selected.sha256)return;
  if(d.id!==selected.id||d.sha256!==selected.sha256||typeof d.csv!=='string')throw Error('取得したメタが一致しません');
  const url=URL.createObjectURL(new Blob(['\ufeff'+d.csv+'\n'],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=selected.name.replace(/[\\/:*?"<>|]/g,'_')+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  el('metaExportStatus').textContent=d.rows+'構成をCSVでダウンロードしました。';
 }catch(e){el('metaExportStatus').textContent=e.message;}
 finally{metaExportWorking=false;syncMetaControls();}
};
el('metaCompact').onclick=async()=>{
 if(active||metaWorking||batchState||runRef||!chosenMeta())return;
 const selected={...chosenMeta()};metaWorking=true;syncMetaControls();
 try{
  metaState=await api('meta-preset-save',{action:'compact',id:selected.id,expected_previous_sha256:selected.sha256,revision:metaState.revision});
  clearMetaExport();resetMetaUpload();renderMetaChoices();metaNotice('保存されていた手動構成に戻し、必要な追加だけ再判定します。由来不明の構成は保持します。');
 }catch(e){metaNotice(e.message,true);}finally{metaWorking=false;syncMetaControls();}
};
el('metaSaveMode').onchange=()=>{resetMetaUploadPreviewOnly();el('metaApply').textContent={create:'別のプリセットとして保存',append:'選択中へ追加して上書き',replace:'選択中を全置換して保存'}[el('metaSaveMode').value];};
async function previewMetaInput(file=null){
 if(active||metaWorking||batchState||runRef){metaNotice('計算中はメタを更新できません。',true);return;}
 resetMetaUploadPreviewOnly();metaWorking=true;syncMetaControls();metaNotice('メタの内容と技を確認中です。');
 try{
  let content=file?await file.text():el('metaText').value;
  if(file&&el('metaFile').files?.[0]!==file)return;
  if(file){el('metaText').value=content;content=el('metaText').value;} // Textareas normalize CRLF/CR to LF.
  if(!content.trim())throw Error('メタの内容を貼り付けてください。');
  const mode=el('metaSaveMode').value||'create',target={...chosenMeta()};
  if(mode!=='create'&&!['custom','legacy'].includes(target.source))throw Error('公式プリセットは別名で保存してください。');
  let prepared=content;
  if(mode==='append'){
   const previous=await api('meta-preset-export',{id:target.id,expected_sha256:target.sha256});
   if(previous.id!==target.id||previous.sha256!==target.sha256)throw Error('追加先のメタが一致しません');
   prepared=(previous.manual_csv||previous.csv)+'\n'+content;
  }
  const preview=await api('meta-preview',{csv:prepared});
  if((el('metaSaveMode').value||'create')!==mode||chosenMeta()?.id!==target.id||chosenMeta()?.sha256!==target.sha256)return;
  if(el('metaText').value!==content||(file&&el('metaFile').files?.[0]!==file))return;
  metaPending={content,prepared,preview,mode,target};
  if(file&&!el('metaName').value.trim())el('metaName').value=file.name.replace(/\.(txt|csv)$/i,'').slice(0,60);
  const lines=['入力 '+(preview.input_rows??preview.rows)+'行 → 保存 '+preview.rows+'技構成',mode==='create'?'既存のメタは上書きしません。別名で保存します。':target.name+(mode==='append'?'の手動構成へ追加します。自動追加分は再判定します。':'を入力内容で全置換します。')];
  if(preview.duplicate_count){
   lines.push('重複 '+preview.duplicate_count+'行を統合しました。');
   if(preview.duplicate_lines?.length)lines.push('重複した行：'+preview.duplicate_lines.join(', ')+(preview.duplicate_count>preview.duplicate_lines.length?' ほか':''));
  }
  if(preview.custom_stats_count){
   lines.push('レベル・個体値付き '+preview.custom_stats_count+'行：種と技だけを保存します。入力のレベル・個体値は保存・計算に使いません。計算時は選択した対戦相手の個体値条件を使います。');
   if(preview.custom_stats_lines?.length)lines.push('対象行：'+preview.custom_stats_lines.join(', ')+(preview.custom_stats_count>preview.custom_stats_lines.length?' ほか':''));
  }
  el('metaPreview').textContent=lines.join('\n');el('metaPreview').hidden=false;
  metaNotice('内容・保存方法・対象メタを確認して保存してください。');
 }catch(e){metaPending=null;metaNotice(e.message+'（元のメタは変更されていません）',true);}
 finally{metaWorking=false;syncMetaControls();}
}
el('metaTextPreview').onclick=()=>previewMetaInput();
el('metaText').oninput=()=>{resetMetaUploadPreviewOnly();el('metaFile').value='';metaNotice('内容を変更しました。「貼り付けた内容を確認」を押してください。');};
el('metaFile').onchange=async()=>{
 if(active||metaWorking||batchState||runRef)return;
 const selected=el('metaFile').files?.[0];resetMetaUploadPreviewOnly();
 if(!selected){metaNotice('');return;}
 if(!/\.(txt|csv)$/i.test(selected.name)){metaNotice('TXTまたはCSVファイルを選んでください。',true);return;}
 if(!selected.size||selected.size>80000){metaNotice('ファイルは空でない80KB以下のものを選んでください。',true);return;}
 await previewMetaInput(selected);
};
function resetMetaUploadPreviewOnly(){metaPending=null;el('metaApply').disabled=true;el('metaPreview').hidden=true;el('metaPreview').textContent='';}
el('metaCancel').onclick=()=>{if(metaWorking)return;resetMetaUpload();metaNotice('メタの更新を取り消しました。現在のメタをそのまま使用します。');};
el('metaApply').onclick=async()=>{
 if(active||metaWorking||batchState||runRef||!metaPending||!metaState)return;
 if(el('metaText').value!==metaPending.content){resetMetaUploadPreviewOnly();metaNotice('内容が確認後に変わりました。もう一度確認してください。',true);return;}
 if(metaPending.mode==='create'&&!el('metaName').value.trim()){metaNotice('プリセット名を入力してください。',true);return;}
 const {content,prepared,preview,mode,target}=metaPending;
 if(mode!==(el('metaSaveMode').value||'create')||chosenMeta()?.id!==target.id||chosenMeta()?.sha256!==target.sha256){resetMetaUploadPreviewOnly();metaNotice('保存先が変わりました。もう一度確認してください。',true);return;}
 metaWorking=true;syncMetaControls();el('metaCancel').disabled=true;
 try{
  const saved=await api('meta-preset-save',{action:mode==='create'?'create':'update',id:target.id,expected_previous_sha256:target.sha256,name:el('metaName').value.trim(),csv:prepared,expected_sha256:preview.sha256,revision:metaState.revision});
  metaState=saved;selectedMetaId=saved.saved_id;clearMetaExport();resetMetaUpload();el('metaName').value='';renderMetaChoices();
  metaNotice('保存完了：'+preview.rows+'技構成'+(preview.duplicate_count?'（重複'+preview.duplicate_count+'行を統合）':'')+'。今回の計算に選択しました。普段使う場合はデフォルトに指定してください。');
 }catch(e){metaNotice(e.message+'（既存のメタは維持されます。一覧を再取得して確認してください）',true);}
 finally{metaWorking=false;el('metaCancel').disabled=false;syncMetaControls();}
};
let inputPokemonStatus=null,bulkStatusUndo=null;
function statusLabel(status){return {normal:'通常',shadow:'シャドウ',purified:'リトレーン'}[status];}
function variantSpecies(sid,status){
 const base=sid.replace(/_shadow$/, '');
 const target=status==='shadow'?base+'_shadow':base;
 if(status==='purified'&&!catalog[base+'_shadow'])throw Error((catalog[sid]?.name_ja||sid)+'：リトレーン可能なシャドウのデータがありません。全体の変更を中止しました。');
 if(!catalog[target])throw Error((catalog[sid]?.name_ja||sid)+'：'+statusLabel(status)+'のデータがありません。全体の変更を中止しました。');
 return target;
}
function statusJob(job,status){
 const target=variantSpecies(job.candidate.species,status),p=catalog[target];
 let candidate={...job.candidate,species:target};
 const valid=c=>p.fastMoves.includes(c.fast)&&p.chargedMoves.includes(c.charged1)&&p.chargedMoves.includes(c.charged2)&&c.charged1!==c.charged2;
 let warnings=[...(job.warnings||[])];
 if(!valid(candidate)){
  const fallback=p.default_moves||presets.find(x=>x.species===target);
  if(!fallback||!valid(fallback))throw Error((p.name_ja||target)+'：変更先の技構成を確認できません。全体の変更を中止しました。');
  candidate={...candidate,fast:fallback.fast,charged1:fallback.charged1,charged2:fallback.charged2};
  warnings.push('区分変更に伴い技を変更：'+[candidate.fast,candidate.charged1,candidate.charged2].join(' / '));
 }
 const records=(job.source_records||[]).map(r=>({...r,species:variantSpecies(r.species,status),search_string:statusSearch(r.search_string,status)}));
 return {...job,candidate,name:(p.name_ja||p.name||target)+'［'+statusLabel(status)+'］',pokemon_status:status,source_records:records,warnings};
}
function applyBulkStatus(status){
 if(active)return;
 try{
  if(batchState||runRef)throw Error('再開待ちの計算があります。再開して完了してから区分を変更してください。');
  const current=currentCandidate();
  const keep=importedSingle?.candidate.species===current.species&&importedSingle.ivs.trim()===el('ivs').value.trim();
  const jobs=importedJobs||[{...(keep?importedSingle:{}),candidate:current,ivs:el('ivs').value,candidate_count:el('ivs').value.split('\n').filter(x=>x.trim()).length,warnings:keep?importedSingle.warnings:[],source_records:keep?importedSingle.source_records:[]}];
  const next=jobs.map(job=>statusJob(job,status));
  bulkStatusUndo={jobs:JSON.parse(JSON.stringify(jobs)),status:inputPokemonStatus};
  setCandidate(next[0].candidate);el('ivs').value=next[0].ivs;setImportedJobs(next);inputPokemonStatus=status;
  el('bulkStatusUndo').hidden=false;el('results').hidden=true;
  el('bulkStatusNote').textContent=next.length+'種類を'+statusLabel(status)+'に変更しました。個体値・CPはそのままです。変更後に再計算してください。';
  message(el('bulkStatusNote').textContent+next.flatMap(j=>j.warnings).filter(x=>x.startsWith('区分変更')).map(x=>'\n'+x).join(''));
 }catch(e){message(e.message,true);}
}
el('bulkNormal').onclick=()=>applyBulkStatus('normal');
el('bulkShadow').onclick=()=>applyBulkStatus('shadow');
el('bulkPurified').onclick=()=>applyBulkStatus('purified');
el('bulkStatusUndo').onclick=()=>{
 if(active||!bulkStatusUndo)return;
 if(batchState||runRef){message('再開待ちの計算を完了してから元に戻してください。',true);return;}
 const old=bulkStatusUndo;
 setCandidate(old.jobs[0].candidate);el('ivs').value=old.jobs[0].ivs;setImportedJobs(old.jobs);inputPokemonStatus=old.status;
 bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;el('results').hidden=true;el('bulkStatusNote').textContent='直前の区分変更を元に戻しました。';message(el('bulkStatusNote').textContent);
};

function cacheBatch(){try{sessionStorage.setItem('pvpoke-app-batch',JSON.stringify(batchState));}catch{message('再開情報を保存できませんでした。計算が終わるまで画面を開いておいてください。',true);}}
function setImportedJobs(jobs){importedSingle=jobs?.length===1?jobs[0]:null;importedJobs=jobs&&jobs.length>1?jobs:null;el('queuePanel').hidden=!importedJobs;for(const id of ['preset','allSpecies','species','ivs'])el(id).disabled=!!importedJobs;el('inputMoves').hidden=!!importedJobs;refreshQueuePreview();}
async function stopActiveRun(){
 if(!runRef)return;
 if(!stopPromise){
  const ref=runRef;
  stopPromise=(async()=>{
   const response=await api('cancel',{run_ref:ref});
   if(response.state!=='cancelling')return response;
   // Wait for the process group to exit before allowing a new calculation.
   for(let attempt=0;attempt<5;attempt++){
    const status=await api('result',{run_ref:ref,wait_seconds:2});
    if(status.state!=='cancelling'&&status.state!=='running')return status;
   }
   throw Error('サーバーの計算停止を確認できません。後で状態を確認してください。');
  })();
 }
 try{return await stopPromise;}catch(e){stopError=e;throw e;}
}
async function honorStop(){
 if(!stopRequested)return;
 await stopActiveRun();
 throw Error('計算を中止しました');
}
async function finish(result){
 while(result.state==='running'){
  await honorStop();
  message('全対面を計算中です。'+(batchState?' '+(batchState.index+1)+' / '+batchState.jobs.length+'構成':''));
  result=await api('result',{run_ref:runRef,wait_seconds:2});
 }
 await honorStop();
 if(result.state!=='done'||!result.complete)throw Error(result.message||'計算が完了していません。');
 return result;
}
const MOVESET_STORAGE='pvpoke-app-movesets-v1';
let savedMovesets=readSavedMovesets();
function readSavedMovesets(){try{const data=JSON.parse(localStorage.getItem(MOVESET_STORAGE)||'{}');return data&&typeof data==='object'&&!Array.isArray(data)?data:{};}catch{return {};}}
function movesetKey(c){return [c.species,c.fast,...[c.charged1,c.charged2].sort()].join('|');}
function validMoveset(c){const p=catalog[c?.species];return !!p&&p.fastMoves.includes(c.fast)&&c.charged1!==c.charged2&&[c.charged1,c.charged2].every(x=>p.chargedMoves.includes(x));}
function registeredMovesets(sid){return Array.isArray(savedMovesets[sid])?savedMovesets[sid].filter(c=>c&&c.species===sid):[];}
function enabledMovesets(sid){return registeredMovesets(sid).filter(c=>c.enabled!==false);}
function saveSpeciesMovesets(sid,rows,status){
 const next={...savedMovesets,[sid]:rows};
 try{localStorage.setItem(MOVESET_STORAGE,JSON.stringify(next));}
 catch{status.textContent='このブラウザへ保存できませんでした。設定は変更されていません。';return false;}
 savedMovesets=next;refreshQueuePreview();return true;
}
function registerMoveset(candidate,status){
 if(!validMoveset(candidate)){status.textContent='通常技と、異なるゲージ技2個を選んでください。';return false;}
 const sid=candidate.species,rows=registeredMovesets(sid),index=rows.findIndex(c=>movesetKey(c)===movesetKey(candidate));
 if(index<0)rows.push({...candidate,enabled:true});
 else rows[index]={...rows[index],enabled:true};
 return saveSpeciesMovesets(sid,rows,status);
}
function renderSpeciesMovesets(sid,panel,notice=''){
 panel.replaceChildren();
 const status=node('p',notice,panel,'note');status.setAttribute?.('role','status');
 const rows=registeredMovesets(sid);
 node('p',rows.length?'チェックした技構成を次の厳選に使います。':'登録した技構成はありません。',panel,'note');
 for(const candidate of rows){
  const row=node('div','',panel,'species-moveset-row'),label=node('label','',row,'checkline');
  const check=document.createElement('input');check.type='checkbox';check.checked=candidate.enabled!==false;check.disabled=active;label.append(check);
  node('span',moveLabel(candidate),label);
  check.onchange=()=>{
   if(active){check.checked=candidate.enabled!==false;return;}
   const current=registeredMovesets(sid),enabled=check.checked;
   const updated=current.map(c=>movesetKey(c)===movesetKey(candidate)?{...c,enabled}:c);
   if(saveSpeciesMovesets(sid,updated,status))status.textContent=enabled?'次の計算で使う構成にしました。':'登録構成から計算対象を外しました。';
   else check.checked=current.find(c=>movesetKey(c)===movesetKey(candidate))?.enabled!==false;
  };
  const remove=node('button','削除',row,'secondary');remove.type='button';remove.disabled=active;
  remove.setAttribute?.('aria-label',moveLabel(candidate)+'を削除');
  remove.onclick=()=>{
   if(!active&&saveSpeciesMovesets(sid,registeredMovesets(sid).filter(c=>movesetKey(c)!==movesetKey(candidate)),status)){
    renderSpeciesMovesets(sid,panel,'技構成を削除しました。').focus?.();
   }
  };
  if(!validMoveset(candidate))node('p','現在の技一覧にない組み合わせです。削除して登録し直してください。',panel,'note');
 }
 const add=node('button','＋ 技構成を追加',panel,'secondary species-moveset-add');add.type='button';add.disabled=active;
 add.onclick=()=>{
  if(active)return;
  add.hidden=true;
  const form=node('div','',panel,'species-moveset-form'),fields=node('div','',form,'row');
  const selects=['通常技','ゲージ技1','ゲージ技2'].map((name,index)=>{
   const field=node('div','',fields),label=node('label',name,field),select=node('select','',field);
   select.id='species-move-'+sid+'-'+index;label.htmlFor=select.id;return select;
  });
  fillMoveFields(sid,catalog[sid].default_moves||{},selects,id=>moveCatalog[id]?.name||id);
  const actions=node('div','',form,'form-buttons');
  const save=node('button','登録',actions),cancel=node('button','キャンセル',actions,'secondary');
  save.type=cancel.type='button';
  save.onclick=()=>{
   const [fast,charged1,charged2]=selects.map(select=>select.value);
   if(!active&&registerMoveset({species:sid,fast,charged1,charged2},status)){
    renderSpeciesMovesets(sid,panel,'技構成を登録しました。次の計算から適用します。').focus?.();
   }
  };
  cancel.onclick=()=>{form.remove();add.hidden=false;add.focus?.();};
  selects[0].focus?.();
 };
 return add;
}
el('autoMoves').onchange=refreshQueuePreview;
function allMoveProfiles(sid){
 const p=catalog[sid],fast=[...new Set(p?.fastMoves||[])].sort(),charged=[...new Set(p?.chargedMoves||[])].sort(),profiles=[];
 for(const f of fast)for(let i=0;i<charged.length;i++)for(let j=i+1;j<charged.length;j++)profiles.push({species:sid,fast:f,charged1:charged[i],charged2:charged[j]});return profiles;
}
function moveEffect(m){return JSON.stringify([m.buffs||[],m.buffTarget||'',m.buffApplyChance??0]);}
function hasMoveStats(id,fast=false){const m=moveCatalog[id];return !!m&&typeof m.type==='string'&&Number.isFinite(m.power)&&m.power>=0&&(fast?Number.isFinite(m.energyGain)&&m.energyGain>=0&&Number.isFinite(m.cooldown)&&m.cooldown>0:Number.isFinite(m.energy)&&m.energy>0);}
// A cheap heuristic, not simulated wins. Preserve effects and type coverage;
// timing/energy differences are useful even when raw DPE is lower.
function shortlistMovesets(sid,profiles){
 const p=catalog[sid],ids=[...new Set(profiles.flatMap(c=>[c.fast,c.charged1,c.charged2]))];
 if(ids.some(id=>!hasMoveStats(id,p.fastMoves.includes(id))))return {profiles:[],incomplete:true};
 const stab=m=>(p.types||[]).includes(m.type)?1.2:1,turns=m=>Math.max(1,m.cooldown/500);
 const fastScore=id=>{const m=moveCatalog[id];return (m.power*stab(m)+1.4*m.energyGain)/turns(m);};
 const chargeScore=id=>{const m=moveCatalog[id];const effects=m.buffs||[],chance=Number(m.buffApplyChance)||0;const direction=m.buffTarget==='opponent'?-1:1;return Math.max(.01,m.power*stab(m)/m.energy+20/m.energy+effects.reduce((s,x)=>s+Number(x),0)*direction*chance*.35);};
 const fastMax=Math.max(...p.fastMoves.map(fastScore),.01),chargeMax=Math.max(...p.chargedMoves.map(chargeScore),.01);
 const dominated=(id,fast)=>{const a=moveCatalog[id];return (fast?p.fastMoves:p.chargedMoves).some(other=>{if(id===other)return false;const b=moveCatalog[other];if(a.type!==b.type||moveEffect(a)!==moveEffect(b))return false;if(fast){const ad=a.power/turns(a),ae=a.energyGain/turns(a),bd=b.power/turns(b),be=b.energyGain/turns(b);return a.cooldown===b.cooldown&&bd>=ad&&be>=ae&&(bd>ad||be>ae);}return b.energy<=a.energy&&b.power>=a.power&&(b.energy<a.energy||b.power>a.power);});};
 const role=c=>{const f=moveCatalog[c.fast];return new Set(['F:'+f.type+':'+Math.round(f.energyGain/turns(f))+':'+Math.round(f.power/turns(f))+':'+f.cooldown+':'+moveEffect(f),...[c.charged1,c.charged2].map(id=>{const m=moveCatalog[id];return 'C:'+m.type+':'+Math.floor(m.energy/15)+':'+moveEffect(m);})]);};
 let ranked=profiles.filter(c=>!dominated(c.fast,true)&&![c.charged1,c.charged2].some(id=>dominated(id,false))).map(c=>{
  const charges=[chargeScore(c.charged1),chargeScore(c.charged2)].sort((a,b)=>b-a);
  return {candidate:c,roles:role(c),score:fastScore(c.fast)/fastMax+1.2*charges[0]/chargeMax+.8*charges[1]/chargeMax+(moveCatalog[c.charged1].type!==moveCatalog[c.charged2].type?.15:0)};
 }).sort((a,b)=>b.score-a.score||movesetKey(a.candidate).localeCompare(movesetKey(b.candidate)));
 const best=ranked[0]?.score||0;ranked=ranked.filter(x=>x.score>=best*.85);const selected=[];
 while(ranked.length&&selected.length<6){
  const similarity=(a,b)=>{const intersection=[...a].filter(x=>b.has(x)).length;return intersection/(a.size+b.size-intersection);};
  ranked=ranked.filter(x=>!selected.some(y=>similarity(x.roles,y.roles)===1));if(!ranked.length)break;
  ranked.sort((a,b)=>{const value=x=>x.score/best+.35*(selected.length?1-Math.max(...selected.map(y=>similarity(x.roles,y.roles))):0);return value(b)-value(a)||movesetKey(a.candidate).localeCompare(movesetKey(b.candidate));});
  selected.push(ranked.shift());
 }
 return {profiles:selected.map(x=>x.candidate),incomplete:false};
}
// Freeze the selected profiles, IVs and source CPs before one sequential worker.
function planMovesets(jobs,mode='smart'){
 if(!['smart','all','manual'].includes(mode))throw Error('技の比較範囲が不正です');
 const groups=new Map(),planned=[];
 for(const job of jobs){const key=JSON.stringify([job.candidate.species,job.ivs,job.source_sections||[],job.source_records||[],job.pokemon_status||null]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(job);}
 for(const members of groups.values()){
  const job=members[0],sid=job.candidate.species,group=planned.length,pool=allMoveProfiles(sid),registered=enabledMovesets(sid);
  if(registered.some(c=>!validMoveset(c)))throw Error(job.name+'：現在の技一覧にない登録構成があります。削除して登録し直してください。');
  const explicit=members.map(j=>j.candidate);if((mode!=='manual'||!registered.length)&&explicit.some(c=>!validMoveset(c)))throw Error(job.name+'の技を確認してください。');
  let picked,incomplete=false;
  if(mode==='all')picked=pool;
  else if(mode==='manual')picked=registered.length?registered:explicit;
  else{const shortlist=shortlistMovesets(sid,pool);picked=shortlist.profiles;incomplete=shortlist.incomplete;const standard=catalog[sid]?.default_moves;if(standard&&validMoveset({species:sid,...standard}))picked=[{species:sid,...standard},...picked].slice(0,6);}
  const required=mode==='manual'?[]:[...explicit,...registered],unique=new Map();
  for(const c of [...required,...picked]){const candidate={species:sid,fast:c.fast,charged1:c.charged1,charged2:c.charged2};if(!unique.has(movesetKey(candidate)))unique.set(movesetKey(candidate),candidate);}
  if(!unique.size)throw Error(job.name+'の技一覧が不足しています。技の設定で直接指定してください。');
  const planning={mode,total:pool.length,selected:unique.size,omitted:Math.max(0,pool.length-unique.size),incomplete};
  for(const candidate of unique.values())planned.push({...job,candidate,moveset_group:group,moveset_plan:planning});
 }
 return planned;
}
function moveLabel(c){return [c.fast,c.charged1,c.charged2].map(id=>moveCatalog[id]?.name||id).join(' / ');}
const moveAliasCache=new Map();
function moveAliases(c){
 const p=catalog[c.species]||{},ids=[...new Set([...(p.fastMoves||[]),...(p.chargedMoves||[]),c.fast,c.charged1,c.charged2])].sort();
 const cacheKey=ids.join('|');if(moveAliasCache.has(cacheKey))return moveAliasCache.get(cacheKey);
 const preferred={SCRATCH:'Sc',THUNDER_PUNCH:'TP',ICE_PUNCH:'IP',SWIFT:'Sw',HIGH_HORSEPOWER:'HH'};
 const codes={},used=new Set();
 // Reserve recognizable codes before assigning alternatives, case-insensitively.
 for(const id of ids.filter(x=>preferred[x])){codes[id]=preferred[id];used.add(preferred[id].toLowerCase());}
 for(const id of ids.filter(x=>!preferred[x])){
  const words=id.split('_'),suggested=words.length>1?words[0][0]+words[1][0]:id.slice(0,2);
  let code=/^[A-Za-z0-9]{2}$/.test(suggested)&&!used.has(suggested.toLowerCase())?suggested:null;
  for(let n=0;!code&&n<1296;n++){
   const fallback=n.toString(36).padStart(2,'0').toUpperCase();
   if(!used.has(fallback.toLowerCase()))code=fallback;
  }
  if(!code)throw Error('技の略号を作成できません');codes[id]=code;used.add(code.toLowerCase());
 }
 moveAliasCache.set(cacheKey,codes);return codes;
}
function movesetNickname(members){
 // One physical IV shared by evolutions keeps the first target's adopted build.
 const primary=members.find(m=>m.row.chosen_moves),c=primary.row.chosen_moves,aliases=moveAliases(c);
 const ids=[c.fast,c.charged1,c.charged2],suffix=ids.map(id=>aliases[id]).join('');
 const grade=String(primary.row.grade||'').startsWith('S')?'S':'A';
 for(const width of [4,3,2])for(const code of codeChoices(primary.sid,width)){
  const text=grade+code+suffix;
  if(validNickname(text))return {text,description:grade+'＝候補評価 / '+code+'＝'+(catalog[primary.sid]?.name_ja||primary.sid)+' / '+ids.map(id=>aliases[id]+'＝'+(moveCatalog[id]?.name||id)).join(' / ')+' / 個体別平均Rating '+primary.row.moveset_mean.toFixed(1)+(members.length>1?' / 共通個体：'+members.map(m=>catalog[m.sid]?.name_ja||m.sid).join('、')+'（技略号は最初の進化先）':'')};
 }
 return null;
}
function combineMovesets(results,threshold){
 const summaries=results.map(r=>r.selection?.moveset_summary),first=summaries[0];
 if(results.some(r=>r.meta_sha256!==results[0].meta_sha256||r.calculation_version!==results[0].calculation_version||r.batch_mode!==results[0].batch_mode||r.candidate.species!==results[0].candidate.species)||!first||summaries.some(s=>!s||s.version!==1||s.axis_sha256!==first.axis_sha256||s.available_wins.length!==first.available_wins.length||!Number.isFinite(s.mean_rating)))throw Error('技の比較条件が一致しません。同じメタ・条件で再計算してください。');
 const counts=Array.from(first.available_wins,(_,i)=>summaries.reduce((n,s)=>n+Number(s.available_wins[i]==='1'),0));
 const best=Math.max(...summaries.map(s=>s.mean_rating));
 const profiles=results.map((r,i)=>({candidate:r.candidate,mean_rating:summaries[i].mean_rating,
  unique_win_count:counts.filter((n,k)=>n===1&&summaries[i].available_wins[k]==='1').length,
  retained:summaries[i].mean_rating>=threshold||summaries[i].mean_rating===best||counts.some((n,k)=>n===1&&summaries[i].available_wins[k]==='1')}));
 const chosen=new Map();
 results.forEach((result,i)=>{
  if(!profiles[i].retained)return;
  for(const row of result.selection.recommendations)for(const item of [row,...(row.equivalent_candidates||[])]){
   const mean=summaries[i].iv_mean_ratings[item.ivs];
   if(!Number.isFinite(mean))throw Error('個体別Ratingが不足しています。再計算してください。');
   const previous=chosen.get(item.ivs);
   if(previous&&previous.moveset_mean>=mean)continue;
   // Equivalence is specific to one profile. Never reuse it across configurations.
   const sizeRow=result.selection.size_comparison?.rows?.[item.ivs];
   chosen.set(item.ivs,{...row,ivs:item.ivs,...(sizeRow?{size_row:sizeRow}:{}),search_string:item.search_string,equivalent_candidates:[],chosen_moves:result.candidate,moveset_mean:mean,comparison_peer:null,comparison_differences:[],comparison_difference_count:0});
  }
 });
 const rows=[...chosen.values()].sort((a,b)=>Number(String(b.grade).startsWith('S'))-Number(String(a.grade).startsWith('S'))||b.moveset_mean-a.moveset_mean||a.ivs.localeCompare(b.ivs));
 rows.forEach((r,i)=>r.rank=i+1);
 const bestIndex=summaries.findIndex(s=>s.mean_rating===best),base=results[bestIndex];
 const candidateIvs=base.selection.candidate_ivs||Object.keys(first.iv_mean_ratings);
 const additional=candidateIvs.filter(iv=>!chosen.has(iv)).map(ivs=>({ivs,reason:'採用した技構成では保存候補に選ばれませんでした。',equivalent_candidates:[]}));
 return {...base,moveset_comparison:{threshold,profiles},selection:{...base.selection,
  recommendations:rows,review_candidates:[],additional_candidates:additional,covered_candidates:[],dominated_by:{},
  total_ratings_checked:summaries.reduce((n,s)=>n+s.rating_count,0)}};
}
function renderMovesetComparison(result,parent){
 const info=result.moveset_comparison,kept=info.profiles.filter(p=>p.retained);
 const plan=result.moveset_plan;if(plan)node('p',(plan.mode==='smart'?'有力構成に絞って比較':plan.mode==='manual'?'登録・指定構成を比較':'全組み合わせを比較')+'：'+plan.selected+' / '+plan.total+'構成'+(plan.omitted?'。選外の勝敗は未計算です。':'')+(plan.incomplete?' 技性能データが不足し、自動候補の追加を省略しました。':''),parent,'note');
 node('p',info.profiles.length+'構成を実測 / 採用 '+kept.length+'構成 / 平均Ratingの目安 '+info.threshold+'以上',parent,'note');
 const d=node('details','',parent);node('summary','技構成の比較を見る',d);
 for(const p of info.profiles)node('p',(p.retained?'採用｜':'参考｜')+moveLabel(p.candidate)+'｜平均 '+p.mean_rating.toFixed(1)+(p.unique_win_count?'｜この構成だけで勝てる対面条件 '+p.unique_win_count:'') ,d,'note');
}
const GOURGEIST_LIMIT=8;
function isGourgeist(sid){return /^gourgeist_(small|average|large|super)$/.test(sid);}
function gourgeistKey(result,ivs){return JSON.stringify([result.candidate.species,result.pokemon_status||null,ivs]);}
function curateGourgeist(group){
 const first=group[0],axis=first?.selection.size_comparison;
 const focus=axis?.focus||'';
 const comparable=Boolean(axis?.axis&&focus.length&&focus.length%6===0&&group.every(r=>
  r.selection.size_comparison?.axis===axis.axis&&r.selection.size_comparison.focus===focus&&
  r.meta_sha256===first.meta_sha256&&r.calculation_version===first.calculation_version));
 const options=[];
 for(const result of group){
  const selection=result.selection;
  const local=new Map(selection.recommendations.map(row=>[row.ivs,row]));
  // Older resumable batches have comparison rows only for local recommendations.
  const metrics=selection.size_comparison?.rows||{};
  const ivs=comparable?Object.keys(metrics):[...local.keys()];
  for(const iv of ivs){
   const prior=local.get(iv),data=metrics[iv],search=data?.search_string||prior?.search_string;
   if(!search||(comparable&&data?.outcomes?.length!==focus.length))continue;
   const mean=data?.mean??prior?.moveset_mean??selection.moveset_summary?.iv_mean_ratings?.[iv]??0;
   const wins=comparable?[...data.outcomes].reduce((n,v,i)=>n+(v==='2'?(i<focus.length/3?2:1):0),0):
    (prior?.win_conditions??0)/(selection.mode_count||1);
   options.push({result,iv,prior,data,search,mean,wins,key:gourgeistKey(result,iv)});
  }
 }
 const covered=new Uint8Array(comparable?focus.length:0);
 const keys=new Set(),selected=[];
 function gain(item){
  let priority=0,wins=0,draws=0;
  for(let i=0;i<covered.length;i++){
   const value=Number(item.data.outcomes[i]);
   if(value<=covered[i])continue;
   if(focus[i]==='1')priority+=value-covered[i];
   if(value===2)wins++;else draws++;
  }
  return {priority,wins,draws};
 }
 while(selected.length<(comparable?GOURGEIST_LIMIT:4)){
  let best=null,bestGain=null,bestScore=null;
  for(const item of options){
   if(keys.has(item.key))continue;
   const added=selected.length&&comparable?gain(item):{priority:0,wins:0,draws:0};
   if(selected.length&&comparable&&!added.priority&&!added.wins&&(!added.draws||selected.length>=4))continue;
   const score=[added.priority,added.wins,added.draws,item.wins,item.mean];
   if(bestScore){
    const different=score.findIndex((value,i)=>value!==bestScore[i]);
    if(different===-1||score[different]<bestScore[different])continue;
   }
   best=item;bestGain=added;bestScore=score;
  }
  if(!best)break;
  keys.add(best.key);
  const rank=selected.length+1;
  const opponents=axis?.opponents||[];
  const improvements=[];
  if(rank>1&&comparable&&opponents.length&&opponents.length*6===covered.length){
   for(let i=0;i<covered.length;i++)if(Number(best.data.outcomes[i])>covered[i])improvements.push(i);
  }
  const gains=improvements.sort((a,b)=>Number(focus[b])-Number(focus[a])||
   Number(best.data.outcomes[b])-Number(best.data.outcomes[a])).slice(0,3).map(i=>({
    opponent:opponents[i%opponents.length],mode:'default',
    shield:['s0','s1','s2','i0y1','i0y2','i1y2'][Math.floor(i/opponents.length)],
    outcome:best.data.outcomes[i]==='2'?'勝ち':'引き分け',
   }));
  const evidence=best.prior?.evidence||[];
  const row={...best.prior,ivs:best.iv,search_string:best.search,rank,grade:rank===1?'Sランク':'Aランク',
   role:rank===1?'全サイズの総合本命':comparable?'追加の勝ち '+bestGain.wins+'条件・引き分け '+bestGain.draws+'条件':'全サイズから選んだ保存候補',
   equivalent_candidates:[],chosen_moves:best.result.candidate,moveset_mean:best.mean,gourgeist_gains:gains,
   comparison_peer:null,comparison_differences:[],comparison_difference_count:0,evidence,
   evidence_count:evidence.length,tradeoff:null};
  selected.push({result:best.result,row});
  if(comparable)for(let i=0;i<covered.length;i++)covered[i]=Math.max(covered[i],Number(best.data.outcomes[i]));
 }
 return {selected,keys,comparable};
}
function renderGourgeist(group,pending,root){
 const panel=node('section','',root);
 node('h2','パンプジン｜全サイズまとめ',panel);
 if(pending){
  node('p','全サイズ・技構成の計算を待っています。完了後にまとめて保存候補を表示します。',panel,'note');
  return;
 }
 const {selected,keys,comparable}=curateGourgeist(group);
 node('p',selected.length+'体を保存候補に選びました。計算したサイズ・技構成を共通条件で比較し、最大'+GOURGEIST_LIMIT+'体に絞ります。',panel,'note');
 if(!comparable||group.some(r=>!r.selection.size_comparison?.opponents))
  node('p','比較用の候補データが揃っていない保存済み結果です。全候補を比較するには再計算してください。',panel,'note');
 const keep=selected.map(({result,row})=>({...result,gourgeist_group:true,selection:{...result.selection,recommendations:[row]}}));
 displayedResults.push(...keep);
 if(keep.length){
  renderCopyActions(panel,keep);
  if(keep.some(r=>!individualSearches(r,r.selection.recommendations[0])[0]?.cp))
   node('p','読み取り時のCPがない検索式は、GO上で複数の個体に一致することがあります。',panel,'note');
 }else node('p','保存候補に該当する個体はありません。',panel,'note');
 for(const result of keep)renderRecommendation(result.selection.recommendations[0],panel,result);
 const remaining=new Map();
 for(const result of group){
  const s=result.selection,sid=result.candidate.species;
  for(const iv of s.candidate_ivs||[...s.recommendations,...(s.additional_candidates||[]),...(s.review_candidates||[])].flatMap(row=>[row.ivs,...(row.equivalent_candidates||[]).map(e=>e.ivs)])){
   const key=gourgeistKey(result,iv);
   if(!keys.has(key))remaining.set(key,{iv,label:result.display_name||catalog[sid]?.name_ja||sid});
  }
 }
 if(remaining.size){
  const details=node('details','',panel);
  node('summary','参考：保存候補外の個体（'+remaining.size+'）',details);
  const bySize=new Map();
  for(const {iv,label} of remaining.values()){
   if(!bySize.has(label))bySize.set(label,[]);
   bySize.get(label).push(iv);
  }
  for(const [label,ivs] of bySize)node('p',label+'：'+ivs.join('、'),details,'note');
 }
}
function renderSelectionResults(results,pending=false){
 if(!results.length&&!pending)return;
 resetResults();const root=el('results'),group=results.filter(r=>isGourgeist(r.candidate?.species)&&r.selection);
 for(const result of results)if(!group.includes(result))render(result,true);
 if(group.length||pending)renderGourgeist(group,pending,root);
 root.hidden=false;updateAllCopy();refreshNicknames();
}
function renderBatchResults(){
 const state=batchState;
 let completed=state.results;
 if(state.compare_moves??state.auto_moves){
  completed=[];
  for(const group of [...new Set(state.jobs.map(j=>j.moveset_group))]){
   const jobs=state.jobs.filter(j=>j.moveset_group===group),results=state.results.filter(r=>r.moveset_group===group);
   if(jobs.some(j=>isGourgeist(j.candidate.species)))completed.push(...results);
   else if(results.length&&results.length===jobs.length)completed.push(combineMovesets(results,state.move_threshold));
  }
 }
 const pending=state.jobs.slice(state.index).some(job=>isGourgeist(job.candidate.species));
 renderSelectionResults(completed,pending);
}

async function executeBatch(){
 for(;batchState.index<batchState.jobs.length;){
  await honorStop();
  const job=batchState.jobs[batchState.index];
  message(job.name+'｜'+moveLabel(job.candidate)+'（'+(batchState.index+1)+' / '+batchState.jobs.length+'構成）');
  let result;
  if(batchState.run_ref){runRef=batchState.run_ref;result=await api('result',{run_ref:runRef,wait_seconds:2});}
  else{
   const data={candidate:job.candidate,ivs:job.ivs,batch_mode:job.batch_mode||batchState.batch_mode||'simple',focus_opponents:batchState.focus,report_format:batchState.report_format,selection_policy:batchState.policy,force_recalculate:batchState.force_recalculate===true,wait_seconds:0};
   if(batchState.meta_sha256)data.expected_meta_sha256=batchState.meta_sha256;
   if(batchState.meta_preset_id)data.meta_preset_id=batchState.meta_preset_id;
   batchState.start_request_id=batchState.start_request_id||calculationRequestId();cacheBatch();
   data.request_id=batchState.start_request_id;
   result=await api('run',data);runRef=result.run_ref;batchState.run_ref=runRef;
   sessionStorage.setItem('pvpoke-app-run',runRef);cacheBatch();
  }
  await honorStop();
  result=await finish(result);
  if(batchState.compare_moves??batchState.auto_moves){
   if(!/^[a-f0-9]{64}$/.test(result.calculation_version||''))throw Error('計算データの更新版を識別できません。単一構成で計算するか、計算環境の設定を確認してください');
   if(batchState.calculation_version&&batchState.calculation_version!==result.calculation_version)throw Error('計算中にゲームデータまたは計算処理が更新されました。古い結果を混ぜず、新しく計算し直してください');
   batchState.calculation_version=result.calculation_version;
  }
  result.display_name=job.name;
  result.source_sections=job.source_sections||[];result.source_records=job.source_records||[];result.pokemon_status=job.pokemon_status;
  result.moveset_group=job.moveset_group;result.moveset_plan=job.moveset_plan;
  batchState.meta_sha256=result.meta_sha256;await honorStop();batchState.results.push(result);batchState.index++;
  batchState.run_ref=null;delete batchState.start_request_id;runRef=null;sessionStorage.removeItem('pvpoke-app-run');cacheBatch();
  renderBatchResults();
 }
 message(batchState.jobs.length+'構成すべての計算と推薦が完了しました。');
 el('results').scrollIntoView?.({block:'start'});el('results').focus?.({preventScroll:true});
 if(readerAutomation)returnReaderAutomation(batchState.results);
 sessionStorage.removeItem('pvpoke-app-batch');batchState=null;runRef=null;el('resume').hidden=true;
}
async function connect(auto=false){credential=auto?'':el('credential').value.trim();if(!auto&&!credential){message('接続キーを入力してください。',true);return;}el('connect').disabled=true;try{if(!auto&&el('remember').checked){try{await api('session');credential='';}catch(e){if(e.status!==401)throw e;el('remember').checked=false;}}const cat=await api('catalog');if(!cat.ready)throw Error(cat.error||'ゲームデータを読込中です。少し待って接続してください。');catalog=cat.species;moveCatalog=cat.moves||{};prepareLabels();presets=cat.app_presets||cat.presets;el('credential').value='';el('login').hidden=true;el('workspace').hidden=false;el('selectionSettingsOpen').hidden=false;updateLowScorePanelVisibility();const opts=el('preset');opts.replaceChildren();const custom=document.createElement('option');custom.value='';custom.textContent='直接指定・貼り付け';opts.append(custom);for(const p of presets){const o=document.createElement('option');o.value=presetKey(p);o.textContent=p.name+' / '+p.fast+' / '+p.charged1+' / '+p.charged2;opts.append(o);}el('presetHint').textContent='登録済みの技構成 '+presets.length+'件。プリセット外も、全ポケモンの選択・CSV貼り付けから計算できます。';const speciesOptions=Object.keys(catalog).sort((a,b)=>(catalog[a].name_ja||catalog[a].name||a).localeCompare(catalog[b].name_ja||catalog[b].name||b,'ja'));el('allSpecies').replaceChildren();el('speciesList').replaceChildren();for(const sid of speciesOptions){const label=(catalog[sid].name_ja||catalog[sid].name||sid)+' ('+sid+')';const o=document.createElement('option');o.value=sid;o.textContent=label;el('allSpecies').append(o);const hint=document.createElement('option');hint.value=sid;hint.label=label;el('speciesList').append(hint);}const preferred=presets.find(p=>p.species==='quagsire'&&p.charged2==='STONE_EDGE')||presets[0];if(preferred)setCandidate(preferred);runRef=sessionStorage.getItem('pvpoke-app-run');try{batchState=JSON.parse(sessionStorage.getItem('pvpoke-app-batch')||'null');}catch{batchState=null;}if(batchState?.jobs){const jobs=batchState.jobs.every(j=>j.moveset_group!==undefined)?batchState.jobs.filter((j,i,a)=>a.findIndex(x=>x.moveset_group===j.moveset_group)===i):batchState.jobs;setImportedJobs(jobs);if(batchState.auto_moves!==undefined)el('autoMoves').checked=batchState.auto_moves;if(batchState.move_threshold!==undefined)el('moveThreshold').value=batchState.move_threshold_setting??batchState.move_threshold;if(batchState.move_strategy)el('moveStrategy').value=batchState.move_strategy;}if(batchState?.results?.length)renderBatchResults();el('resume').hidden=!(runRef||batchState);message('接続できました。');if(new URLSearchParams(location.search||'').get('tool')==='low-score'){el('lowScorePanel').scrollIntoView?.();await loadLowScores();}await refreshMetaStatus(true);if(readerAutomation&&batchState&&batchState.reader_automation_digest!==readerAutomation.digest)throw Error('別の計算が残っています。既存の計算を完了または中止してください');await autoImportReader();if(readerAutomation&&batchState&&!active)Promise.resolve().then(()=>el('resume').onclick());}catch(e){credential='';if(!auto||e.status!==401)message(e.message,true);}finally{el('connect').disabled=false;}}
el('connect').onclick=()=>connect(false);
el('preset').onchange=()=>{bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;setPreset();};el('species').onchange=()=>{inputPokemonStatus=null;bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;resolveTypedSpecies();el('allSpecies').value=el('species').value;el('preset').value='';moves();};
el('allSpecies').onchange=()=>{inputPokemonStatus=null;bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;el('species').value=el('allSpecies').value;el('preset').value='';moves();};
el('singleForm').onclick=()=>{if(!active){inputPokemonStatus=null;bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;setImportedJobs(null);message('単一種のフォームに切り替えました。貼り付けた元の入力は上の欄に残っています。');}};
async function importInput(){
 if(active)return false;
 setBusy(true);
 try{
  const parsed=await api('import',{text:el('importText').value,current:currentCandidate()});
  const jobs=parsed.jobs||[parsed];
  if(!jobs.length)throw Error('取り込む個体値がありません');
  setCandidate(jobs[0].candidate);el('ivs').value=jobs[0].ivs;
  if(parsed.batch_mode)el('batchMode').value=parsed.batch_mode;
  setImportedJobs(jobs);bulkStatusUndo=null;el('bulkStatusUndo').hidden=true;
  message(jobs.map(j=>j.name+'：'+j.candidate_count+'個体'+(j.warnings?.length?'\n'+j.warnings.join('\n'):'')).join('\n')+'\n取り込みました。メタを確認して計算してください。');
  el('comparisonSettings').scrollIntoView?.({block:'start'});el('comparisonSettings').focus?.({preventScroll:true});
  return true;
 }catch(e){message(e.message,true);return false;}finally{setBusy(false);}
}
async function autoImportReader(){
 if(!readerImportPending||readerImportInFlight||active||el('workspace').hidden)return;
 readerImportPending=false;readerImportInFlight=true;
 try{el('importText').value=readerInputText;const imported=await importInput();if(imported&&readerAutomation&&!batchState)Promise.resolve().then(startSelection);}finally{readerImportInFlight=false;if(readerImportPending)Promise.resolve().then(autoImportReader);}
}
el('importInput').onclick=importInput;
el('evaluation').onchange=()=>{el('evaluation').value='app';el('run').textContent='計算して結果を表示';};
function handleCalculationError(e){
 if(stopRequested&&!stopError){
  batchState=null;runRef=null;
  sessionStorage.removeItem('pvpoke-app-run');sessionStorage.removeItem('pvpoke-app-batch');
  el('resume').hidden=true;
  message('計算を中止しました。完了済みの結果は表示したままです。');
  return;
 }
 if(batchState&&!batchState.results.length&&!batchState.run_ref&&!batchState.start_request_id){
  batchState=null;sessionStorage.removeItem('pvpoke-app-batch');
 }
 message((stopError||e).message+'\n完了済みの結果は表示を保持しています。後続の対象は未実行です。',true);
 el('resume').hidden=!(runRef||batchState);
}
el('cancelRun').onclick=async()=>{
 if(!active||!calculating||stopRequested)return;
 stopRequested=true;el('cancelRun').disabled=true;
 message('中止を要求しました。処理終了を確認中です。');
 if(runRef){
  try{await stopActiveRun();}catch(e){
   message('サーバー側の停止を確認できませんでした: '+e.message,true);
  }
 }
};
async function startSelection(){
 el('evaluation').value='app';
 if(active||metaWorking||metaDraft)return;
 if(!chosenMeta()){message('メタプリセットを選択してください。',true);return;}
 calculating=true;stopRequested=false;stopPromise=null;stopError=null;
 setBusy(true);el('results').hidden=true;
 try{
  const current=currentCandidate();
  const keep=importedSingle?.candidate.species===current.species&&importedSingle.ivs.trim()===el('ivs').value.trim();
  const inputJobs=importedJobs||[{candidate:current,ivs:el('ivs').value,
   name:catalog[el('species').value]?.name_ja||el('species').value,
   source_records:keep?importedSingle.source_records:[],source_sections:keep?importedSingle.source_sections:[],pokemon_status:inputPokemonStatus}];
  const auto_moves=el('autoMoves').checked===true,threshold=Number(el('moveThreshold').value);
  if(auto_moves&&(!Number.isFinite(threshold)||threshold<0||threshold>1000))throw Error('技の平均Rating下限は0〜1000で指定してください');
  if(auto_moves&&el('evaluation').value!=='app')throw Error('自動の技比較は「アプリで自動推薦」で使用してください');
  const mode=auto_moves?el('moveStrategy').value:'manual',jobs=planMovesets(freezeSelectionModes(inputJobs),mode);
  const compare_moves=el('evaluation').value==='app'&&(auto_moves||jobs.some((j,i,a)=>a.filter(x=>x.moveset_group===j.moveset_group).length>1));
  const plans=[...new Map(jobs.map(j=>[j.moveset_group,j.moveset_plan])).values()];
  el('movePlanSummary').textContent=plans.map(p=>p.selected+' / '+p.total+'構成を計算'+(p.omitted?'（選外 '+p.omitted+'構成は未計算）':'')+(p.incomplete?'。技性能データが不足しているため、自動候補の追加を省略しました。':'')).join(' / ');
  batchState={reader_automation_digest:readerAutomation?.digest||null,jobs,auto_moves,compare_moves,move_strategy:mode,move_threshold:auto_moves?threshold:0,move_threshold_setting:threshold,
   index:0,results:[],run_ref:null,meta_preset_id:selectedMetaId,meta_sha256:chosenMeta().sha256,
   batch_mode:'simple',focus:el('focus').value.split('\n').map(x=>x.trim()).filter(Boolean),
   report_format:el('evaluation').value==='app'?'app':'decision',force_recalculate:el('forceRecalculate').checked===true,
   policy:{meaningful_win_lead:Number(el('lead').value)}};
  cacheBatch();await executeBatch();
 }catch(e){handleCalculationError(e);}finally{calculating=false;setBusy(false);}
}
el('run').onclick=startSelection;
el('resume').onclick=async()=>{
 if(active||!(runRef||batchState))return;
 calculating=true;stopRequested=false;stopPromise=null;stopError=null;setBusy(true);
 try{
  if(batchState){await executeBatch();}
  else{const result=await finish(await api('result',{run_ref:runRef,wait_seconds:2}));renderSelectionResults([result]);runRef=null;sessionStorage.removeItem('pvpoke-app-run');el('resume').hidden=true;message('計算と結果の確認が完了しました。');}
 }catch(e){handleCalculationError(e);}finally{calculating=false;setBusy(false);}
};
el('disconnect').onclick=async()=>{try{await api('logout');}catch(e){message('ログアウトできませんでした。再試行してください。',true);return;}credential='';catalog={};metaState=null;selectedMetaId=null;clearMetaExport();nameEntries=[];opponentLabels.clear();displayedResults=[];nicknameBindings=[];presets=[];lastResult=null;setImportedJobs(null);batchState=null;el('results').replaceChildren();el('workspace').hidden=true;el('selectionSettingsOpen').hidden=true;el('selectionSettings').hidden=true;el('login').hidden=false;resetMetaUpload();message('接続を解除しました。このブラウザのログイン情報も削除しました。');};
// Opt-in reader automation uses the existing authenticated browser and selected meta.
let readerAutomation=null;
try{readerAutomation=JSON.parse(sessionStorage.getItem('pokemoniv-reader-automation')||'null');}catch{}
function configureReaderAutomation(params){
 const nonce=params.get('automation'),digest=params.get('digest');
 if(!nonce&&!digest){readerAutomation=null;sessionStorage.removeItem?.('pokemoniv-reader-automation');return;}
 if(!/^[a-f0-9]{64}$/.test(nonce||'')||!/^[a-f0-9]{64}$/.test(digest||''))throw Error('Invalid automation request');
 if(batchState&&(!readerAutomation||readerAutomation.digest!==digest))throw Error('別の計算が残っています。既存の計算を完了または中止してください');
 readerAutomation={nonce,digest};sessionStorage.setItem('pokemoniv-reader-automation',JSON.stringify(readerAutomation));
}
function discardSearchKey(query){return query.split('&').filter(t=>!['favorite','!favorite'].includes(t.trim().toLowerCase())).join('&');}
function readerDiscardQueries(results,keep=[]){
 // A search sent as a keep candidate must never also be sent for cleanup.
 const protectedSearches=new Set(keep.map(item=>discardSearchKey(item.search)));
 // Fail closed: every applicable evolution/moveset must explicitly dominate the IV.
 const sources=new Map();
 for(const r of results)for(const source of r.source_records||[]){
  const q=discardSearchKey(xxlProtectedSearch(statusSearch(source.search_string,r.pokemon_status)));
  if(protectedSearches.has(q))continue;
  if(q.split('&').some(t=>t.trim().toLowerCase()==='!xxl'))continue; // Ambiguous size-dependent forms require review; never widen their identity.
  if(!q||/[;,|\n\r]/.test(q)||!/(?:^|&)cp[0-9]+(?:&|$)/i.test(q))continue;
  if(!sources.has(q))sources.set(q,[]);sources.get(q).push({r,iv:source.ivs});
 }
 return [...sources].filter(([q,entries])=>entries.length&&entries.every(({r,iv})=>{
  const s=r.selection;
  if(s?.complete!==true||!s.dominated_by?.[iv]?.length)return false;
  const keep=(s.recommendations||[]).flatMap(x=>[x,...(x.equivalent_candidates||[])]);
  return ![...keep,...(s.review_candidates||[]),...(s.additional_candidates||[])].some(x=>x.ivs===iv);
 })).map(([q])=>q);
}
function returnReaderAutomation(results){
 if(!readerAutomation)return;
 const keep=displayedResults.some(r=>r.selection?.recommendations?.length)?JSON.parse(overlayExport(displayedResults)):{format:'pokemoniv-overlay-v2',items:[]};
 const result={format:'pokemoniv-automation-v1',...readerAutomation,keep,discard:readerDiscardQueries(results,keep.items)};
 const bytes=new TextEncoder().encode(JSON.stringify(result));
 if(bytes.length>18000){message('計算完了。結果が大きいため自動で返せません。Androidへ送るボタンから分割して適用してください。',true);return;}
 let binary='';for(const b of bytes)binary+=String.fromCharCode(b);
 const encoded=btoa(binary).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
 const url='intent://automation?payload='+encoded+'#Intent;scheme=pokemonivreader;package=com.example.pokemonivreader;end';
 const button=node('button','整理結果を読み取りアプリへ返す',el('results'),'primary');
 button.onclick=()=>window.location.assign(url);
 readerAutomation=null;sessionStorage.removeItem?.('pokemoniv-reader-automation');
 message('計算完了。自動で戻らない場合は「整理結果を読み取りアプリへ返す」を押してください。');
 try{window.location.assign(url);}catch{}
}

// Reader-to-browser handoff is kept in a URL fragment, never sent in an HTTP request.
function receiveReaderInput(){
 const params=new URLSearchParams(location.hash.slice(1));
 const encoded=params.get('ivdata');
 if(!encoded)return false;
 // Remove imported data from the address bar before parsing or showing it.
 history.replaceState(null,'',location.pathname+location.search);
 try{
  if(encoded.length>512000||!/^[A-Za-z0-9_-]+$/.test(encoded))throw Error('Invalid payload');
  const pad='='.repeat((4-encoded.length%4)%4);
  const bytes=Uint8Array.from(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')+pad),c=>c.charCodeAt(0));
  const value=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  if(bytes.length>384000||!value.startsWith('個体値厳選')||!/(?:^|\n)#\s*\S/.test(value))throw Error('Invalid IV input');
  configureReaderAutomation(params);readerInputText=value;readerImportPending=true;
  if(!active)el('importText').value=value;
  message('読み取りアプリから個体値を受け取りました。接続後に取り込み、比較と推薦の設定へ移動します。');
  return true;
 }catch(e){message('読み取りデータを自動入力できませんでした。コピーした内容を手動で貼り付けてください。',true);return false;}
}
const access=new URLSearchParams(location.hash.slice(1)).get('access');
if(access){history.replaceState(null,'',location.pathname+location.search);el('remember').checked=false;el('credential').value=access;connect(false);}else{receiveReaderInput();connect(true);}
if(typeof window!=='undefined')window.addEventListener('hashchange',()=>{if(receiveReaderInput())autoImportReader();});
</script></body></html>'''





