# Origin — Scrapers torréfacteurs

Scrapers produisant, pour chaque torréfacteur listé dans `config/roasters.json`,
un fichier `data/<id>.json` conforme à [`docs/schema-scraping-origin.md`](docs/schema-scraping-origin.md).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`ANTHROPIC_API_KEY` (optionnel) : si présente dans l'environnement, le champ
`description` de chaque **nouveau** produit est reformulé via l'API Anthropic
(courte paraphrase, jamais une copie du texte du site — voir
`scrapers/common/paraphrase.py`). Sans clé, `description` reste `null`. Les
produits déjà connus ne sont jamais re-paraphrasés (coût et idempotence).

## Lancer un scraping

```bash
python3 run.py                  # tous les torréfacteurs scrapables
python3 run.py tanat-coffee lomi  # un ou plusieurs, par id
```

Affiche un résumé par torréfacteur (nouvelles références / mises à jour /
passées indisponibles / inchangées) et met à jour `data/<id>.json` de façon
non destructive : un produit disparu du site passe `available: false` mais
n'est jamais supprimé du fichier.

## Automatisation

`.github/workflows/scrape.yml` lance `run.py` chaque lundi et commite les
JSON mis à jour. Ajouter le secret `ANTHROPIC_API_KEY` au repo GitHub pour
activer la génération de description.

## Architecture

- `config/roasters.json` — un torréfacteur par entrée : id, nom, ville, url,
  domaine, plateforme détectée.
- `scrapers/common/` — logique partagée (fusion/écriture JSON, HTTP, parsing,
  paraphrase).
- `scrapers/<plateforme>.py` — un module par plateforme e-commerce
  (`shopify`, `woocommerce`, `prestashop`, `odoo`, `squarespace`, `wizishop`,
  `magento`), plus `lomi.py`, cas particulier (Next.js + backend Swell).
- `run.py` — orchestrateur : lit la config, appelle le bon scraper par
  torréfacteur, imprime le résumé.

## Plateformes détectées (95 torréfacteurs)

| Plateforme | Nb sites | Scraper |
|---|---|---|
| WooCommerce | 30 | `scrapers/woocommerce.py` — API publique `/wp-json/wc/store/v1/products` |
| Shopify | 26 | `scrapers/shopify.py` — API publique `/products.json` |
| PrestaShop | 8 | `scrapers/prestashop.py` — parsing HTML (pas d'API publique sans clé webservice) |
| Odoo | 3 | `scrapers/odoo.py` — parsing HTML des pages `/shop` |
| Squarespace | 2 | `scrapers/squarespace.py` — `?format=json` sur la page boutique |
| Wizishop | 2 | `scrapers/wizishop.py` — parsing HTML |
| Magento | 1 | `scrapers/magento.py` (Cime — écrit spécifiquement pour son thème, qui expose pays/variété/producteur/notes en clair) |
| Custom (Swell/Next.js) | 1 | `scrapers/lomi.py` (Lomi — lit le JSON `__NEXT_DATA__` embarqué dans la page) |
| **Total scrapable** | **73** | |

Pour WooCommerce, Shopify et Magento, les produits sont filtrés pour ne
garder que la catégorie café (les machines/accessoires/thés du même
catalogue sont exclus) via une liste de labels connus ; si aucune catégorie
ne correspond sur un site donné, tous les produits sont gardés plutôt que
d'en perdre silencieusement.

Champs enrichis automatiquement quand la plateforme les expose en clair
(WooCommerce : attributs `Producteur`/`Variété`/`Process`/`Score`/`Torréfaction`
si présents ; Magento (Cime) : panneau `Pays`/`Variété`/`Plantation`/`Notes
aromatiques`) — sinon laissés à `null`, jamais devinés à partir de texte
libre, conformément au schéma.

## 22 torréfacteurs non scrapés

Voir le champ `notes` de chaque entrée dans `config/roasters.json` (`platform`
≠ une des valeurs ci-dessus). Raisons : pas de site/boutique en ligne trouvé
(10), site inaccessible en HTTP simple — TLS cassé ou expiré (2), protection
anti-bot bloquant toute requête (2), site Wix rendu en JS côté client sans
API exploitable (2), boutique PrestaShop réservée aux comptes pro (1),
boutique Shopify actuellement gelée/indisponible (1), vente uniquement via
une marketplace tierce plutôt que le site du torréfacteur (1), page-builder
statique sans structure de données exploitable (1), doublon d'un autre
torréfacteur de la liste — Kawa a été rebrandé en Tanat Coffee (1).
