#!/usr/bin/env python3
"""Transform data/*.json (schema-scraping-origin.md) into app/coffees-data.json,
the shape origin-app.html fetches at startup: {roasters: {...}, coffees: [...]}.

Only roasters with at least one product are included — an empty roaster entry
would just be dead weight in the app's filters. Missing optional fields are
left as null (the app's na() helper already treats null like its 'Indisponible'
sentinel), except a retailer's price, where the app expects the literal string
'Indisponible' when unknown (that's how it's rendered directly in the UI).

Run this after run.py, or standalone: python3 scripts/build_app_data.py
"""
import json
import os

DATA_DIR = "data"
CONFIG_PATH = "config/roasters.json"
OUT_PATH = "app/coffees-data.json"


def format_price(price, currency):
    if price is None:
        return "Indisponible"
    symbol = {"EUR": "€", "GBP": "£", "USD": "$"}.get(currency, currency or "€")
    formatted = f"{price:.2f}".replace(".", ",")
    return f"{formatted} {symbol}" if symbol in ("€",) else f"{symbol}{formatted}"


def format_note(retailer):
    parts = []
    if retailer.get("unitWeightG"):
        g = retailer["unitWeightG"]
        parts.append(f"{g/1000:g} kg" if g >= 1000 else f"{g} g")
    if retailer.get("priceNote"):
        parts.append(retailer["priceNote"])
    if retailer.get("inStock") is False:
        parts.append("rupture de stock")
    return ", ".join(parts)


def transform_retailer(r):
    return {
        "site": r.get("site") or "",
        "url": r.get("url") or "",
        "price": format_price(r.get("price"), r.get("currency")),
        "note": format_note(r),
    }


def transform_product(p, roaster_id):
    country = p.get("originCountry")
    detail = p.get("originDetail")
    if country and detail:
        origin = f"{country} · {detail}"
    else:
        origin = country or detail or None

    flavors = p.get("flavors")
    flavors_str = ", ".join(flavors) if flavors else None

    return {
        "id": p["id"],
        "roasterId": roaster_id,
        "name": p["name"],
        "origin": origin,
        "originCountry": country,
        "process": p.get("process"),
        "usage": p.get("method"),
        "variety": p.get("variety"),
        "producer": p.get("producer"),
        "score": p.get("score"),
        "acidity": p.get("acidity"),
        "body": p.get("body"),
        "roast": p.get("roastLevel"),
        "flavors": flavors_str,
        "desc": p.get("description"),
        "imageUrl": p.get("imageUrl"),
        "available": p.get("available", True),
        "retailers": [transform_retailer(r) for r in p.get("retailers", [])],
    }


def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        roasters_config = {r["id"]: r for r in json.load(f)}

    roasters_out = {}
    coffees_out = []
    latest_scrape = None

    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".json"):
            continue
        roaster_id = fname[:-5]
        with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
            d = json.load(f)
        latest_scrape = max(latest_scrape or d["scrapedAt"], d["scrapedAt"])
        products = [p for p in d["products"] if p.get("available", True)]
        if not products:
            continue

        meta = roasters_config.get(roaster_id, {})
        roasters_out[roaster_id] = {
            "name": d["roaster"]["name"],
            "city": meta.get("city"),
            "url": d["roaster"]["url"],
            "domain": d["roaster"]["domain"],
        }
        coffees_out.extend(transform_product(p, roaster_id) for p in products)

    out = {
        "generatedAt": latest_scrape,
        "roasterCount": len(roasters_out),
        "coffeeCount": len(coffees_out),
        "roasters": roasters_out,
        "coffees": coffees_out,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"{len(roasters_out)} torréfacteurs, {len(coffees_out)} cafés -> {OUT_PATH}")


if __name__ == "__main__":
    main()
