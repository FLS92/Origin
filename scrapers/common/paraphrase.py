"""Short paraphrase of a roaster's raw product text via the Anthropic API.

Only called once per product, the first time it is seen (see schema.apply_products) —
never re-run on every scrape, to keep this idempotent and cheap. Requires
ANTHROPIC_API_KEY in the environment; if absent, returns None rather than failing
the whole scrape (a missing description is schema-valid, a crashed run is not).
"""
import os
import re

_MODEL = "claude-haiku-4-5-20251001"
_client = None


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
    text = re.sub(r"\s+", " ", text).strip()
    return text


def paraphrase(product_name, raw_html):
    """Returns a short French paraphrase (1-2 sentences), or None if unavailable."""
    text = strip_html(raw_html)
    if not text:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    "Reformule ce texte marketing d'un café en une paraphrase courte "
                    "(1 à 2 phrases, en français), factuelle, sans reprendre les tournures "
                    "originales ni copier des phrases entières. Ne mentionne pas que c'est "
                    "une reformulation, donne juste le résultat.\n\n"
                    f"Produit : {product_name}\n\nTexte original :\n{text[:1500]}"
                ),
            }],
        )
        out = "".join(block.text for block in resp.content if block.type == "text").strip()
        return out or None
    except Exception:
        return None
