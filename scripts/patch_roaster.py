"""Patch one or more entries in config/roasters.json by id.
Usage: python3 scripts/patch_roaster.py '[{"id": "lomi", "url": "...", "domain": "...", "platform": "...", "notes": "..."}, ...]'
"""
import json
import sys

patches = json.loads(sys.argv[1])
path = "config/roasters.json"

with open(path, encoding="utf-8") as f:
    roasters = json.load(f)

by_id = {r["id"]: r for r in roasters}

for p in patches:
    rid = p["id"]
    if rid not in by_id:
        print(f"WARNING: id not found: {rid}")
        continue
    by_id[rid].update({k: v for k, v in p.items() if k != "id"})
    print(f"patched {rid}: {by_id[rid].get('platform')} — {by_id[rid].get('domain')}")

with open(path, "w", encoding="utf-8") as f:
    json.dump(roasters, f, ensure_ascii=False, indent=2)
