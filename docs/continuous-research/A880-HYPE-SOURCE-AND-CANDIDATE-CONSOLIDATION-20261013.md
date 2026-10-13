# Analyse source et classement des candidats — 13 octobre 2026

Consolidation exploratoire en lecture seule, à partir du cutoff autorisé commun du **12 octobre 2026 à 07:16:34.195 UTC**. La sélection reste limitée aux trois comptes déjà présélectionnés dans [les fiches G2](economic-qualification-cards-20261012-g2.md). Les courbes rapportées décrivent des variations déclarées par le fournisseur : elles ne sont ni un rendement ajusté des flux ni une validation économique.

L’attribution exploratoire des épisodes a880/HYPE qui réutilise cette reconstruction est publiée dans [le rapport économique lié](A880-HYPE-EPISODE-ATTRIBUTION-20261013.md), avec ses mesures détaillées dans [l’artefact JSON](A880-HYPE-EPISODE-ECONOMICS-20261013.json).

## a880/HYPE : `closedPnl` API et frais

La documentation de l’interface décrit un `closed pnl` calculé pour l’affichage, où une ouverture ne compte que le fee et une fermeture inclut le fee et la variation de valeur. La documentation API, elle, expose `closedPnl` et `fee` comme deux champs séparés dans un objet fill; son exemple d’ouverture perpétuelle contient `closedPnl=0` avec `fee=0.01`. La convention d’affichage ne permet donc pas de réinterpréter automatiquement le champ API [`closedPnl`](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint). Le schéma WebSocket précise par ailleurs que `fee` négatif signifie une rétrocession, que `crossed` indique si le fill a franchi le spread, et que `builderFee` est déjà compris dans `fee` ([champs WsFill](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), [formule d’affichage](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/entry-price-and-pnl)).

Sur **32 921 fills HYPE uniques**, les **14 060 ouvertures** (`Open Long` et `Open Short`) ont toutes un `fee` non nul et `closedPnl=0`. Leur champ fee totalise **−300,370771 USDC**; leur somme API `closedPnl` est **0**. Pour les 32 921 lignes, les champs archivés somment séparément à `fee = −524,607450 USDC` et `closedPnl = −58,177781 USDC`. Ce sont deux mesures distinctes; faute de contrat API documentant leur relation, le rapport ne les additionne ni ne les compense. Les lignes de frais observées sont en USDC et aucun `builderFee` distinct n’est présent dans ces fills. Les soldes de frais négatifs représentent des rebates selon le schéma, pas un crédit extrapolable à d’autres tailles ou périodes.

## a880/HYPE : cohérence `startPosition` et limites

La séquence a été dédupliquée par `tid`, puis ordonnée par les transitions de position à l’intérieur des groupes de fills au même timestamp. Les **32 921 fills contiennent `startPosition`**. Parmi les **25 549 groupes temporels**, 4 072 contiennent plusieurs fills (11 444 fills au total); aucune transition de ces groupes n’est ambiguë ou invalide. **25 547 des 25 548 raccords entre groupes successifs** sont cohérents.

La seule rupture sépare deux segments et n’est pas comblée :

| Segment | Période UTC | Fills | Position au début → à la fin | Limites |
|---|---|---:|---:|---|
| 1 | 7 oct. 18:46:06 → 8 oct. 23:14:06 | 17 876 | −299,43 → +148,82 HYPE | début et fin censurés |
| 2 | 9 oct. 15:31:24 → 11 oct. 23:36:48 | 15 045 | −45,02 → +164,73 HYPE | début et fin censurés |

Entre ces segments : **16 h 17 min 17,662 s** sans chaîne observée, avec un écart arithmétique de **−193,84 HYPE** entre la fin précédente et le `startPosition` suivant. Cet écart est une rupture de couverture/cohérence; il ne représente pas une clôture ou un mouvement expliqué.

À l’intérieur des segments seulement, **652 épisodes localement reconstructibles flat-à-flat** ont une durée médiane de **2 min 56 s**, un p95 de **29 min 48 s** et un maximum de **5 h 05 min 34 s**. Ce résultat améliore la datation locale que ne permettaient pas les snapshots clairsemés. Il ne transforme pas les épisodes en historique exhaustif : toutes les pages REST `userFillsByTime` utilisées sont marquées incomplètes (170 pages, plusieurs au plafond de 2 000 lignes), et les segments commencent et finissent avec une position non nulle. La couverture de rétention, les fills absents et le contenu de l’intervalle de rupture restent inconnus.

Les traces sources sont dans `raw_observations` : fills REST `userFillsByTime` ids **10174802–26002582** (170 pages incomplètes) et `userFills` id **12389413** (page incomplète). L’analyse reproductible calcule les transitions à partir des champs archivés :

```sh
PYTHONPATH=src python scripts/analyze_a880_hype.py \
  --database data/tamtam.sqlite3 --as-of-ms 1791789394195 \
  --output /tmp/a880-analysis-oct12.json
```

Les mesures structurées et les références de couverture sont conservées dans [l’artefact d’analyse `startPosition` v1](A880-HYPE-START-POSITION-CONSOLIDATION-20261013.json). Le [rapport a880 précédent](A880-HYPE-ACCOUNT-BEHAVIOR-20261013.md) est préservé et renvoie à ce rectificatif; ses deux affirmations sur `closedPnl` et les épisodes complets sont remplacées par les précisions ci-dessus.

