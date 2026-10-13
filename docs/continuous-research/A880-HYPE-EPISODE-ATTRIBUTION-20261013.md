# Attribution économique exploratoire — a880/HYPE

Analyse en lecture seule au cutoff autorisé **2026-10-12 07:16:34.195 UTC**. Elle réutilise les chaînes de position reconstruites depuis `startPosition` et les 32 921 fills uniques déjà recensés. La commande et les résultats structurés sont conservés dans [le rapport JSON reproductible](A880-HYPE-EPISODE-ECONOMICS-20261013.json) :

```sh
PYTHONPATH=src python scripts/analyze_a880_hype_episode_economics.py \
  --database data/tamtam.sqlite3 --as-of-ms 1791789394195 \
  --output docs/continuous-research/A880-HYPE-EPISODE-ECONOMICS-20261013.json
```

## Méthode et conventions

Pour chaque fill, le changement de position est `+sz` côté achat et `−sz` côté vente à partir de `startPosition`. Un passage de position positive à négative (ou l’inverse) est une **inversion** : `abs(position avant fill)` ferme l’ancienne jambe et `abs(position après fill)` ouvre la nouvelle. Le fill et son fee sont répartis entre ces jambes au prorata des quantités, au prix unique du fill. L’API ne fournit pas cette répartition; c’est une hypothèse explicite pour l’attribution.

