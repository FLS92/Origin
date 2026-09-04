#!/usr/bin/env python3
"""Fetch a logo URL for each roaster in config/roasters.json that has a
usable one — a <img> that reads as the site's logo, falling back to a
high-res favicon (apple-touch-icon) when no clean logo is found. Every
candidate is verified to actually respond as an image before being saved;
otherwise logoUrl stays null (the app already renders an initials badge
when there's no logo, so a dead link is strictly worse than nothing).

Usage:
    python3 scripts/fetch_logos.py                 # all roasters with a url
    python3 scripts/fetch_logos.py tanat-coffee lomi # just these, by id
"""
import json
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, ".")
from scrapers.common.http import session, get  # noqa: E402

CONFIG_PATH = "config/roasters.json"

LOGO_SELECTORS = [
    'img[class*="logo" i]',
    'img[id*="logo" i]',
    'a[class*="logo" i] img',
    'header img',
    '.site-header img',
    '.header img',
]

ICON_RELS = ["apple-touch-icon", "apple-touch-icon-precomposed", "icon", "shortcut icon"]


def find_logo_candidates(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for sel in LOGO_SELECTORS:
        for img in soup.select(sel):
            src = img.get("src") or img.get("data-src") or img.get("data-srcset", "").split(" ")[0]
            if src:
                candidates.append(urljoin(base_url, src))

    for rel in ICON_RELS:
        for link in soup.select(f'link[rel="{rel}"]'):
            href = link.get("href")
            if href:
                candidates.append(urljoin(base_url, href))

    # de-dupe, keep order
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def verify_image(s, url):
    try:
        resp = get(s, url, timeout=10, allow_redirects=True)
    except Exception:
        return False
    if resp.status_code != 200:
        return False
    ctype = ""
    if hasattr(resp, "headers"):
        ctype = resp.headers.get("content-type", "")
    if ctype:
        return ctype.startswith("image/")
    # curl fallback shim has no headers — accept based on status alone
    return True


def find_logo(domain, url):
    s = session()
    try:
        resp = get(s, url, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  homepage fetch failed: {exc}")
        return None
    for candidate in find_logo_candidates(resp.text, url):
        if verify_image(s, candidate):
            return candidate
    return None


def main():
    only_ids = set(sys.argv[1:]) or None
    with open(CONFIG_PATH, encoding="utf-8") as f:
        roasters = json.load(f)

    found = skipped = 0
    for r in roasters:
        if only_ids and r["id"] not in only_ids:
            continue
        if not r.get("url"):
            continue
        print(f"{r['name']} ({r['domain']})")
        logo = find_logo(r["domain"], r["url"])
        r["logoUrl"] = logo
        if logo:
            found += 1
            print(f"  -> {logo}")
        else:
            skipped += 1
            print("  -> aucun logo valide trouvé")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(roasters, f, ensure_ascii=False, indent=2)

    print(f"\n{found} logos trouvés, {skipped} sans logo valide.")


if __name__ == "__main__":
    main()
