"""Extracts origin country / process / brewing method from a product's own
NAME rather than its description — roasters very commonly put these right
in the title ("Rumudamo [Natural]", "Éthiopie Moka Yrgacheffe", "Blend
Espresso [Bio]"). Free, deterministic, and safe: a country/process word
appearing in a coffee's own title is the roaster naming that fact about
THIS product, not a guess on our part — same "only if explicit" rule as
everywhere else in this pipeline.

Matches whole words only (word-boundary), so e.g. "Inde" doesn't fire
inside "Indépendant" and "Congo" doesn't fire inside a longer unrelated
word — verified against the current catalog before shipping (see project
history) to confirm no coffee is actually NAMED after one of these terms
in a way that would misfire.
"""
import re

from .parsing import norm, normalize_method

# Multi-word phrases must be checked before single words ("costa rica"
# before a stray "rica" would ever be considered, which it isn't anyway --
# but "republique dominicaine" must win over nothing matching "dominicaine"
# alone, since that's not in the single-word map).
_COUNTRY_PHRASES = {
    "costa rica": "Costa Rica",
    "el salvador": "Salvador",
    "rd congo": "RD Congo",
    "republique dominicaine": "République Dominicaine",
    "porto rico": "Porto Rico",
    "papouasie nouvelle guinee": "Papouasie-Nouvelle-Guinée",
    "sri lanka": "Sri Lanka",
}
_COUNTRY_WORDS = {
    "ethiopie": "Éthiopie", "ethiopia": "Éthiopie",
    "kenya": "Kenya",
    "colombie": "Colombie", "colombia": "Colombie",
    "bresil": "Brésil", "brazil": "Brésil",
    "guatemala": "Guatemala",
    "rwanda": "Rwanda",
    "burundi": "Burundi",
    "honduras": "Honduras",
    "nicaragua": "Nicaragua",
    "salvador": "Salvador",
    "panama": "Panama",
    "perou": "Pérou", "peru": "Pérou",
    "bolivie": "Bolivie",
    "mexique": "Mexique", "mexico": "Mexique",
    "indonesie": "Indonésie", "indonesia": "Indonésie",
    "vietnam": "Vietnam",
    "yemen": "Yémen",
    "ouganda": "Ouganda", "uganda": "Ouganda",
    "tanzanie": "Tanzanie", "tanzania": "Tanzanie",
    "congo": "RD Congo",
    "equateur": "Équateur",
    "cuba": "Cuba",
    "jamaique": "Jamaïque", "jamaica": "Jamaïque",
    "malawi": "Malawi",
    "zambie": "Zambie",
    "chine": "Chine", "china": "Chine",
    "laos": "Laos",
    "thailande": "Thaïlande",
    "myanmar": "Myanmar",
    "nepal": "Népal",
    "haiti": "Haïti",
    "guadeloupe": "Guadeloupe",
    "reunion": "La Réunion",
}
_PROCESS_PHRASES = {
    "co fermente": "Co-fermenté",
}
_PROCESS_WORDS = {
    "naturel": "Naturel", "natural": "Naturel", "nature": "Naturel",
    "lave": "Lavé", "lavee": "Lavé", "washed": "Lavé",
    "honey": "Honey", "miel": "Honey",
    "anaerobie": "Anaérobie", "anaerobic": "Anaérobie",
}


def extract_from_title(name):
    n = norm(name)
    words = n.split()
    word_set = set(words)
    out = {}

    for phrase, country in _COUNTRY_PHRASES.items():
        if phrase in n:
            out["originCountry"] = country
            break
    if "originCountry" not in out:
        for word in words:
            country = _COUNTRY_WORDS.get(word)
            if country:
                out["originCountry"] = country
                break

    for phrase, process in _PROCESS_PHRASES.items():
        if phrase in n:
            out["process"] = process
            break
    if "process" not in out:
        for word in words:
            process = _PROCESS_WORDS.get(word)
            if process:
                out["process"] = process
                break

    method = normalize_method(name)
    if method:
        out["method"] = method

    return out
