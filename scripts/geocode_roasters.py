#!/usr/bin/env python3
"""Geocode each roaster in config/roasters.json to a city-level lat/lng,
for the "Carte des torréfacteurs" map feature. Uses OpenStreetMap's free
Nominatim API (no key needed) rather than fabricating coordinates.

Only queries roasters missing lat/lng, so re-running after adding a new
roaster is cheap. Sleeps 1s between requests per Nominatim's usage policy
(https://operations.osmfoundation.org/policies/nominatim/), which also
requires a descriptive User-Agent identifying the application.

A miss (no match, or an ambiguous/ambulant query) leaves lat/lng as null
rather than guessing -- the map simply skips roasters with no coordinates.

Usage:
    python3 scripts/geocode_roasters.py                 # all roasters missing lat/lng
    python3 scripts/geocode_roasters.py tanat-coffee     # just this one, by id (re-geocodes even if already set)
"""
import json
import sys
import time

import requests

CONFIG_PATH = "config/roasters.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "origin-coffee-app-geocoder/1.0 (https://github.com/FLS92/Origin)"


def geocode(city, region, country):
    query = ", ".join(p for p in [city, region, country] if p)
    if not query:
        return None
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def main():
    only_ids = set(sys.argv[1:]) or None
    with open(CONFIG_PATH, encoding="utf-8") as f:
        roasters = json.load(f)

    found = skipped = 0
    for r in roasters:
        if only_ids:
            if r["id"] not in only_ids:
                continue
        elif r.get("lat") is not None and r.get("lng") is not None:
            continue

        city, region, country = r.get("city"), r.get("region"), r.get("country")
        if not city and not region:
            print(f"{r['name']}: pas de ville/région connue, ignoré")
            r.setdefault("lat", None)
            r.setdefault("lng", None)
            skipped += 1
            continue

        print(f"{r['name']} ({city or '?'}, {country or '?'})")
        try:
            coords = geocode(city, region, country)
        except Exception as exc:
            print(f"  échec : {exc}")
            coords = None
        time.sleep(1)

        if coords:
            r["lat"], r["lng"] = coords
            found += 1
            print(f"  -> {coords[0]:.4f}, {coords[1]:.4f}")
        else:
            r.setdefault("lat", None)
            r.setdefault("lng", None)
            skipped += 1
            print("  -> aucune coordonnée trouvée")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(roasters, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n{found} torréfacteurs géolocalisés, {skipped} sans coordonnées.")


if __name__ == "__main__":
    main()
