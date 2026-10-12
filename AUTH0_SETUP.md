# Railway PvPoke + Auth0 接続手順（v0.3試作）

## 重要

**OAuthを有効にする前に、Auth0のアカウントとAPIを設定してください。** 未設定のまま新しいコードを配備すると、元の `PVP_API_KEY` だけで動作します。すでに稼働中のAPIキーを削除しないでください。これは試作版です。実際のChatGPT接続は未検証です。

## Auth0で用意するもの

1. https://auth0.com/ で開発用テナントを作成。
2. Applications → APIs → Create API。API identifier を **`https://pokemoniv-production.up.railway.app/mcp`**、Signing Algorithm を **RS256** にする。
3. Tenant Settings → Default Audience も上記API identifierに設定（Auth0発行access tokenをJWT化）。
4. User Management → Users で自分だけのユーザーを作成。ユーザー画面の `user_id` を確認する（例 `auth0|...`）。この値は秘密鍵ではない。
5. Settings → Advanced で **Client ID Metadata Document (CIMD) Registration** を有効にする。ChatGPTのプラグイン連携側で表示されるCIMD URLをAuth0へ手動登録し、対象APIへのユーザー委任アクセスを許可する必要がある。MCPクライアント登録とredirect URIの許可はHost画面の案内に従う。
6. Auth0のテナント発行者URL（Issuer）を確認する。形式: `https://dev-xxxx.us.auth0.com/`。

公式参照:
https://developers.openai.com/plugins/build/auth
https://github.com/openai/openai-mcpkit/blob/main/python-authenticated-mcp-server-scaffold/README.md

## Railway Variables

既存の `PVP_API_KEY`、`PORT` は変更しないで、以下を追加:

| Key | 値 |
| --- | --- |
| `AUTH0_ISSUER` | `https://dev-xxxx.us.auth0.com/`（自分の実際のIssuer） |
| `JWT_AUDIENCE` | `https://pokemoniv-production.up.railway.app/mcp` |
| `AUTH0_ALLOWED_SUB` | 自分のAuth0の `user_id` |
| `PVP_MCP_URL` | `https://pokemoniv-production.up.railway.app/mcp` |
| `PVP_OAUTH_SCOPE` | `openid`（初期テスト用。実際のAuth0トークンにopenidが入るか確認） |

`AUTH0_ISSUER` を空にするとOAuthは無効で、APIキー方式のみ有効。`AUTH0_ALLOWED_SUB` が空の状態でAuth0を有効化すると安全のため起動を拒否する。

## テスト

- `/health` は200。
- `/.well-known/oauth-protected-resource` はOAuth設定後、`resource` と `authorization_servers` を含むJSONを返す。
- APIキーなしの `POST /mcp` は401を返し、`WWW-Authenticate` の resource_metadata にOAuthの設定先を示す。
- 既存のAPIキーで`tools/list`をすると従来どおり成功する。
- ChatGPTの登録とOAuthログインは別途実行。成功までを未検証と扱う。

## 制限

既存のMCPサーバーは一部のMCP Streamable HTTP機能のみを実装する試作サーバーであり、公式SDKではない。ツール探索、トークンの`aud`/`scope`、リダイレクト、セッション管理、ジョブの独立性は実機で検証が必要。PyJWTとcryptographyがクラウド用Dockerに追加される（Termux側でのRustビルドは不要）。運用ではリクエスト制限、非公開ジョブID、永続化、レート制限、監査等が必要。
