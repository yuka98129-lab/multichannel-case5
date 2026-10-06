"""
案件5 - 緊急通知 5分以内SLA の確認(チェックリスト「10件中9件以上」)
クレームのキーワードを含む10件を、署名付きのLINE Webhookとして流し、
受信から「LINE Pushを出した」までの時間を測る。
注意: LINEへの送信は「送ったつもり」の記録なので、本物のLINEの通信時間は含まない。
"""
import json
import os
import statistics

os.environ["CASE5_DB"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sla_test.db")

import db  # noqa: E402
import pipeline  # noqa: E402
from security import make_line_signature  # noqa: E402

SECRET = "test-channel-secret"
MESSAGES = [  # 私が作った10件(講座のサンプルとは別)
    "先週修理を頼んだのに、まだ誰も来ません。至急対応してください。",
    "隣の部屋の騒音がひどく、管理会社に何度言っても改善されません。苦情です。",
    "退去時の費用の請求が契約書と違います。クレームとして申し入れます。",
    "エントランスの鍵が壊れたままで危険です。至急直してください。",
    "管理人の対応が失礼でした。正式に苦情を申し上げます。",
    "給湯器が3日前から使えません。至急お願いします。もう怒りしかありません。",
    "更新料の説明を受けていません。クレームです。責任者から連絡をください。",
    "水漏れで下の階に迷惑をかけています。至急来てください。",
    "共用部の清掃がされておらず、苦情が出ています。対応をお願いします。",
    "何度連絡しても折り返しがありません。苦情として記録してください。",
]

db.init_db(reset=True)
for i, text in enumerate(MESSAGES, 1):
    body = json.dumps(
        {"events": [{"type": "message", "message": {"type": "text", "id": f"sla-{i}", "text": text}}]},
        ensure_ascii=False,
    ).encode("utf-8")
    status, res = pipeline.handle_line_webhook(body, make_line_signature(body, SECRET), SECRET)
    assert status == 200, (status, res)

with db.get_conn() as c:
    rows = c.execute(
        "SELECT q.external_id, q.category, o.sent_at - q.received_at AS sec "
        "FROM inquiry_queue q LEFT JOIN outbox o ON o.ref=q.external_id AND o.kind='line_push' "
        "ORDER BY q.id"
    ).fetchall()

secs = [r["sec"] for r in rows if r["sec"] is not None]
within = sum(1 for s in secs if s < 300)
print(f"LINE Pushが出た: {len(secs)}/10件")
print(f"5分(300秒)以内: {within}/10件   (基準: 9件以上)")
print(f"受信→Push 最短/平均/最長: {min(secs):.1f} / {statistics.mean(secs):.1f} / {max(secs):.1f} 秒")
for r in rows:
    print(f"  {r['external_id']:<7} 分類={r['category']}  {r['sec']:.1f}秒" if r["sec"] is not None
          else f"  {r['external_id']:<7} 分類={r['category']}  Pushなし")
json.dump(
    {"pushed": len(secs), "within_300s": within, "seconds": secs},
    open("sla_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2,
)
