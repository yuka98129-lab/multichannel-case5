"""
案件5 - 統合テスト
  A. 署名検証(本物は通り、偽物・改ざんは弾く)
  B. 22件の問い合わせを、LINE/メールの本物の入口を通して流す → Cronで処理 → 結果を照合
  C. 冪等性(同じ通知の再送で二重通知が出ないか)
  D. 追加の意地悪ケース(キーワードがあるのにクレームではない / AI障害時の安全側の動き)
"""
import csv
import json
import time

import db
import pipeline
from security import make_line_signature

SECRET = "test-channel-secret"
results = {"A": [], "B": [], "C": [], "D": [], "rows": [], "urgent_latency_sec": []}


def line_body(msg_id, text):
    return json.dumps(
        {"events": [{"type": "message", "message": {"type": "text", "id": msg_id, "text": text}}]},
        ensure_ascii=False,
    ).encode("utf-8")


def send_line(msg_id, text, secret=SECRET, tamper=False):
    body = line_body(msg_id, text)
    sig = make_line_signature(body, secret)
    if tamper:
        body = body.replace("エアコン".encode(), "エアコソ".encode())  # 途中で書き換えられた想定
    return pipeline.handle_line_webhook(body, sig, SECRET)


def count_outbox(kind, ref=None):
    with db.get_conn() as c:
        if ref:
            return c.execute("SELECT COUNT(*) FROM outbox WHERE kind=? AND ref=?", (kind, ref)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM outbox WHERE kind=?", (kind,)).fetchone()[0]


def check(bucket, name, ok, detail=""):
    results[bucket].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"  [{'OK' if ok else 'NG'}] {name} {detail}")


db.init_db(reset=True)

# ---------- A. 署名検証 ----------
print("=== A. 署名検証 ===")
body = line_body("sig-test", "テスト")
good_sig = make_line_signature(body, SECRET)
from security import verify_line_signature  # noqa: E402

check("A", "正しい署名は通る", verify_line_signature(body, good_sig, SECRET))
check("A", "別の秘密で作った偽署名は弾く", not verify_line_signature(body, make_line_signature(body, "wrong"), SECRET))
check("A", "署名ヘッダーが無いものは弾く", not verify_line_signature(body, None, SECRET))
status, _ = send_line("sig-tamper", "エアコンが効きません。至急対応してください。苦情です。", tamper=True)
check("A", "本文が途中で書き換えられたら401で拒否", status == 401)
check("A", "拒否したものはキューに入らない", db.get_row("sig-tamper") is None)

# ---------- B. 22件を流す ----------
print("\n=== B. 22件の問い合わせ(LINE/メールの入口を通す) ===")
rows = list(csv.DictReader(open("case5-test-inquiries.csv", encoding="utf-8")))
for r in rows:
    ext = f"case5-{r['番号']}"
    if r["チャネル"] == "line":
        status, _ = send_line(ext, r["問い合わせ本文"])
        assert status == 200
    else:
        pipeline.handle_gmail_message(ext, r["問い合わせ本文"])

t0 = time.time()
n = pipeline.process_pending(limit=50)  # Cron 1回分
print(f"  Cronで処理: {n}件 ({time.time() - t0:.1f}秒)")

correct, detail_rows = 0, []
for r in rows:
    ext = f"case5-{r['番号']}"
    row = db.get_row(ext)
    expected = "その他" if r["期待カテゴリ"].startswith("その他") else r["期待カテゴリ"]
    ok = row["category"] == expected
    correct += ok
    expected_urgent = r["緊急"] == "TRUE"
    pushed = count_outbox("line_push", ext) > 0
    detail_rows.append({
        "no": int(r["番号"]), "channel": r["チャネル"], "text": r["問い合わせ本文"],
        "expected": expected, "actual": row["category"], "category_ok": ok,
        "expected_urgent": expected_urgent, "pushed": pushed, "push_ok": pushed == expected_urgent,
        "status": row["status"],
    })
    if not ok or pushed != expected_urgent:
        print(f"  [NG] No.{r['番号']} 期待={expected}/緊急={expected_urgent} → 実際={row['category']}/Push={pushed}")

push_ok = sum(d["push_ok"] for d in detail_rows)
check("B", f"カテゴリ分類 {correct}/22", correct == 22)
check("B", f"緊急通知の判定(Pushすべきものだけ鳴らした) {push_ok}/22", push_ok == 22)
with db.get_conn() as c:
    urgent_lat = [
        r["sent_at"] - q["received_at"]
        for r in c.execute("SELECT * FROM outbox WHERE kind='line_push' AND ref LIKE 'case5-%'")
        for q in [c.execute("SELECT received_at FROM inquiry_queue WHERE external_id=?", (r["ref"],)).fetchone()]
    ]
print(f"  緊急通知までの時間(受信→LINE Push): {[round(x, 1) for x in urgent_lat]} 秒")
check("B", "緊急通知は全て5分(300秒)以内", all(x < 300 for x in urgent_lat))
results["rows"] = detail_rows
results["urgent_latency_sec"] = urgent_lat

# ---------- C. 冪等性 ----------
print("\n=== C. 冪等性(再送されても二重処理しない) ===")
before_push, before_slack = count_outbox("line_push"), count_outbox("slack")
resend = next(r for r in rows if r["番号"] == "19")
for _ in range(3):  # LINEが同じ通知を3回再送してきた想定
    send_line("case5-19", resend["問い合わせ本文"])
pipeline.process_pending()
check("C", "緊急通知を3回再送されてもLINE Pushは増えない", count_outbox("line_push") == before_push)
check("C", "Slackへの投稿も増えない", count_outbox("slack") == before_slack)
send_line("case5-1", rows[0]["問い合わせ本文"])
pipeline.process_pending()
check("C", "通常の問い合わせの再送でもSlack投稿は増えない", count_outbox("slack") == before_slack)

# ---------- D. 意地悪ケース ----------
print("\n=== D. 追加の意地悪ケース(講座のサンプルには無い、私が追加したもの) ===")
edge = [
    ("edge-1", "至急、内見をお願いしたいです。明日の午後で空いていますか？", "内見", False),
    ("edge-2", "これはクレームではなく、単なる質問です。更新料はいくらですか？", "賃貸", False),
]
for ext, text, exp_cat, exp_push in edge:
    send_line(ext, text)
    pipeline.process_pending()
    row = db.get_row(ext)
    pushed = count_outbox("line_push", ext) > 0
    check("D", f"{ext}: キーワードが入っていても {exp_cat} として扱い、営業部長は鳴らさない",
          row["category"] == exp_cat and pushed == exp_push, f"(分類={row['category']}, Push={pushed})")

# AI障害を模擬: 分類関数を壊しても、クレームかもしれないものは見逃さない
orig = pipeline.classify_with_claude
pipeline.classify_with_claude = lambda text: (_ for _ in ()).throw(RuntimeError("API障害(模擬)"))
send_line("edge-3", "苦情です。至急連絡をください。")
pipeline.classify_with_claude = orig
row = db.get_row("edge-3")
pushed = count_outbox("line_push", "edge-3") > 0
check("D", "AI障害時は安全側(要確認付きで緊急通知)に倒れる", pushed and row["status"] == "notified", f"(Push={pushed})")

json.dump(results, open("test_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n=== 結果 ===")
all_checks = results["A"] + results["B"] + results["C"] + results["D"]
print(f"全チェック: {sum(x['ok'] for x in all_checks)}/{len(all_checks)} OK")