## Même grille pour les trois candidats

Les horizons sont les deltas de `allTime.pnlHistory` aux points disponibles les plus proches des fenêtres visées (environ 32, 95 et 186 jours). L’activité est celle des pages fills effectivement archivées, pas une extrapolation à la période des courbes. La compatibilité ci-dessous est une possibilité d’observation avec les feeds BBO/l2Book déjà archivés; elle ne préjuge ni du comportement causal réel ni de la rentabilité.

| Rang de recherche | Variation déclarée 30 / 90 / 180 j (USDC) | Activité et couverture fills | Compatibilité potentielle avec notre exécution |
|---|---|---|---|
| **1 — `a880…4ee` (HYPE parmi 18 marchés)** | +16 094,87 / +56 403,54 / +128 249,47 | 178 438 fills; 5 jours actifs; 3,504 jours contigus couverts; 121 pages et plafond de collecte atteint. | HYPE standard a 458 570 observations BBO et 459 211 l2Book du 2 au 12 oct. Les contrôles et le runtime paper actifs ciblent HYPE ([`experimental_paper.py`](../../src/tamtam_again/experimental_paper.py)); c’est donc le seul candidat directement comparable à l’exécution actuelle. Les fills sont très denses, les pages incomplètes, et les deux segments ont des extrémités censurées. Son historique de travail antérieur n’entre pas dans le rang. |
| **2 — `67f7…9ba` (ETH, `xyz:DRAM`)** | −79,75 / +9 210,55 / +36 304,35 | 25 601 fills; 6 jours actifs; 4,661 jours contigus couverts; 55 pages, arrêt `page_budget_exhausted`; 2 marchés. | Les archives contiennent 484 129 observations BBO et 484 670 l2Book pour ETH du 2 au 12 oct.; `xyz:DRAM` dispose aussi des deux feeds. Mais le runtime paper actuel valide HYPE explicitement, donc une exécution ETH n’est pas directement établie dans cette version. Compatibilité réelle avec DRAM non établie. |
| **3 — `be504…77b` (mode `portfolioMargin`)** | +193 867,76 / +266 983,24 / +365 968,59 | 891 fills; 5 jours actifs; 4,964 jours contigus; 9 marchés. Les pages ont atteint la fin de pagination, mais la rétention n’est pas démontrée. Trois des six mois mesurés sont négatifs. | Le compte utilise sous-compte et marchés `xyz:`/`para:`; transferts et funding apparaissent en unités/scopes multiples. Des feeds existent pour plusieurs marchés mais la portée du moteur et la consolidation de portefeuille restent incertaines. C’est le candidat le plus coûteux à comparer proprement. |

Toutes les courbes sont fournisseur-déclarées. Pour `67f7`, la fenêtre 30 j est légèrement négative et les fenêtres 90/180 j positives; cela rend la différence d’horizon observable et testable sans supposer que les signaux refusés auraient gagné. Pour `a880`, la courbe déclarée est la plus régulièrement positive, mais les pages de fills sont fortement tronquées et ne couvrent que 3,5 jours. Pour `be504`, les plus grands gains déclarés coexistent avec des mois négatifs, de fortes baisses échantillonnées et un périmètre à plusieurs comptes/marchés. Aucun candidat n’a ici un rendement net consolidé validé.

## Décision

**Priorité de recherche : `a880…4ee`, pour une étude étroite de comparabilité d’exécution sur HYPE.** Ce rang découle du support HYPE explicite de la version active du runtime et des feeds historiques existants, pas des travaux antérieurs sur le compte. C’est un choix de comparabilité technique, pas une préférence économique : l’archive des fills est incomplète, elle n’observe que 3,504 jours, et les deux épisodes bornés ont des positions non nulles à leurs extrémités. `67f7…9ba` arrive deuxième : ses six jours actifs, 4,661 jours contigus et le marché standard ETH en font le meilleur candidat pour une future étude séparée si le périmètre d’exécution l’autorise; sa courbe 30 jours est négative.

Question précise : **dans chacun des deux segments continus HYPE de `a880…4ee`, quelle part des fills peut être appariée à un BBO/l2Book antérieur de moins d’une seconde selon les timestamps d’événement, et comment prix d’exécution, `crossed` et `fee` se répartissent-ils entre les 652 épisodes localement reconstructibles et les fills sans attribution d’épisode ?** Cette jointure de timestamps ne prouverait pas que le collecteur avait reçu le carnet avant une décision : le décalage entre horloges collecteur et événement n’est pas établi. L’analyse doit afficher les bornes censurées et la rupture séparément; elle ne doit ni combler les 16 h 17 min ni extrapoler aux pages absentes. Elle mesurerait la comparabilité observable des fills présents, pas le résultat du compte ni la validité de sa courbe.

`be504` reste troisième en raison du mode portfolio-margin, des sous-comptes, des devises et du mélange d’instruments. **Aucun des trois n’est exploitable actuellement pour conclure à une performance économique nette ou déclencher une expérience paper.** Le rang a880 autorise seulement cette comparaison historique limitée avec le runtime HYPE existant. Aucun lancement, collecte, appel IA ou changement de service n’est réalisé dans cette consolidation.
