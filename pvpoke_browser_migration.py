"""Same-origin browser export/import; no server-side data or credentials."""
from pathlib import Path


def page():
    return '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ブラウザ保存データのバックアップと復元</title><style>
body{font:17px system-ui;line-height:1.7;max-width:44rem;margin:auto;padding:1rem;background:#f0f4ef;color:#273d35}
section{background:#fff;padding:1.2rem;border-radius:24px;margin:1rem 0}button,input{font:inherit;padding:.9rem;max-width:100%;box-sizing:border-box;border:1px solid #91aaa0;border-radius:20px}button{background:#d7e8df}button:disabled{opacity:.5}a{color:#245e4d}p{overflow-wrap:anywhere}
</style><h1>ブラウザ保存データのバックアップと復元</h1>
<p>元のサイトと移行先を、同じ端末・ブラウザでそれぞれ開いて操作してください。先に両サイトの計算を完了し、ほかのアプリ画面・タブを閉じてください。</p>
<section><h2>1. 元のサイトで保存</h2><p>技構成、保存済みの計算再開情報、フラッシュカードの全保存レコードをSHA256付きJSONに保存します。サーバーのSQLite・メタ・パーティ・ZIPとAndroid読み取り履歴はこのファイルに含みません。別途保存したバックアップも維持してください。入力フォームの未保存内容は含まれません。ファイルは非公開で保管してください。</p>
<button id="migrationPreview" type="button">保存対象を確認</button><p class="quiet">上のボタンは内容を表示するだけで、データを変更しません。</p><button id="migrationExport" type="button">このブラウザの全データをバックアップ</button></section>
<section><h2>2. 移行先で復元</h2><p>異なるデータがある場合は上書きせず停止します。元の保存データとファイルはそのまま残ります。</p><input id="migrationFile" type="file" accept="application/json,.json" aria-label="保存したJSONファイル">
<button id="migrationImport" disabled>確認したデータを復元</button></section>
<p id="migrationStatus" role="status" aria-live="polite"></p>
<p>ログイン用Cookie・接続キーは移行しません。移行先で再ログインしてください。サーバーのパーティ・メタ・計算履歴は別途移行が必要です。再開情報は保存できますが、実行中の計算はサーバー側の移行が終わるまで再開できません。</p>
<a href="/app">厳選アプリへ</a> · <a href="/flashcards">フラッシュカードへ</a>
<script>''' + Path(__file__).with_suffix('.js').read_text(encoding='utf-8') + '</script></html>'
