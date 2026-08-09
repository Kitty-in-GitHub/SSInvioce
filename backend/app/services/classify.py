from __future__ import annotations

from pathlib import Path

from ..models import MaterialType

ORDER_KEYWORDS = ("订单", "淘宝", "京东", "拼多多", "天猫", "order", "taobao", "jd")
PAYMENT_KEYWORDS = ("支付", "支付宝", "微信", "付款", "收款", "账单", "alipay", "wechat", "pay")


def classify_file(
    filename: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> MaterialType:
    name = filename.lower()
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return "invoice"

    # Filename heuristics first for payment/order keywords
    if any(k in filename or k in name for k in PAYMENT_KEYWORDS):
        return "payment"
    if any(k in filename or k in name for k in ORDER_KEYWORDS):
        return "order"

    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"} and width and height and height > 0:
        ratio = height / width
        # Tall screenshots often order pages; phone-like portrait leans payment
        if ratio >= 1.6:
            return "order"
        if 1.3 <= ratio < 1.6 and width <= 1200:
            return "payment"
        if ratio >= 1.2:
            return "order"

    return "unknown"
