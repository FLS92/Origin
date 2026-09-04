#!/usr/bin/env python3
"""Run the scraper for every roaster in config/roasters.json whose platform is
one we have a scraper for, writing/merging data/<id>.json for each, and
printing a per-roaster summary line plus totals at the end.

Usage:
    python3 run.py                # scrape every scrapable roaster
    python3 run.py tanat-coffee    # scrape just this one (by id)
"""
import json
import sys
import traceback

from scrapers import shopify, woocommerce, prestashop, odoo, squarespace, wizishop, magento, lomi

DISPATCH = {
    "shopify": shopify.scrape,
    "woocommerce": woocommerce.scrape,
    "prestashop": prestashop.scrape,
    "odoo": odoo.scrape,
    "squarespace": squarespace.scrape,
    "wizishop": wizishop.scrape,
    "magento": magento.scrape,
    "custom-swell": lomi.scrape,
}


def main():
    only_ids = set(sys.argv[1:]) or None

    with open("config/roasters.json", encoding="utf-8") as f:
        roasters = json.load(f)

    if only_ids:
        roasters = [r for r in roasters if r["id"] in only_ids]

    results = []
    for r in roasters:
        scrape_fn = DISPATCH.get(r["platform"])
        if scrape_fn is None:
            continue
        try:
            summary = scrape_fn(r)
            results.append(("ok", r, summary))
        except Exception as exc:
            results.append(("error", r, str(exc)))
            traceback.print_exc(file=sys.stderr)

    print("\n" + "=" * 70)
    print("RÉSUMÉ DU SCRAPING")
    print("=" * 70)
    ok_count = err_count = 0
    total_new = total_updated = total_unavailable = total_unchanged = total_excluded = 0
    for status, r, data in results:
        if status == "error":
            err_count += 1
            print(f"❌ {r['name']} ({r['platform']}) — ERREUR: {data}")
            continue
        ok_count += 1
        warn = f" ⚠️  {data['warning']}" if data.get("warning") else ""
        excluded_note = f", {data['excluded']} exclus (non-café)" if data.get("excluded") else ""
        print(
            f"✅ {data['roaster']}: {data['new']} nouvelles références, "
            f"{data['updated']} mises à jour, {data['newly_unavailable']} passées indisponibles, "
            f"{data['unchanged']} inchangées{excluded_note} (total {data['total_products']}){warn}"
        )
        total_new += data["new"]
        total_updated += data["updated"]
        total_unavailable += data["newly_unavailable"]
        total_unchanged += data["unchanged"]
        total_excluded += data.get("excluded", 0)

    print("-" * 70)
    print(
        f"{ok_count} torréfacteurs scrapés avec succès, {err_count} en erreur. "
        f"Total : {total_new} nouvelles, {total_updated} mises à jour, "
        f"{total_unavailable} passées indisponibles, {total_unchanged} inchangées, "
        f"{total_excluded} exclus (non-café)."
    )


if __name__ == "__main__":
    main()
