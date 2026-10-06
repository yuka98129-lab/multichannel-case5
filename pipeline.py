"""
案件5 - 受信(Webhook) → 通常パス / 緊急パス → Cron で分類・通知
講座のコード例との違い(講座の例の弱点を直したところ):
  1. 緊急パスでも「同じ番号は処理しない」を先に確認する(再送で二重通知を防ぐ)
  2. キーワードは「緊急かもしれない」の入口にとどめ、最終判断は Claude に任せる
  3. 署名の比較は hmac.compare_digest を使う
  4. Claude が失敗したときは、見落としを避けるため「要確認」付きで緊急通知する
"""
import json
import re
import time

import db
from classifier import classify_with_claude
from notifiers import post_to_slack, push_line_to_manager
from security import verify_line_signature

# 緊急「かもしれない」の入口(最終判断はこの後 Claude がする)
URGENT_CANDIDATE_RE = re.compile(r"クレーム|至急|苦情|怒り")


def ingest(channel: str, external_id: str, text: str) -> dict:
    """1件のメッセージを受け取り、緊急パスか通常パスに振り分ける。"""
    if not URGENT_CANDIDATE_RE.search(text):
        # --- 通常パス: キューに溜めるだけ(分類はCronが1分ごとにやる) ---
        saved = db.insert_inquiry(channel, external_id, text, status="pending")
        return {"path": "normal", "duplicate": not saved}

    # --- 緊急パス(候補): 受け取った関数の中で最後まで完結させる ---
    # まず保存を試みる。保存できなければ「もう処理済みの再送」なので何もしない(冪等性)
    saved = db.insert_inquiry(channel, external_id, text, status="pending")
    if not saved:
        return {"path": "urgent", "duplicate": True}

    try:
        result = classify_with_claude(text)
    except Exception as e:  # Claudeが落ちていても、クレームかもしれないものを見逃さない
        db.update_inquiry(
            external_id, category="クレーム", is_urgent=1, status="notified",
            error=f"AI判定失敗のため緊急扱い: {e}", classified_at=time.time(), notified_at=time.time(),
        )
        post_to_slack("クレーム", f"🚨 緊急(AI判定失敗・要確認): {text}", external_id)
        push_line_to_manager(f"🚨 緊急対応(AI判定失敗・要確認): {text}", external_id)
        return {"path": "urgent", "duplicate": False, "category": "クレーム", "fallback": True}

    if result["category"] == "クレーム":
        db.update_inquiry(
            external_id, category="クレーム", is_urgent=1, status="notified",
            classified_at=time.time(), notified_at=time.time(),
        )
        post_to_slack("クレーム", f"🚨 緊急: {text}", external_id)
        push_line_to_manager(f"🚨 緊急対応: {text}", external_id)
        return {"path": "urgent", "duplicate": False, "category": "クレーム"}

    # キーワードは入っていたが、Claudeがクレームではないと判断 → 通常パスに戻す
    db.update_inquiry(
        external_id, category=result["category"], status="classified", classified_at=time.time()
    )
    return {"path": "urgent→normal", "duplicate": False, "category": result["category"]}


def handle_line_webhook(body: bytes, signature: str | None, channel_secret: str):
    """LINE の Webhook を受ける入口。(HTTPステータス, 結果) を返す。"""
    # 1. 署名検証(必ず最初。本文を JSON に直す前の「生のまま」で検証する)
    if not verify_line_signature(body, signature, channel_secret):
        return 401, {"error": "invalid signature"}

    # 2. 本文から、テキストメッセージだけ取り出す
    events = json.loads(body).get("events", [])
    results = []
    for ev in events:
        if ev.get("type") != "message" or ev["message"].get("type") != "text":
            continue
        results.append(ingest("line", ev["message"]["id"], ev["message"]["text"]))
    return 200, results


def handle_gmail_message(message_id: str, text: str):
    """Gmail 経由の受信(本番は Google の Pub/Sub 通知 → Gmail API で本文取得。ここでは本文を直接受ける)。"""
    return 200, [ingest("gmail", message_id, text)]


def process_pending(limit: int = 20) -> int:
    """Cron が1分ごとに呼ぶ処理。待っている問い合わせを分類して Slack に振り分ける。"""
    rows = db.fetch_rows(["pending", "classified"], limit)
    # 先に「処理中」の札を付ける(前回のCronがまだ動いている間に次のCronが来ても、同じものを取り合わない)
    for row in rows:
        db.update_inquiry(row["external_id"], status="processing")
    done = 0
    for row in rows:
        ext = row["external_id"]
        try:
            category = row["category"]
            if row["status"] == "pending" or not category:
                category = classify_with_claude(row["raw_content"])["category"]
                db.update_inquiry(ext, category=category, status="classified", classified_at=time.time())
            if category == "クレーム":
                # 通常パスで来たがクレームと判定された場合も、緊急通知を出す
                post_to_slack("クレーム", f"🚨 緊急: {row['raw_content']}", ext)
                push_line_to_manager(f"🚨 緊急対応: {row['raw_content']}", ext)
                db.update_inquiry(ext, is_urgent=1)
            else:
                post_to_slack(category, f"[{row['channel']}] {row['raw_content']}", ext)
            db.update_inquiry(ext, status="notified", notified_at=time.time())
            done += 1
        except Exception as e:
            db.update_inquiry(ext, status="failed", error=str(e))
    return done
