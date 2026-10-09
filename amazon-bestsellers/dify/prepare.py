import json
import re

BATCH_SIZE = 25


def main(body: str) -> dict:
    data = json.loads(body)
    items, lines, seen = [], [], set()
    for it in data:
        if not isinstance(it, dict) or it.get("error"):
            continue
        url = it.get("url") or ""
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
        asin = it.get("asin") or (m.group(1) if m else "")
        cat = it.get("category") or it.get("categoryName") or ""
        cat = re.sub(r"^Amazon Best Sellers:\s*(Best\s+)?", "", cat).strip()
        key = asin + "@" + cat
        if not asin or key in seen:
            continue
        seen.add(key)
        name = it.get("name") or it.get("title") or ""
        name = name.replace("&amp;", "&").replace("|", "/").strip()[:120]
        price = it.get("price")
        if isinstance(price, dict):
            price = price.get("value")
        items.append({
            "asin": asin,
            "rank": it.get("position") or it.get("rank"),
            "title": name,
            "price": price,
            "currency": it.get("currency") or "$",
            "category": cat,
        })
        lines.append(asin + " | " + name)
    batches = [
        "\n".join(lines[i:i + BATCH_SIZE])
        for i in range(0, len(lines), BATCH_SIZE)
    ]
    return {
        "items_json": json.dumps(items, ensure_ascii=False),
        "batches": batches,
        "count": len(items),
    }
