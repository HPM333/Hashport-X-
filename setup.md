# X Monitor Bot セットアップガイド

## 必要なもの
- Python 3.9+（インストール済み）
- X (Twitter) API Bearer Token（契約済み）
- Anthropic API Key
- Google アカウント（個人アカウントでOK）

---

## STEP 1 — ライブラリのインストール（完了済み）

```bash
pip3 install -r requirements.txt
```

---

## STEP 2 — Google Cloud で OAuth2 認証情報を作成

サービスアカウント不要。個人のGoogleアカウントで認証します。

### 2-1. プロジェクト作成＆API有効化

1. [console.cloud.google.com](https://console.cloud.google.com) を開く
2. 画面上部の「プロジェクトを選択」→「新しいプロジェクト」→ 名前は任意（例: `hashport-monitor`）→「作成」
3. 左メニュー → **APIとサービス** → **ライブラリ**
4. 「Google Sheets API」を検索して**有効化**
5. 「Google Drive API」も検索して**有効化**

### 2-2. OAuth2 認証情報を作成

1. 左メニュー → **APIとサービス** → **認証情報**
2. 「**認証情報を作成**」→「**OAuth クライアント ID**」
3. 初回は「同意画面を構成」を求められる場合あり:
   - User Type: **外部** → 「作成」
   - アプリ名: 任意（例: `X Monitor`）、サポートメール: 自分のアドレス → 保存して続行
   - スコープ・テストユーザーはスキップしてOK
4. 「OAuth クライアント ID の作成」に戻る
5. アプリケーションの種類: **デスクトップアプリ** → 名前は任意 → 「作成」
6. ダウンロードボタン（⬇）をクリック → JSONファイルを `oauth_credentials.json` にリネーム
7. `x_monitor/` フォルダに配置

```
x_monitor/
├── oauth_credentials.json   ← ここに配置
├── x_monitor_bot.py
└── ...
```

---

## STEP 3 — 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して2つのキーを設定：

```
X_BEARER_TOKEN=xxxxx
ANTHROPIC_API_KEY=xxxxx
```

`SPREADSHEET_NAME` はデフォルト「Hashport X投稿モニター」のままでOK（変更したい場合は記載）。

---

## STEP 4 — 初回実行（ブラウザ認証）

```bash
cd ~/Desktop/Claud/x_monitor
source .env
python3 x_monitor_bot.py
```

**初回のみ**ブラウザが自動で開き、Googleアカウントでのログインを求められます。
「このアプリはGoogleによって確認されていません」という警告が出た場合:
→「詳細」→「（アプリ名）に移動」→「許可」

認証完了後、`token.json` が自動保存され、**以降はブラウザ不要**で自動実行されます。

実行後、自分のGoogleドライブに「Hashport X投稿モニター」スプレッドシートが作成されます。

---

## STEP 5 — 毎日自動実行（cron）

毎朝9時JSTに実行する例：

```bash
crontab -e
```

以下を追記：

```
0 9 * * * /Users/noriyoshimatsuda/Desktop/Claud/x_monitor/run_bot.sh
```

ログは `x_monitor/logs/bot_YYYYMMDD.log` に蓄積されます。

---

## 動作仕様

- **上書き方式**: 毎日実行するたびにシートをクリアして当日分のデータで書き直し
- **重複除去**: `.seen_ids.txt` でツイートIDを管理（同じ投稿を2度収集しない）
- **検索期間**: 実行時刻から過去24時間以内の投稿

---

## スプレッドシートの列構成

| 列 | 内容 |
|---|---|
| 収集日時 | ボット実行日時（JST） |
| 投稿日時 | ツイート投稿日時（JST） |
| 投稿者アカウント | @username |
| 表示名 | 表示名 |
| 投稿内容 | ツイート本文 |
| 投稿URL | x.com へのリンク |
| マッチKW | 引っかかったキーワード |
| そのKWの総投稿数 | 同KWの24h以内の総ツイート数 |
| いいね数 | |
| RT数 | |
| 返信数 | |
| ポジネガ判定 | ポジティブ / ネガティブ / ニュートラル |
| 判定理由 | Claudeによる30字以内の理由 |

---

## キーワードのカスタマイズ

`x_monitor_bot.py` の `KEYWORDS` を編集：

```python
KEYWORDS = [
    "Hashport",
    "HashPortWallet",
    "HashPort Wallet",
    "ハッシュポート",
    "ハッシュポートウォレット",
]
```
