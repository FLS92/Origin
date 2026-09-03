# Schéma JSON cible — Scraping des torréfacteurs (app Origin)

Ce document décrit le format que le script de scraping (à construire dans Claude Code) doit produire, pour qu'il puisse être intégré directement dans l'app Origin sans transformation manuelle.

## Structure générale

Un fichier JSON par torréfacteur, nommé `<roaster-id>.json`.

```json
{
  "roaster": {
    "id": "tanat",
    "name": "Tanat",
    "city": "Paris",
    "country": "France",
    "url": "https://tanat.coffee/",
    "domain": "tanat.coffee"
  },
  "scrapedAt": "2026-09-03T10:00:00Z",
  "products": [
    {
      "id": "tanat-rumudamo",
      "name": "Rumudamo [Natural]",
      "originCountry": "Éthiopie",
      "originDetail": "Sidama, station Rumudamo",
      "process": "Naturel",
      "variety": "74112",
      "producer": "Rumudamo Station",
      "score": 88,
      "acidity": null,
      "body": null,
      "method": "Filtre",
      "roastLevel": null,
      "flavors": ["Pêche", "Fruits Rouges", "Mangue"],
      "description": "Un lot naturel issu de la station de Rumudamo...",
      "imageUrl": null,
      "harvestYear": "2026",
      "retailers": [
        {
          "site": "Tanat",
          "url": "https://tanat.coffee/boutique/rumudamo-washed/",
          "price": 16.90,
          "currency": "EUR",
          "unitWeightG": 200,
          "priceNote": "à partir de",
          "inStock": true,
          "stockStatus": "backorder"
        }
      ],
      "available": true,
      "firstSeenAt": "2026-09-03T10:00:00Z",
      "lastSeenAt": "2026-09-03T10:00:00Z"
    }
  ]
}
```

## Conventions de champs

| Champ | Type | Notes |
|---|---|---|
| `id` | string | Préfixé par l'id du torréfacteur (`tanat-rumudamo`) pour éviter toute collision entre torréfacteurs. Stable dans le temps — ne doit jamais changer une fois attribué, même si le produit change de nom. |
| `name` | string | Nom du produit tel qu'affiché par le torréfacteur. |
| `originCountry` | string \| null | Pays d'origine du café. `null` si non trouvé (jamais une chaîne vide). |
| `originDetail` | string \| null | Région, ferme, coopérative — le complément d'info après le pays. |
| `process` | string \| null | Texte brut du torréfacteur (« Naturel », « Lavé », « Yellow Honey »...). La catégorisation (Lavé/Naturel/Honey/Anaérobie/Co-fermenté) reste calculée côté app à partir de ce texte — ne pas la précalculer ici. |
| `score` | number \| null | Score SCA si disponible. |
| `acidity` / `body` | string \| null | Descriptif qualitatif du torréfacteur, si fourni tel quel (pas de conversion en note chiffrée). |
| `method` | string \| null | Uniquement si le torréfacteur classe explicitement le produit en **Filtre / Espresso / Omni** (comme le fait Tanat). Ne pas déduire depuis `roastLevel` — laisser `null` si non fourni explicitement. |
| `roastLevel` | string \| null | Degré de torréfaction si distinct de `method` (ex. Légère/Moyenne/Foncée) — concept différent, à ne pas confondre. |
| `flavors` | array de strings \| null | Toujours un tableau, jamais une chaîne à séparateurs — c'est l'app qui les joint pour l'affichage. |
| `description` | string \| null | Paraphrase courte, jamais une copie intégrale du texte du site (contrainte de droit d'auteur). |
| `imageUrl` | string \| null | URL directe de l'image produit (pas de téléchargement local). À vérifier que le lien reste accessible en hotlink depuis l'app — sinon laisser `null` plutôt qu'un lien cassé. |
| `retailers` | array | Toujours au moins 1 entrée (le site du torréfacteur lui-même). `price` en nombre, pas en chaîne formatée. `unitWeightG` en grammes — **champ critique** : ne jamais supposer un poids par défaut (250g), toujours le lire depuis la fiche produit. |
| `available` | boolean | `false` si le produit n'apparaît plus dans le scraping le plus récent — **ne jamais supprimer un produit du fichier**, seulement basculer ce champ. |
| `firstSeenAt` / `lastSeenAt` | ISO datetime | `firstSeenAt` ne change jamais après la première écriture. `lastSeenAt` se met à jour à chaque scraping où le produit est retrouvé. |

## Logique de mise à jour (non destructive)

À chaque scraping :
1. Charger le fichier JSON existant du torréfacteur (s'il existe).
2. Pour chaque produit trouvé sur le site : mettre à jour ses champs, `lastSeenAt`, et `available: true`.
3. Pour chaque produit présent dans l'ancien fichier mais absent du nouveau scraping : conserver la fiche telle quelle, passer `available: false`. Ne jamais le supprimer — c'est ce qui permet de garder les cafés dans les bibliothèques des utilisateurs même retirés du catalogue.
4. Un nouvel `id` n'est créé que pour un produit jamais vu (pas de correspondance possible avec l'existant).

## Actualisation récurrente

Le scraping n'est pas un script à lancer une fois : il doit tourner **régulièrement** (quotidien ou hebdomadaire selon le torréfacteur) pour :
- **ajouter automatiquement** les nouvelles références publiées depuis le dernier passage (nouvel `id`, `firstSeenAt` = maintenant) ;
- **repasser `available: false`** les références qui ont disparu du site, sans jamais les supprimer du fichier.

Ce que ça implique concrètement à demander à Claude Code :
- Le script doit être **idempotent** : le relancer plusieurs fois de suite sur les mêmes données ne doit rien casser ni dupliquer.
- Il doit produire à chaque exécution un **résumé lisible** (ex. « Tanat : 3 nouvelles références, 1 passée indisponible, 42 inchangées ») pour repérer facilement un problème (site qui a changé de structure, blocage, etc.) sans avoir à comparer les fichiers JSON à la main.
- Faire tourner le script "régulièrement" veut dire l'automatiser en dehors de Claude Code lui-même : par exemple une GitHub Action planifiée (`schedule: cron`) qui exécute le script et commite les JSON mis à jour dans le repo. Claude Code peut écrire ce fichier de workflow, mais l'activation (dépôt Git, planification) reste une étape à faire une fois, à part.
- Si un torréfacteur change de plateforme ou casse le scraper existant entre deux exécutions, le script doit le signaler clairement (erreur explicite) plutôt que d'écrire un fichier JSON vide ou incomplet qui écraserait silencieusement les bonnes données précédentes.

## Ce qui reste hors scraper

- Pas de conversion de devise entre torréfacteurs.
- Pas de note communauté ni d'avis : ça reste propre à l'app (stockage séparé).
- Pas de catégorisation automatique du process ou du pays en anglais/français normalisé : laisser le texte brut, la normalisation reste dans l'app.
