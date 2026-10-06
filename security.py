"""
案件5 - 署名検証
「届いた通知が、本当にLINEから来たものか」を確かめる。

仕組み:
  LINE は、メッセージの中身 + Channel Secret(LINEと自分だけが知る秘密)から
  HMAC-SHA256 で署名を作り、ヘッダー x-line-signature に付けて送ってくる。
  こちらも同じ計算をして、一致すれば本物。
"""
import base64
import hashlib
import hmac


def make_line_signature(body: bytes, channel_secret: str) -> str:
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def verify_line_signature(body: bytes, signature: str | None, channel_secret: str) -> bool:
    if not signature:
        return False
    expected = make_line_signature(body, channel_secret)
    # 普通の == ではなく compare_digest を使う(比較にかかる時間の差から秘密を推測されないため)
    return hmac.compare_digest(expected, signature)
