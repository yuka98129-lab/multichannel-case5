"""
案件5 - 最小コストの監視
講座の例: Supabase の SQL 1本で「未処理件数」「失敗件数」を見る。
ここでは同じ考え方を手元の SQLite で動かす。(本番の SQL は README を参照)

使い方:  python3 monitor.py
本番では、これを Cron で1時間ごとに回し、失敗が多ければ Slack に警告を出す。
"""
import time

import db
from notifiers import post_to_slack

FAILED_THRESHOLD = 5          # 失敗がこの件数以上なら警告
STUCK_MINUTES = 10            # 「処理中」のまま、この分数を超えたら止まっているとみなす


def check_health(now=None):
    now = now or time.time()
    since = now - 24 * 3600
    with db.get_conn() as conn:
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM inquiry_queue WHERE received_at > ? GROUP BY status",
                (since,),
            )
        }
        stuck = conn.execute(
            "SELECT COUNT(*) FROM inquiry_queue WHERE status='processing' AND received_at < ?",
            (now - STUCK_MINUTES * 60,),
        ).fetchone()[0]

    failed = by_status.get("failed", 0)
    warnings = []
    if failed >= FAILED_THRESHOLD:
        warnings.append(f"失敗が{failed}件(しきい値{FAILED_THRESHOLD}件以上)")
    if stuck:
        warnings.append(f"「処理中」のまま{STUCK_MINUTES}分以上止まっているものが{stuck}件")
    if warnings:
        post_to_slack("その他", "⚠️ 監視アラート: " + " / ".join(warnings), ref="monitor")
    return {"by_status": by_status, "stuck": stuck, "warnings": warnings}


if __name__ == "__main__":
    result = check_health()
    print("直近24時間の件数(状態別):")
    for status, n in sorted(result["by_status"].items()):
        print(f"  {status:<11} {n}")
    print(f"処理中のまま止まっている: {result['stuck']}件")
    print("警告:", result["warnings"] or "なし")
