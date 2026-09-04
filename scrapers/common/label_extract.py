"""Extracts schema fields from a product's free-text description when the
roaster writes it as "Label : Value" pairs (very common: "Variété : Geisha
Altitude : 1800m Process : Lavé Notes de dégustation : Pêche, Jasmin" — with
no consistent separator, casing or label set between sites).

Deterministic, no API call — runs on every scrape automatically, unlike the
LLM extraction path which needs ANTHROPIC_API_KEY. Only fills a field when
its label is explicitly present; free-flowing marketing prose with no labels
at all yields nothing here (left for the LLM path, or null), never a guess.

Label BOUNDARIES are detected generically (any "Capitalized phrase :" run of
1-4 words), rather than off an enumerated list — labels appear in far more
variants across 60+ independent sites than any list could keep up with, and
a missed boundary silently corrupts the *previous* field's value by letting
it run on into the next label's text. Only the small FIELD_LABELS map below
decides which of those recognized boundaries actually gets extracted into a
schema field; everything else is (correctly) just a boundary, not a value.

Verified against a hand-reviewed sample of scrapers/../scratch/raw_text_dump.jsonl
before the label map and safety checks below were finalized — see project history.
"""
import re
import unicodedata

# label (normalized, accents stripped) -> schema field.
FIELD_LABELS = {
    "process": [
        "process de sechage", "processus de traitement", "traitement apres recolte",
        "process post recolte", "type de process", "traitement", "procede",
        "process", "sechage",
    ],
    "variety": [
        "variete botanique", "varietes", "variete", "cultivar", "espece",
    ],
    "producer": [
        "producteurs", "producteur", "cooperative", "ferme",
    ],
    "originDetail": ["region", "localite"],
    "originCountry": ["pays", "origine"],
    "score": ["score"],
    "flavors": [
        # "profil a la tasse" deliberately excluded: sometimes a discrete
        # note list, sometimes a flowing descriptive sentence ("Un café
        # d'une grande clarté...") -- too inconsistent to trust as a list.
        "notes de degustation", "note de degustation", "notes aromatiques",
        "notes gustatives", "profil aromatique", "saveurs", "notes", "note", "nez",
    ],
    "body": ["corps"],
    "acidity": ["acidite"],
    "_method": ["extraction recommandee"],  # needs normalization, handled separately
}

_LABEL_TO_FIELD = {label: field for field, labels in FIELD_LABELS.items() for label in labels}

# A flavor item is a short noun/adjective phrase ("fruits rouges", "vin de
# pêche") — never a full sentence. When one bleeds into a trailing marketing
# line with no label of its own, it almost always starts with a copywriting
# imperative like these; reject the item rather than keep it.
_SENTENCE_MARKERS = (
    "degustez", "decouvrez", "ouvrez", "savourez", "profitez", "selectionnez",
    "offrez", "essayez", "laissez", "preparez",
)

# Some sites' description text carries a UI slider's label with no value of
# its own next to it ("Niveau de torréfaction", then nothing — the actual
# level was a visual bar, not text). No colon follows, so it can't be a
# _LABEL_RE boundary, and it silently glues onto whatever field came before
# it. Truncate a captured value at the first one of these found, same as a
# real boundary would.
_HEADLESS_MARKERS_RE = re.compile(
    r"\b(?:niveau de torrefaction|richesse aromatique|intensite du cafe|intensite)\b"
)


def _truncate_at_headless_marker(value):
    m = _HEADLESS_MARKERS_RE.search(_norm(value))
    return value[:m.start()].strip() if m else value

# Generic "<1-4 capitalized/lowercase words> :" — matches ANY label-shaped
# run, known or not, so an unrecognized label still acts as a boundary
# instead of leaking into the previous field's value. À-Þ / ß-ÿ
# cover the accented Latin-1 letters used in French.
_LABEL_RE = re.compile(
    # ":" needs no surrounding space (the common case); "/" does, since
    # unlike ":" it's also a URL and date separator with no space around it
    # in those uses — requiring space keeps a "Variété / Caturra" style
    # label without pulling in "12/03/2025" or a path.
    r"(?<!\S)([A-ZÀ-Þ][a-zß-ÿ]+(?:[ '’-][a-zß-ÿ]+){0,3})(?:\s*:\s*|\s+/\s+)"
)


def _norm(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _normalize_method(value):
    v = _norm(value)
    has_espresso = "espresso" in v
    has_filtre = "filtre" in v
    if "omni" in v or (has_espresso and has_filtre):
        return "Omni"
    if has_espresso:
        return "Espresso"
    if has_filtre:
        return "Filtre"
    return None


def extract_labeled_fields(text):
    """Returns a dict of schema fields found via 'Label : Value' pairs in
    `text`. Fields not explicitly labelled are simply absent from the dict."""
    if not text:
        return {}

    matches = list(_LABEL_RE.finditer(text))
    if not matches:
        return {}

    out = {}
    for i, m in enumerate(matches):
        field = _LABEL_TO_FIELD.get(_norm(m.group(1)))
        if not field:
            continue  # a recognized boundary, but not one we extract

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[start:end].strip(" .,;:–-")
        value = _truncate_at_headless_marker(value).strip(" .,;:–-")
        if not value:
            continue

        if field == "score":
            # Anchored to the start of the span, so safe even if trailing
            # text (there shouldn't be any now, but just in case) is noise.
            num = re.match(r"\d+(?:[.,]\d+)?", value)
            if num:
                n = float(num.group(0).replace(",", "."))
                out.setdefault("score", int(n) if n.is_integer() else n)
            continue

        if len(value) > 60 and field != "flavors":
            continue  # boundary detection still looks wrong for this span

        if field in ("acidity", "body") and not any(c.isalpha() for c in value):
            continue  # a bare "3" or "3/5" isn't a qualitative descriptor

        if field == "flavors":
            head = re.split(r"[.!]", value)[0]
            items = [v.strip() for v in re.split(r"[,•/]| et ", head) if v.strip()]
            items = [
                v.lstrip("*# ") for v in items
                if 0 < len(v) <= 30 and not any(c.isdigit() for c in v)
                and not any(m in _norm(v) for m in _SENTENCE_MARKERS)
            ]
            items = [v for v in items if v]
            if items:
                # Several labels map here (Notes/Saveurs/Profil aromatique) —
                # merge rather than let the first one found win, since a
                # product often states them in more than one place.
                existing = out.setdefault("flavors", [])
                existing.extend(v for v in items if v not in existing)
        elif field == "_method":
            method = _normalize_method(value)
            if method:
                out.setdefault("method", method)
        else:
            out.setdefault(field, value)

    return out
