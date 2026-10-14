# 厳選Project情報源とサーバースナップショットの使用

## 原本と照合
- Projectの `pvpokeメタポケモン.txt` を、その時点の元情報として利用する。2026-10-13の原本87行はGitHub `jagaimoUK/pokemoniv` の `pvpoke_meta_opponents.csv` に取り込まれているが、その後の変更は自動同期されない。
- 一括24条件MCPを使う前に、現在のProjectの4列行がサーバーのスナップショットと一致するか照合する。不一致なら、更新内容を反映するか、旧MCPでProject原本を入力として使用する。
- 原本は `species,fast,charged1,charged2` の4列を基本とする。8列の場合、元のIVやLvは参照データとして別管理する。技構成の重複削除・代替技への勝手な変更は禁止。
- `_shadow-shadow` はPvPoke出力表記。MCP入力では末尾 `-shadow` のみ除いて `_shadow` を保持する。通常を勝手にシャドウ化しない。
- 存在しない種・技や未対応技を見つけたら、行番号と除外理由を示す。除外を0点として加算しない。

## 自動個体値モード
`default`, `rank1`, `attack`, `defense`のみ。情報源IVの自動設定は禁止。元IVは `source_ivs` として保持し、明示的な相手 `iv_mode:'source'` で手動利用する。`custom` は手入力のみ。24条件自動処理は原本IVを採用しない。

## 新一括経路
`prepare_24_conditions` → `start_24_conditions` → `get_status` → `get_24_summary` と `get_results({mode,shield,offset,limit})`。単一実行。4自動モード×同数3/不利3シールド = 24条件。サーバーはメタファイルの全行を読み、種・技の検証で除外があれば報告する。

## 旧経路の継続
Project原本とGitHubスナップショットが異なる、または新MCPが未使用の場合、Project情報源を80行以内に分割し、4自動モードをそれぞれ指定して従来MCPの6条件を実行する。毎回 `get_status` の done と全ページ結果取得を確認してから次のジョブへ進む。最新ZIPが上書きされるため、計測結果を各ジョブごとに保持する。全件終了後に対戦相手列を整合して集計する。

## 重要な注意
ChatGPT ProjectのファイルをRailwayが直接読み出すことはできない。一括版のメタファイルは**同期ではなく同梱コピー**。情報源が変わったら再反映が必要。

