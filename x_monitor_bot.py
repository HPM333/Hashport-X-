"""
X (Twitter) Monitor Bot for Hashport-related keywords
Collects posts daily and overwrites Google Sheets with AI sentiment analysis
"""

import os
import time
import re
import json
import tweepy
import gspread
from google import genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from datetime import datetime, timezone, timedelta

# ローカル実行時のみ .env を読み込む（GitHub Actions では環境変数で渡す）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# ─── Config ───────────────────────────────────────────────────────────────────

KEYWORDS = [
    "Hashport",
    "HashPortWallet",
    "HashPort Wallet",
    "ハッシュポート",
    "ハッシュポートウォレット",
]

# X API v2 Bearer Token (set in env or .env)
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "")

# Google Gemini API Key (free tier: aistudio.google.com/app/apikey)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Google Sheets settings
# oauth_credentials.json: OAuth2 Desktop App credentials downloaded from Google Cloud Console
OAUTH_CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "oauth_credentials.json")
# token.json: saved automatically after first browser auth, reused on subsequent runs
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Hashport X投稿モニター")
SHEET_NAME = "X投稿ログ"

GSHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Search period: last 24 hours
HOURS_BACK = 24

# Rate limit: X Basic plan = 1 request/15s for search
SEARCH_DELAY_SECONDS = 2

# ─── Spreadsheet columns ──────────────────────────────────────────────────────

HEADERS = [
    "収集日時",
    "投稿日時",
    "投稿者アカウント",
    "表示名",
    "投稿内容",
    "投稿URL",
    "マッチKW",
    "そのKWの総投稿数",
    "いいね数",
    "RT数",
    "返信数",
    "ポジネガ判定",
    "判定理由",
]

# ─── X API client ─────────────────────────────────────────────────────────────

def get_x_client() -> tweepy.Client:
    return tweepy.Client(
        bearer_token=X_BEARER_TOKEN,
        wait_on_rate_limit=True,
    )


def build_query(keyword: str) -> str:
    """Build X search query. Exclude retweets to avoid duplicates."""
    if " " in keyword:
        q = f'"{keyword}"'
    else:
        q = keyword
    return f"{q} -is:retweet"