Un épisode économiquement borné démarre à position zéro et finit soit à zéro, soit par inversion, dont la jambe de fermeture revient à zéro. Le résultat de prix est le produit des ventes moins le coût des achats. Le champ `fee` est gardé signé : un fee positif est une charge, un fee négatif une rétrocession; le calcul après frais est `résultat de prix − fee signé`. Le funding n’est ajouté que si une écriture HYPE `userFunding` avec `szi` non nul survient strictement à l’intérieur de l’épisode et si son `szi` égale exactement la dernière position reconstruite avant l’écriture. Le champ API `closedPnl` reste un contrôle séparé et n’est pas interprété comme la formule d’interface ([exemple de fill API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [documentation d’affichage](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/entry-price-and-pnl), [schéma fee/crossed](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), [funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)).

Les pages REST de fills (171) et de funding (71) sont toutes marquées incomplètes. Les épisodes sont des événements séquentiels issus d’un seul compte; ils ne sont ni indépendants ni exhaustifs. Les carnets sont joints au dernier événement BBO/l2Book **strictement antérieur** au timestamp d’événement du fill. Aucun âge maximal n’est appliqué. Cette comparaison d’horodatages n’établit pas que le collecteur avait reçu le carnet avant une décision; le décalage des horloges n’est pas connu.

## Résultat sur les 652 épisodes intérieurement bornés

Les épisodes contiennent **270 180,52 HYPE achetés et vendus**. Les achats représentent **23 118 028,93 USDC** et les ventes **23 118 022,79 USDC**, soit un résultat de prix de **−6,13 USDC**. Le champ fee signé attribué à ces épisodes vaut **−519,94 USDC** (rétrocessions nettes observées); les 82 écritures de funding effectivement attribuées totalisent **+6,22 USDC**. Le calcul exploratoire après ces deux champs est donc **+520,03 USDC**.

Le `closedPnl` API brut des fills des mêmes épisodes somme **−3,18 USDC**, proche mais distinct du résultat de prix **−6,13 USDC**. Les 32 921 fills de la chaîne entière, y compris les queues censurées, somment à **−58,18 USDC** sur ce champ. Ce rapprochement est un contrôle descriptif, pas une validation de convention ou un résultat de compte.

### Retours à zéro, inversions et frais répartis

La chaîne contient **643 fills d’inversion**. Parmi eux, 641 ferment un épisode intérieur borné et deux ferment une position déjà ouverte à la borne gauche; ils ouvrent une nouvelle position résiduelle. Les 652 épisodes intérieurs se terminent donc par **641 inversions** et seulement **11 retours à zéro**.

| `crossed` au fill d’inversion | Inversions | Quantité fermant l’ancienne position | Quantité ouvrant la nouvelle | Fee alloué à la fermeture | Fee alloué à l’ouverture |
|---|---:|---:|---:|---:|---:|
| `true` (taker selon le schéma) | 35 | 1 857,96 HYPE | 742,61 HYPE | +26,709 USDC | +10,722 USDC |
| `false` (non-crossed) | 608 | 9 386,49 HYPE | 10 519,70 HYPE | −24,095 USDC | −26,970 USDC |
| **Total** | **643** | **11 244,45 HYPE** | **11 262,31 HYPE** | **+2,614 USDC** | **−16,248 USDC** |

Le net des fees de ces inversions est **−13,634 USDC**. Les deux quantités de jambe et leurs fees somment aux champs du fill d’origine selon le prorata choisi. `crossed=true` indique un fill taker; `crossed=false` signifie qu’il n’a pas franchi le spread, sans prouver à lui seul la position dans la file ou le maker status économique.

### Résultats par segment

| Segment / bornes observées UTC | Épisodes intérieurs | Résultat de prix | Fee signé | Funding attribué | Après fee et funding | `closedPnl` API contrôle |
|---|---:|---:|---:|---:|---:|---:|
| 1 — 7 oct. 18:46 à 8 oct. 23:14 | 320 | +1 749,26 | −274,38 | +4,48 | **+2 028,13** | +1 752,22 |
| 2 — 9 oct. 15:31 à 11 oct. 23:36 | 332 | −1 755,39 | −245,56 | +1,74 | **−1 508,10** | −1 755,40 |
| **Total intérieur** | **652** | **−6,13** | **−519,94** | **+6,22** | **+520,03** | **−3,18** |

Les deux segments n’ont pas le même signe de résultat après coûts. La rupture entre eux dure **16 h 17 min 17,662 s**; la dernière position observée du premier est `+148,82 HYPE`, tandis que le `startPosition` suivant est `−45,02 HYPE`. Le delta **−193,84 HYPE** n’est attribué à aucun fill, financement ou clôture.

### Résultats par journée de clôture UTC

Les épisodes traversant minuit sont affectés au jour de leur fill de sortie; les montants d’achat/vente, frais et funding de ces épisodes suivent cette date de clôture. `closedPnl` est ici la somme brute des fills de l’épisode, distincte du relevé journalier de tous les fills.

| Jour de clôture | Épisodes | Résultat de prix | Fee signé | Funding attribué | Après fee et funding | `closedPnl` API contrôle |
|---|---:|---:|---:|---:|---:|---:|
| 7 oct. | 61 | −26,62 | −70,84 | +2,43 | **+46,65** | −26,55 |
| 8 oct. | 259 | +1 775,88 | −203,54 | +2,06 | **+1 981,48** | +1 778,78 |
| 9 oct. | 42 | +274,65 | −32,94 | +0,11 | **+307,69** | +274,81 |
| 10 oct. | 120 | −652,44 | −116,45 | +1,75 | **−534,24** | −652,96 |
| 11 oct. | 170 | −1 377,60 | −96,17 | −0,12 | **−1 281,55** | −1 377,24 |

Sur les **16 320,76 USDC** de valeur absolue des résultats nets par épisode, le plus grand épisode représente **7,33 %** et les cinq premiers **26,25 %**. La concentration journalière varie fortement : les cinq épisodes les plus importants du 11 octobre représentent 73,51 % de la somme absolue de ce jour. Ces parts décrivent une seule séquence dépendante et ne sont pas des intervalles de confiance.

### Durée et caractère crossed

| Durée observée | Épisodes | Prix | Fee signé | Funding | Après fee et funding |
|---|---:|---:|---:|---:|---:|
| < 1 min | 178 | −414,70 | +13,22 | −0,004 | −427,92 |
| 1–5 min | 237 | +1 493,54 | −124,89 | +0,99 | +1 619,42 |
| 5–30 min | 205 | −70,90 | −253,88 | +5,19 | +188,18 |
| > 30 min | 32 | −1 014,08 | −154,38 | +0,04 | −859,65 |

Les épisodes exclusivement non-crossed sont 436 : leur résultat après coûts observés est **+1 812,86 USDC** (prix +1 541,30; fee signé −270,48; funding +1,08). Les 216 épisodes mixtes totalisent **−1 292,83 USDC** (prix −1 547,43; fee signé −249,46; funding +5,14). Aucun épisode n’est exclusivement crossed/taker.

Sur les fills attribués aux épisodes, les portions taker représentent **51 475,75 HYPE** et **+735,75 USDC de fee débité**; les portions non-crossed représentent **488 885,29 HYPE** et **−1 255,68 USDC de fee signé**. Ces différences sont descriptives : elles ne séparent pas l’effet de sélection, l’ordre temporel, le prix obtenu ou les conditions de marché.

## Information ajoutée par les carnets

Les archives fournissent un quote strictement antérieur pour les **32 921 fills** et les **32 569 fills** distincts rattachés à au moins une jambe bornée; aucun n’est sans snapshot antérieur dans la plage chargée. Cela ne rend pas les snapshots vieux admissibles ni ne certifie une continuité du carnet.

| Feed | Âge médian / p95 / max | 0–100 ms | 100 ms–1 s | 1–5 s | 5–30 s | >30 s | Sans snapshot antérieur |
|---|---|---:|---:|---:|---:|---:|---:|
| BBO | 266 ms / 4 h 08 min / 6 h 21 min | 7 351 | 16 588 | 3 104 | 67 | 5 811 | 0 |
| l2Book | 356 ms / 4 h 08 min / 6 h 21 min | 3 396 | 23 684 | 22 | 8 | 5 811 | 0 |

Ces classes d’âge sont descriptives; elles ne filtrent aucun fill. Pour les quotes âgées de plus de 30 s, l’écart médian fill-vers-touch est d’environ **22 bps** pour BBO et l2Book; ces snapshots ne décrivent pas de façon fiable le carnet au fill. Dans la classe 100 ms–1 s, le p50 de l’écart au touch est environ **−0,117 bps**. Le quote antérieur est donc informatif quand récent, mais les **5 811 cas très âgés** rendent une moyenne globale trompeuse. Un quote publié avant le fill ne révèle pas non plus la réception locale ni la priorité de file.

## Financement et queues censurées

Les 71 pages `userFunding` sont incomplètes. Elles contiennent **118 écritures HYPE**, pour un total observé de **+5,57748 USDC**. **82 écritures (+6,222528 USDC)** correspondent exactement à une position reconstruite, non nulle, strictement à l’intérieur d’un épisode; **36 (−0,645048 USDC)** restent à part : 16 pendant la rupture de chaîne (+0,371230), 17 hors des segments observés (−2,059449) et 3 dans un segment sans correspondance stricte de temps/position (+1,043171). Le financement observé n’est pas complet par preuve de couverture.

Les positions ouvertes au début et à la fin de chaque segment restent des queues séparées. Les queues gauches partent de `−299,43` et `−45,02 HYPE`, puis l’ancienne position est fermée par une inversion; les queues droites restent respectivement à `+148,82` et `+164,73 HYPE`. Les flux nets de trésorerie de ces fills sont conservés dans le JSON, mais ne sont pas appelés PnL puisqu’ils incluent une inventaire initiale ou finale non valorisée. La rupture de 16 h 17 n’est pas comblée.

## Décision

**Mécanisme observable à approfondir : la captation de rétrocessions sur les fills non-crossed.** Le flux de prix des épisodes bornés est presque nul (−6,13 USDC), alors que le fee signé net apporte +519,94 USDC et le financement attribué +6,22 USDC. Les frais taker observés sont des débits (+735,75 USDC), tandis que les fees non-crossed apportent −1 255,68 USDC. C’est un mécanisme descriptif plausible derrière le résultat net positif de ces segments; les deux segments et plusieurs journées sont opposés, et les pages restent incomplètes. Ce constat ne valide pas la récurrence de ces rebates, une performance globale ou une stratégie.

Le potentiel de recherche existe pour mesurer le prix, l’âge des quotes et les fees par comportement. **Le moteur paper actuel ne reproduit pas ce mécanisme** : sa version HYPE utilise une exécution IOC et applique des frais configurés de 4,5 bps maker et taker, sans rétrocession observée ni simulation de priorité maker ([configuration v5](../../config/experiments/a880-hype-live-delta-v5.json), [runtime](../../src/tamtam_again/experimental_paper.py)). Donc la recherche est économiquement observable, mais non compatible telle quelle avec le modèle d’exécution actuel. Cette mission n’a modifié ni stratégie ni moteur; aucun paper, appel IA ou service n’a été lancé.
