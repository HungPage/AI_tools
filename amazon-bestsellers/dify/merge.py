import json
import re
from datetime import datetime, timedelta, timezone

SUBS = [
    "耳機與音訊", "手機與平板配件", "充電與線材", "電腦與周邊", "儲存裝置",
    "智慧家庭", "電視與影音串流", "相機與攝影", "穿戴裝置", "遊戲周邊",
    "廚房家電", "清潔與空氣家電", "大型家電與零件", "個人護理家電", "其他",
]
LOW, HIGH = 25, 100  # 美元：低於 25 為低價，25 至 100 為中價，高於 100 為高價


def main(items_json: str, results: list) -> dict:
    items = json.loads(items_json)
    cls = {}
    for chunk in results or []:
        for line in str(chunk).splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and re.fullmatch(r"[A-Z0-9]{10}", parts[0]):
                cls[parts[0]] = parts[1:4]
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")  # 台北日期
    rows = []
    for it in items:
        sub, brand, points = cls.get(it["asin"], ["其他", "未知", ""])
        if sub not in SUBS:
            sub = "其他"
        price = it.get("price")
        if isinstance(price, (int, float)):
            tier = "低" if price < LOW else ("中" if price <= HIGH else "高")
        else:
            price, tier = "", "未知"
        rows.append({
            "date": today,
            "asin": it["asin"],
            "title": it["title"],
            "category": it["category"],
            "rank": it.get("rank") or "",
            "price": price,
            "currency": it.get("currency") or "$",
            "price_tier": tier,
            "sub_category": sub,
            "brand": brand or "未知",
            "selling_points": points,
        })
    return {
        "payload": json.dumps({"rows": rows}, ensure_ascii=False),
        "count": len(rows),
    }
