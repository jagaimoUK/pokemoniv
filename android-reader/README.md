# PokemonIVReader 正式Androidソース

2026-10-19 23:23のFormalSource ZIPを基準とした、地方の姿の判別・図鑑自動更新の実装です。Webアプリのソースは従来どおりリポジトリ直下です。

PC上では既存の `C:\Users\kuros\AndroidStudioProjects\PokemonIVReader` を更新します。新規プロジェクトは作らず、配布更新ZIPの `Apply-RegionalForms.ps1` を使用してください。

[実装・検証・引継ぎ](docs/RegionalForms_Handoff_20261020.md)

`verification/check.sh` は本番Kotlinの図鑑／OCR／保存経路と受け渡し契約を検証します。アプリ全体のAPKビルドや実機確認を代行するテストではありません。

アプリIDと署名設定は元の構成を維持します。署名鍵・端末データ・local.properties・バックアップはGitHubへ格納しません。
