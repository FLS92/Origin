"""Title-based safety net against non-coffee products slipping through a
platform's category filter (gift cards, workshops, subscriptions, brewing
equipment). Applied inside apply_products() so it runs on every scrape, not
as a one-off cleanup — see the schema doc's requirement that recurring runs
stay clean.

Keywords are equipment BRAND/MODEL names or exact multi-word phrases, never
a bare word like "filtre" — many real coffees are legitimately named or
labelled "Filtre" (roasted for filter brewing), and excluding on that word
alone would silently drop real products. Verified against the full scraped
dataset before being finalized (see project history) — every keyword here
matched zero coffee-bean products when checked by hand.
"""
import re
import unicodedata

EXCLUDE_KEYWORDS = [
    # Gift cards
    "carte cadeau", "e-carte",
    # Workshops / classes
    "atelier", "s'inscrire", "formation", "cours de degustation", "workshop",
    # Subscriptions (a delivery plan, not a specific coffee)
    "abonnement",
    # Brewing equipment brands/models — never used as a coffee's own name
    "dripper", "v60", "chemex", "moccamaster", "kalita", "hario", "origami",
    "aeropress", "espro", "porte-filtre", "porte filtre", "cafetiere",
    "grinder", "moulin a cafe", "moulin electrique", "balance", "tamper",
    "tasse", "mug", "t-shirt", "tshirt", "goodies",
    # Accessory phrases (not the bare word "filtre"/"capsule")
    "filtre papier", "filtres papier", "filtre a eau", "filtres a eau",
    "capsule reutilisable", "capsules reutilisables",
    "capsule a remplir", "capsules a remplir",
    "capsule vide", "capsules vides", "porte-capsule",
]


def _norm(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", n)


def excluded_reason(name):
    """Returns the matched keyword if `name` looks like a non-coffee product,
    else None."""
    n = _norm(name)
    for kw in EXCLUDE_KEYWORDS:
        if kw in n:
            return kw
    return None
