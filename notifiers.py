"""
案件5 - 通知の送信(今回は「送ったつもり」の記録で代用)
本番では:
  Slack: https://slack.com/api/chat.postMessage (Bearer SLACK_BOT_TOKEN)
  LINE : https://api.line.me/v2/bot/message/push (Bearer LINE_CHANNEL_ACCESS_TOKEN)
この環境からは外部に送れないので、outbox テーブルに残す。送信の呼び出し口(関数)は本番と同じ形。
"""
import time

from db import get_conn

SLACK_CHANNELS = {
    "賃貸": "#賃貸の問い合わせ",
    "売買": "#売買の問い合わせ",
    "内見": "#内見希望",
    "クレーム": "#クレーム",
    "その他": "#要確認",  # 分類対象外も捨てずに「要確認」へ(見落とし防止)
}
MANAGER_LINE_USER_ID = "U_manager_dummy"


def post_to_slack(category: str, text: str, ref: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO outbox (kind, target, body, ref, sent_at) VALUES (?,?,?,?,?)",
            ("slack", SLACK_CHANNELS[category], text, ref, time.time()),
        )


def push_line_to_manager(text: str, ref: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO outbox (kind, target, body, ref, sent_at) VALUES (?,?,?,?,?)",
            ("line_push", MANAGER_LINE_USER_ID, text, ref, time.time()),
        )