def fetch_tweets(client: tweepy.Client, keyword: str, since: datetime) -> list[dict]:
    """Fetch tweets for a single keyword within the time window."""
    query = build_query(keyword)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    results = []
    try:
        response = client.search_recent_tweets(
            query=query,
            start_time=since_str,
            max_results=100,
            tweet_fields=["created_at", "public_metrics", "author_id", "text"],
            user_fields=["username", "name"],
            expansions=["author_id"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"[ERROR] X API error for '{keyword}': {e}")
        return []

    if not response.data:
        return []

    # Build user lookup map
    users = {}
    if response.includes and "users" in response.includes:
        for u in response.includes["users"]:
            users[u.id] = u

    total_count = response.meta.get("result_count", len(response.data)) if response.meta else len(response.data)

    for tweet in response.data:
        user = users.get(tweet.author_id, None)
        username = user.username if user else str(tweet.author_id)
        display_name = user.name if user else ""
        metrics = tweet.public_metrics or {}

        results.append({
            "keyword": keyword,
            "keyword_total": total_count,
            "tweet_id": tweet.id,
            "created_at": tweet.created_at,
            "username": username,
            "display_name": display_name,
            "text": tweet.text,
            "url": f"https://x.com/{username}/status/{tweet.id}",
            "like_count": metrics.get("like_count", 0),
            "retweet_count": metrics.get("retweet_count", 0),
            "reply_count": metrics.get("reply_count", 0),
        })

    return results


# ─── AI sentiment analysis via Gemini (free tier) ─────────────────────────────

_gemini_client = None

def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


BATCH_SIZE = 20  # 20件まとめて1リクエスト → 101件なら6回のAPI呼び出しで完了


def analyze_sentiment(tweets: list[dict]) -> list[dict]:
    """Batch AI sentiment analysis using Gemini Flash (free tier).
    Sends BATCH_SIZE tweets per request to minimize API calls."""
    if not tweets:
        return tweets

    client = _get_gemini()
    total = len(tweets)

    for batch_start in range(0, total, BATCH_SIZE):
        batch = tweets[batch_start: batch_start + BATCH_SIZE]

        # Build numbered tweet list for the prompt
        tweet_list = "\n".join(
            f"[{i+1}] {t['text'].replace(chr(10), ' ')}"
            for i, t in enumerate(batch)
        )

        prompt = f"""あなたはWeb3/暗号資産領域のSNS分析の専門家です。
以下の{len(batch)}件のX（Twitter）投稿それぞれについて、Hashport／HashPort Walletに対する感情・姿勢を総合的に判断してください。

【判定基準】
- ポジティブ: 好意、期待、称賛、利用意向、良いニュースの拡散
- ネガティブ: 不満、批判、問題報告、不信感、詐欺懸念
- ニュートラル: 単純な情報共有、質問、言及のみ、判断困難

【投稿一覧】
{tweet_list}

以下のJSON配列形式のみで回答してください（番号順、説明不要）:
[
  {{"id": 1, "judgment": "ポジティブ|ネガティブ|ニュートラル", "reason": "40字以内"}},
  ...
]"""

        for attempt in range(5):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                raw = response.text.strip()
                m = re.search(r'\[.*?\]', raw, re.DOTALL)
                if m:
                    results = json.loads(m.group())
                    for item in results:
                        idx = item.get("id", 0) - 1
                        if 0 <= idx < len(batch):
                            batch[idx]["judgment"] = item.get("judgment", "ニュートラル")
                            batch[idx]["judgment_reason"] = item.get("reason", "")
                else:
                    for t in batch:
                        t.setdefault("judgment", "ニュートラル")
                        t.setdefault("judgment_reason", "解析失敗")
                break  # 成功したらリトライ終了
            except Exception as e:
                err_str = str(e)
                # レート制限の場合はエラーメッセージの待ち時間を守る
                wait_match = re.search(r'retry in (\d+\.?\d*)s', err_str)
                wait_sec = float(wait_match.group(1)) + 2 if wait_match else 30 * (attempt + 1)
                print(f"  [WARN] レート制限 → {wait_sec:.0f}秒待機 (attempt {attempt+1}/5)")
                time.sleep(wait_sec)
                if attempt == 4:
                    for t in batch:
                        t.setdefault("judgment", "エラー")
                        t.setdefault("judgment_reason", "API quota超過")

        done = min(batch_start + BATCH_SIZE, total)
        print(f"  判定済み: {done}/{total}")
        time.sleep(5)

    return tweets


# ─── Google Sheets ────────────────────────────────────────────────────────────

def _get_google_creds() -> Credentials:
    """OAuth2 flow: use saved token if valid, else open browser for auth."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GSHEET_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDENTIALS_FILE, GSHEET_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def get_sheet():
    """Connect to Google Sheets and return (gc, spreadsheet, sheet)."""
    creds = _get_google_creds()
    gc = gspread.authorize(creds)

    # Open by name; create if not exists
    try:
        spreadsheet = gc.open(SPREADSHEET_NAME)
    except gspread.exceptions.SpreadsheetNotFound:
        spreadsheet = gc.create(SPREADSHEET_NAME)
        print(f"[INFO] Created new spreadsheet: {SPREADSHEET_NAME}")
        print(f"  → URL: https://docs.google.com/spreadsheets/d/{spreadsheet.id}")

    # Get or create sheet tab
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=10000, cols=len(HEADERS))

    return sheet


_JUDGMENT_COLORS = {
    "ポジティブ": {"red": 0.776, "green": 0.937, "blue": 0.808},  # 緑 #C6EFCE
    "ネガティブ": {"red": 1.0,   "green": 0.780, "blue": 0.808},  # 赤 #FFC7CE
    "ニュートラル": {"red": 1.0, "green": 0.922, "blue": 0.612},  # 黄 #FFEB9C
}


def _color_judgment_cells(sheet, tweets: list[dict]):
    """L列（ポジネガ判定）をポジ=緑、ネガ=赤、ニュートラル=黄で色付け。"""
    fmt_requests = []
    for i, t in enumerate(tweets):
        color = _JUDGMENT_COLORS.get(t.get("judgment", ""))
        if color:
            row = i + 2  # 1行目はヘッダー
            fmt_requests.append({
                "range": f"L{row}",
                "format": {"backgroundColor": color},
            })
    if fmt_requests:
        sheet.batch_format(fmt_requests)


def _format_header(sheet):
    try:
        sheet.format(f"A1:{chr(ord('A') + len(HEADERS) - 1)}1", {
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
        })
    except Exception:
        pass


def write_to_sheet(sheet, tweets: list[dict]):
    """Clear sheet and overwrite with today's data."""
    now_jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    rows = [HEADERS]

    for t in tweets:
        if t["created_at"]:
            posted_jst = t["created_at"].astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
        else:
            posted_jst = ""

        rows.append([
            now_jst,
            posted_jst,
            t.get("username", ""),
            t.get("display_name", ""),
            t.get("text", "").replace("\n", " "),
            t.get("url", ""),
            t.get("keyword", ""),
            t.get("keyword_total", 0),
            t.get("like_count", 0),
            t.get("retweet_count", 0),
            t.get("reply_count", 0),
            t.get("judgment", ""),
            t.get("judgment_reason", ""),
        ])

    # Clear all and rewrite from A1
    sheet.clear()
    sheet.update("A1", rows, value_input_option="USER_ENTERED")
    sheet.freeze(rows=1)
    _format_header(sheet)
    _color_judgment_cells(sheet, tweets)
    print(f"[INFO] Overwrote sheet with {len(rows) - 1} rows.")


# ─── Deduplication ───────────────────────────────────────────────────────────

def load_seen_ids(path: str) -> set:
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return set(line.strip() for line in f if line.strip())


def save_seen_ids(path: str, ids: set):
    with open(path, "w") as f:
        for id_ in sorted(ids):
            f.write(f"{id_}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] X Monitor Bot starting...")

    # Validate env
    missing = []
    if not X_BEARER_TOKEN:
        missing.append("X_BEARER_TOKEN")
    if not os.path.exists(OAUTH_CREDENTIALS_FILE):
        missing.append(f"oauth_credentials.json (at {OAUTH_CREDENTIALS_FILE})")
    if missing:
        print(f"[ERROR] Missing configuration: {', '.join(missing)}")
        print("  → .env と oauth_credentials.json を確認してください")
        return

    client = get_x_client()
    since = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)

    seen_ids_path = os.path.join(os.path.dirname(__file__), ".seen_ids.txt")
    seen_ids = load_seen_ids(seen_ids_path)

    all_tweets = []
    new_ids = set()

    for keyword in KEYWORDS:
        print(f"[INFO] Searching: {keyword}")
        tweets = fetch_tweets(client, keyword, since)
        print(f"  → {len(tweets)} tweets found")

        # Deduplicate across keywords
        for t in tweets:
            tid = str(t["tweet_id"])
            if tid not in seen_ids and tid not in new_ids:
                all_tweets.append(t)
                new_ids.add(tid)

        time.sleep(SEARCH_DELAY_SECONDS)

    print(f"[INFO] Total new unique tweets: {len(all_tweets)}")

    print("[INFO] Running AI sentiment analysis...")
    all_tweets = analyze_sentiment(all_tweets)

    print("[INFO] Writing to Google Sheets...")
    sheet = get_sheet()
    write_to_sheet(sheet, all_tweets)

    # Persist seen IDs — trim to latest 10000 to avoid unbounded growth
    combined_ids = seen_ids | new_ids
    if len(combined_ids) > 10000:
        combined_ids = set(sorted(combined_ids, reverse=True)[:10000])
    save_seen_ids(seen_ids_path, combined_ids)

    print(f"[INFO] Done. {len(all_tweets)} new tweets processed.")


if __name__ == "__main__":
    main()
