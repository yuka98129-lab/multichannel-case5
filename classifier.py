"""
案件5 - Claude による問い合わせの分類
入力: 問い合わせ本文 / 出力: {"category": ..., "reason": ...}
"""
import json
import re
import subprocess

# Headless モード(claude -p)で分類する。講座で習った「画面なしでClaudeを呼ぶ」方法そのもの。
# (この作業環境では Claude API のキーが無かったが、claude コマンドは使えたのでこちらを採用。
#  本番で API を直接呼ぶ場合は、この関数の中身だけ差し替えればよい)
CATEGORIES = ["賃貸", "売買", "内見", "クレーム", "その他"]

SYSTEM_PROMPT = """あなたは不動産管理会社の問い合わせ振り分け担当です。
届いたメッセージを、次の5つのうち1つだけに分類してください。

- 賃貸: 借りる側の問い合わせ(物件探し、家賃、更新、乗り換え、退去・敷金精算など賃貸契約に関する質問)
- 売買: 購入・売却・投資・査定・住宅ローンなど
- 内見: 物件の見学の日程・方法の希望が主な目的のもの(物件探しが主で、内見は付け足しの場合は賃貸か売買)
- クレーム: 対応や管理状況への苦情・不満・正式な申し入れ(設備の不具合への強い抗議や、契約内容との食い違いの指摘を含む)
- その他: 不動産と無関係、または判断できないもの

注意:
- 「至急」「緊急」などの言葉があるだけでクレームにしない。内容が苦情・不満かどうかで判断する。
- 「クレームではありません」「緊急ではありません」と書かれていれば、書かれた意図を尊重して判断する。
- 無理に4つのどれかに当てはめず、無関係なものは「その他」にする。

次のJSONだけを出力してください(説明文や```は付けない):
{"category": "賃貸|売買|内見|クレーム|その他", "reason": "20字程度の理由"}"""


def classify_with_claude(text: str, timeout: int = 90) -> dict:
    proc = subprocess.run(
        ["claude", "-p", "--system-prompt", SYSTEM_PROMPT, "--tools", "", "--no-session-persistence"],
        input=text, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p が失敗しました: {proc.stderr.strip()[:200]}")
    raw = proc.stdout.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(match.group(0)) if match else {}
    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"分類結果が想定外です: {raw[:200]}")
    return {"category": category, "reason": data.get("reason", "")}
