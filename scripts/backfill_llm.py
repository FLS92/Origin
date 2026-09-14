#!/usr/bin/env python3
"""One-time backfill: apply paraphrase.analyze_product (the LLM extraction
path, needs ANTHROPIC_API_KEY) to existing products in data/*.json, using the
raw text harvested by harvest_raw_text.py (scratch/raw_text_dump.jsonl).

Unlike backfill_labeled_fields.py (deterministic, free, run first), this
spends real API credit -- one call per product. Only fills fields that are
still null; never overwrites a value a platform's own structured data or the
deterministic label pass already found. Also fills `description`, which is
LLM-only and not touched by any other backfill script.

Run harvest_raw_text.py first, then backfill_labeled_fields.py (free), then
this. Usage:
    python3 scripts/backfill_llm.py            # every candidate in the dump
    python3 scripts/backfill_llm.py --limit 10  # first N only, for a test run
"""
import argparse
import json
import os
import sys

sys.path.insert(0, ".")
from scrapers.common.paraphrase import analyze_product  # noqa: E402

DUMP_PATH = "scratch/raw_text_dump.jsonl"
SCHEMA_FIELDS = [
    "originCountry", "originDetail", "process", "variety", "producer",
    "score", "acidity", "body", "method", "roastLevel", "flavors", "harvestYear",
]


def load_env_file(path=".env"):
    if not os.environ.get("ANTHROPIC_API_KEY") and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N candidates (for a test run)")
    args = parser.parse_args()

    load_env_file()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (checked env and .env) -- aborting.", file=sys.stderr)
        sys.exit(1)

    candidates = []
    with open(DUMP_PATH, encoding="utf-8") as f:
        for line in f:
            candidates.append(json.loads(line))
    if args.limit:
        candidates = candidates[: args.limit]

    data_by_roaster = {}
    for fname in os.listdir("data"):
        if fname.endswith(".json"):
            roaster_id = fname[:-5]
            with open(f"data/{fname}", encoding="utf-8") as f:
                data_by_roaster[roaster_id] = json.load(f)

    products_by_id = {}
    for roaster_id, d in data_by_roaster.items():
        for p in d["products"]:
            products_by_id[p["id"]] = (roaster_id, p)

    def save(roaster_id):
        path = f"data/{roaster_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_by_roaster[roaster_id], f, ensure_ascii=False, indent=2)

    updated_products = updated_fields = errors = 0
    touched_roasters = set()
    calls_made = 0

    for c in candidates:
        entry = products_by_id.get(c["id"])
        if not entry:
            continue
        roaster_id, p = entry
        calls_made += 1
        try:
            analysis = analyze_product(c["name"], c["text"])
        except Exception as exc:
            errors += 1
            print(f"  [{calls_made}/{len(candidates)}] {c['name'][:60]!r} -> ERROR: {exc}")
            continue
        changed = False

        if p.get("description") is None and analysis.get("description"):
            p["description"] = analysis["description"]
            updated_fields += 1
            changed = True

        for field in SCHEMA_FIELDS:
            if p.get(field) is None and analysis.get(field) is not None:
                p[field] = analysis[field]
                updated_fields += 1
                changed = True

        if changed:
            updated_products += 1
            touched_roasters.add(roaster_id)
            save(roaster_id)  # written immediately -- a crash further down must not lose paid-for work
        print(f"  [{calls_made}/{len(candidates)}] {c['name'][:60]!r} -> "
              f"{'updated' if changed else 'nothing new'}")

    print(f"\n{calls_made} appels API ({errors} erreurs), {updated_products} produits mis à jour "
          f"({updated_fields} champs remplis) sur {len(touched_roasters)} torréfacteurs")


if __name__ == "__main__":
    main()
