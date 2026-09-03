"""One-off generator for config/roasters.json skeleton (id, name, city, region).
URLs and platform are filled in later by the discovery pass, not by this script.
"""
import json
import re
import unicodedata

ROASTERS = [
    # (name, city, region)
    ("Terres de Café", "Paris", "Île-de-France"),
    ("Coutume Café", "Romainville", "Île-de-France"),
    ("Lomi", "Paris", "Île-de-France"),
    ("Belleville Brûlerie", "Paris", "Île-de-France"),
    ("L'Arbre à Café", "Paris", "Île-de-France"),
    ("Kawa", "Paris", "Île-de-France"),
    ("Hexagone Café", "Paris", "Île-de-France"),
    ("Dose", "Paris", "Île-de-France"),
    ("Partisan Café Artisanal", "Paris", "Île-de-France"),
    ("KB Coffee Roasters", "Paris", "Île-de-France"),
    ("Café d'Auteur", "Paris", "Île-de-France"),
    ("Café Nibi", "Suresnes", "Île-de-France"),
    ("Anbassa", "Melun", "Île-de-France"),
    ("GramGram", "Le Perreux-sur-Marne", "Île-de-France"),
    ("Cafés Factorerie", "Houdan", "Île-de-France"),
    ("Brûlerie Caron", "Saclay", "Île-de-France"),
    ("Gaia Torréfacteur", "Vincennes", "Île-de-France"),
    ("Liperli", "Paris", "Île-de-France"),
    ("Arlo's Coffee", "Rambouillet", "Île-de-France"),
    ("MOJO Coffee Club", "Bagnolet", "Île-de-France"),
    ("Cafés Lecoeur", "Épinay-sous-Sénart", "Île-de-France"),
    ("Laplaine Torréfacteur", "Pontoise", "Île-de-France"),
    ("Brûlerie des Gobelins", "Paris", "Île-de-France"),
    ("Bel Horizon Coffee Roasters", "Paris", "Île-de-France"),
    ("Cœur Coffee Roasters", "Paris", "Île-de-France"),
    ("Tanat Coffee", "Paris", "Île-de-France"),
    ("Substance", "Paris", "Île-de-France"),
    ("Early Bird", "Paris", "Île-de-France"),
    ("Café Claudio Nelda", "Moret-Loing-et-Orvanne", "Île-de-France"),
    ("Espeletia Café", "Paris", "Île-de-France"),

    ("Mokxa", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Celsius Roasters", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Fika Roasters", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Loutsa", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Café Toqué", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Café Chulo", "Fontaine", "Auvergne-Rhône-Alpes"),
    ("Café Côme", "Grenoble", "Auvergne-Rhône-Alpes"),
    ("Placid Roasters", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Signé Extrait", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Kaova", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Cafés Gonéo", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Tower Coffee", "Grenoble", "Auvergne-Rhône-Alpes"),
    ("Minouch", "Grenoble", "Auvergne-Rhône-Alpes"),
    ("Kaffa Torréfacteur", "Crest", "Auvergne-Rhône-Alpes"),
    ("Clinton Hill", "Clermont-Ferrand", "Auvergne-Rhône-Alpes"),

    ("L'Alchimiste", "Bordeaux", "Nouvelle-Aquitaine"),
    ("Café Piha", "Bordeaux", "Nouvelle-Aquitaine"),
    ("La Pelle Café", "Bordeaux", "Nouvelle-Aquitaine"),
    ("Cafés Lugat", "La Teste-de-Buch", "Nouvelle-Aquitaine"),
    ("Yellow Peak", "Pau", "Nouvelle-Aquitaine"),
    ("La Torref' / Icö", "Anglet", "Nouvelle-Aquitaine"),
    ("Cafés Kikeran", "Saint-Jean-de-Luz", "Nouvelle-Aquitaine"),
    ("La Brûlerie du Marché", "La Rochelle", "Nouvelle-Aquitaine"),
    ("L'Optimist Café", "La Rochelle", "Nouvelle-Aquitaine"),
    ("La Fabrique du Café", "Limoges", "Nouvelle-Aquitaine"),

    ("Hayuco Coffee Roasters", "Toulouse", "Occitanie"),
    ("Cafés Gorille", "Calvisson", "Occitanie"),
    ("Montista", "Montferrier-sur-Lez", "Occitanie"),
    ("Dyade Coffee", "Montpellier", "Occitanie"),
    ("Black Flamingo", "Nîmes", "Occitanie"),
    ("Valini", "Nîmes", "Occitanie"),
    ("Corbeau Specialty Coffee Roasters", "Montpellier", "Occitanie"),
    ("Café Plume", "Toulouse", "Occitanie"),
    ("Café 18grammes", "Saint-Jean-de-Fos", "Occitanie"),
    ("La Brûlerie des Filatiers", "Toulouse", "Occitanie"),
    ("Café Fraté", "Esclanèdes", "Occitanie"),
    ("L'Îlot Cafés", "Occitanie", "Occitanie"),
    ("Torrea", "Occitanie", "Occitanie"),

    ("Café Corto", "Marseille", "Provence-Alpes-Côte d'Azur"),
    ("MÖKA", "Marseille", "Provence-Alpes-Côte d'Azur"),
    ("Deep Coffee Roasters", "Marseille", "Provence-Alpes-Côte d'Azur"),
    ("Cafés Magali", "Toulon", "Provence-Alpes-Côte d'Azur"),
    ("Colombian Barista", "Nice", "Provence-Alpes-Côte d'Azur"),
    ("Colors Coffee & Roasters", "Aix-en-Provence", "Provence-Alpes-Côte d'Azur"),
    ("La Touche Café", "Saint-Victoret", "Provence-Alpes-Côte d'Azur"),

    ("Cime", "Nantes", "Pays de la Loire"),
    ("Café Loulé", "Nantes", "Pays de la Loire"),
    ("Kultivar", "Nantes", "Pays de la Loire"),
    ("TINTO", "Nantes", "Pays de la Loire"),
    ("Cafés BOC", "Le Mans", "Pays de la Loire"),

    ("Café 1802", "Rennes", "Bretagne"),
    ("HUG", "Binic-Étables-sur-Mer", "Bretagne"),
    ("Brûlerie du Léon", "Brest", "Bretagne"),
    ("Cafés Bozec", "Brest", "Bretagne"),
    ("Caffè Cataldi", "Louargat", "Bretagne"),
    ("Le Café qui Fume", "Plescop", "Bretagne"),

    ("Omnino", "Strasbourg", "Grand Est"),
    ("Cafés Reck", "Strasbourg", "Grand Est"),
    ("Café Bretelles", "Strasbourg", "Grand Est"),
    ("Moklair", "Reims", "Grand Est"),

    ("Coffee Makers", "Lille", "Hauts-de-France"),
    ("Pikaro Coffee", "Valenciennes", "Hauts-de-France"),
    ("Cafés Muda", "Lille", "Hauts-de-France"),

    ("Kawaty", "Châteauroux", "Centre-Val de Loire"),

    ("Au Cœur du Café", "Troyes", "Grand Est"),
]

def slugify(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n

def dedupe_ids(entries):
    seen = {}
    for e in entries:
        base = e["id"]
        if base in seen:
            seen[base] += 1
            e["id"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 0
    return entries

entries = []
for name, city, region in ROASTERS:
    entries.append({
        "id": slugify(name),
        "name": name,
        "city": city,
        "region": region,
        "country": "France",
        "url": None,
        "domain": None,
        "platform": None,  # "woocommerce" | "shopify" | "prestashop" | "custom" | "js-only" | "blocked"
        "notes": None,
    })

entries = dedupe_ids(entries)

assert len(entries) == 95, len(entries)

with open("config/roasters.json", "w", encoding="utf-8") as f:
    json.dump(entries, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(entries)} roasters to config/roasters.json")
