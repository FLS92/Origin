"""Paraphrase + structured-field extraction from a roaster's raw product text,
via the Anthropic API — one call does both, since they're the same read of
the same paragraph.

Only called once per product, the first time it is seen (see schema.apply_products)
— never re-run on every scrape, to keep this idempotent and cheap. Requires
ANTHROPIC_API_KEY in the environment; if absent, returns {} rather than failing
the whole scrape (missing fields are schema-valid, a crashed run is not).

Extraction is instructed to report only what the roaster's own text states
explicitly — never to infer or guess — matching the schema's own rule that a
field like `process` or `method` must reflect the source, not a computed
categorization. A platform's own structured data (a WooCommerce attribute, a
Magento hover-panel) is applied before this and takes precedence: this only
fills what that didn't find.
"""
import html
import json
import os
import re

_MODEL = "claude-haiku-4-5-20251001"
_client = None

_FIELDS = [
    "originCountry", "originDetail", "process", "variety", "producer",
    "score", "acidity", "body", "method", "roastLevel", "flavors", "harvestYear",
]

_PROMPT = """Tu lis la fiche produit d'un café vendu par un torréfacteur. À partir du texte fourni, renvoie un objet JSON avec exactement ces clés :

- originCountry: pays d'origine du café (string ou null)
- originDetail: région/ferme/coopérative/station si mentionné, en plus du pays (string ou null)
- process: texte brut décrivant le traitement post-récolte tel qu'écrit par le torréfacteur, ex. "Lavé", "Naturel", "Honey", "Anaérobie" (string ou null)
- variety: variété(s) botanique(s) du café, ex. "Caturra", "Geisha" (string ou null)
- producer: nom du producteur/de la ferme/coopérative (string ou null)
- score: score SCA/cupping si un nombre est donné explicitement (number ou null)
- acidity: descriptif qualitatif de l'acidité SI le texte le qualifie explicitement, ex. "Vive", "Faible" (string ou null)
- body: descriptif qualitatif du corps SI qualifié explicitement, ex. "Soyeux", "Rond" (string ou null)
- method: UNIQUEMENT si le torréfacteur classe explicitement ce café en "Filtre", "Espresso" ou "Omni" (string ou null, une seule de ces 3 valeurs)
- roastLevel: degré de torréfaction SI mentionné explicitement, ex. "Légère", "Moyenne", "Foncée", "French Roast" (string ou null)
- flavors: liste des notes aromatiques mentionnées, ex. ["Pêche", "Jasmin"] (array de strings ou null)
- harvestYear: année de récolte si mentionnée (string ou null)
- description: une paraphrase courte (1 à 2 phrases, en français), factuelle, qui NE reprend PAS les tournures ni les phrases du texte original — jamais une copie (string, jamais null : si le texte ne dit rien de particulier, résume ce qu'il y a en 1 phrase générique)

Règle stricte : ne déduis, n'invente et ne complète RIEN. Si une information n'est pas explicitement écrite dans le texte, la valeur est null (pas une supposition, pas une valeur par défaut). Réponds uniquement avec le JSON, sans texte autour.

Produit : {name}

Texte original :
{text}"""

_EMPTY = {}


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    _client = anthropic.Anthropic(api_key=api_key)
    return _client


def strip_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def analyze_product(product_name, raw_html):
    """Returns a dict with a `description` string plus any of _FIELDS the
    source text explicitly states — missing/unstated fields are simply
    absent from the dict (never a guessed value). Returns {} if there's no
    text to read or no API key configured."""
    text = strip_html(raw_html)
    if not text:
        return dict(_EMPTY)
    client = _get_client()
    if client is None:
        return dict(_EMPTY)
    try:
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(name=product_name, text=text[:2000]),
            }],
        )
        raw = "".join(block.text for block in resp.content if block.type == "text").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
    except Exception:
        return dict(_EMPTY)

    out = {}
    if isinstance(data.get("description"), str) and data["description"].strip():
        out["description"] = data["description"].strip()
    for field in _FIELDS:
        value = data.get(field)
        if value in (None, "", []):
            continue
        out[field] = value
    return out
