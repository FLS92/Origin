#!/usr/bin/env python3
"""Builds docs/world-countries.json, a small vendored set of country border
outlines for the "Carte des torréfacteurs" map in index.html.

Source: Natural Earth's public-domain 1:110m Admin-0 Countries dataset (the
lowest-detail tier they publish, meant exactly for small stylized world
maps like this one) -- NOT fetched at runtime by the app; downloaded once
here and simplified further, then committed as a static asset alongside
coffees-data.json, consistent with how the rest of the site avoids depending
on third-party services at page-load time.

Each country keeps only its largest ring (drops small offshore islands/
exclaves -- irrelevant at this map's scale and this app's "approximate is
fine" brief) and is simplified with Douglas-Peucker down to a handful of
points, since the on-screen map is small and doesn't need coastline detail.

Usage:
    python3 scripts/build_world_map.py
"""
import json
import math
import urllib.request

SOURCE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
OUT_PATH = "docs/world-countries.json"
SIMPLIFY_EPSILON_DEG = 0.1


def perpendicular_distance(pt, start, end):
    if start == end:
        return math.hypot(pt[0] - start[0], pt[1] - start[1])
    x1, y1 = start
    x2, y2 = end
    x0, y0 = pt
    num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    den = math.hypot(y2 - y1, x2 - x1)
    return num / den


def douglas_peucker(points, epsilon):
    if len(points) < 3:
        return points
    dmax, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perpendicular_distance(points[i], points[0], points[-1])
        if d > dmax:
            index, dmax = i, d
    if dmax > epsilon:
        left = douglas_peucker(points[: index + 1], epsilon)
        right = douglas_peucker(points[index:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


def ring_bbox_area(ring):
    lngs = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (max(lngs) - min(lngs)) * (max(lats) - min(lats))


def largest_ring(geometry):
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    rings = [poly[0] for poly in polys]
    return max(rings, key=ring_bbox_area)


def main():
    with urllib.request.urlopen(SOURCE_URL) as resp:
        data = json.load(resp)

    out = []
    for feature in data["features"]:
        props = feature["properties"]
        name = props.get("NAME_FR") or props.get("NAME")
        # ISO_A2 is "-99" for a handful of countries in this dataset
        # (France, Norway, Kosovo...) due to their disputed/complex admin
        # status -- ISO_A2_EH ("de-facto" boundaries) doesn't have that gap.
        iso2 = props.get("ISO_A2")
        if not iso2 or iso2 == "-99":
            iso2 = props.get("ISO_A2_EH")
        if not name or not iso2 or iso2 == "-99":
            continue
        ring = largest_ring(feature["geometry"])
        simplified = douglas_peucker(ring, SIMPLIFY_EPSILON_DEG)
        # GeoJSON stores [lng, lat]; the app's projection wants [lat, lng].
        points = [[round(lat, 2), round(lng, 2)] for lng, lat in simplified]
        out.append({"name": name, "iso2": iso2, "points": points})

    out.sort(key=lambda c: c["name"])
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    total_pts = sum(len(c["points"]) for c in out)
    print(f"{len(out)} pays, {total_pts} points au total -> {OUT_PATH}")


if __name__ == "__main__":
    main()
