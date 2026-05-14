"""
テスト実行スクリプト: 2026年5月分をクロール → Google Sheetsに出力
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
sys.path.insert(0, os.path.dirname(__file__))

from x_monitor_bot import (
    KEYWORDS,
    GEMINI_API_KEY,
    get_x_client,
    fetch_tweets,
    analyze_sentiment,
    get_sheet,
    write_to_sheet,
    SEARCH_DELAY_SECONDS,
)


def main():
    missing = []
    if not os.environ.get("X_BEARER_TOKEN"):
        missing.append("X_BEARER_TOKEN")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not os.path.exists(os.path.join(os.path.dirname(__file__), "oauth_credentials.json")):
        missing.append("oauth_credentials.json")
    if missing:
        print(f"[ERROR] 未設定: {', '.join(missing)}")
        return

    # Basicプランは直近7日間のみ
    since = datetime.now(timezone.utc) - timedelta(days=7)
    print(f"検索期間: {since.strftime('%Y-%m-%d')} 〜 現在（X Basic: 直近7日間）")
    print(f"対象KW: {KEYWORDS}\n")

    client = get_x_client()
    all_tweets = []
    seen_ids = set()

    for keyword in KEYWORDS:
        print(f"[検索中] {keyword} ...")
        tweets = fetch_tweets(client, keyword, since)
        print(f"  → {len(tweets)} 件取得")
        for t in tweets:
            tid = str(t["tweet_id"])
            if tid not in seen_ids:
                all_tweets.append(t)
                seen_ids.add(tid)
        time.sleep(SEARCH_DELAY_SECONDS)

    print(f"\n合計 {len(all_tweets)} 件（重複除去済み）")

    if not all_tweets:
        print("投稿が見つかりませんでした。")
        return

    print("Gemini AIでポジネガ判定中...")
    all_tweets = analyze_sentiment(all_tweets)

    print("Google Sheetsに書き込み中...")
    sheet = get_sheet()
    write_to_sheet(sheet, all_tweets)

    pos = sum(1 for t in all_tweets if t.get("judgment") == "ポジティブ")
    neg = sum(1 for t in all_tweets if t.get("judgment") == "ネガティブ")
    neu = sum(1 for t in all_tweets if t.get("judgment") == "ニュートラル")
    print(f"\n✅ 完了: {len(all_tweets)} 件")
    print(f"   ポジティブ: {pos} / ネガティブ: {neg} / ニュートラル: {neu}")


if __name__ == "__main__":
    main()
