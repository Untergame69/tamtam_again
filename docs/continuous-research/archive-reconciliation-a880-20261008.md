# Rapprochement d'archives — a880…4ee

**Statut : rapprochement partiel reproductible sur un intervalle, pas validation économique globale.** Données locales arrêtées au cutoff commun `1791789394195` (`2026-10-12T07:16:34.195Z`). La lecture SQLite est en `mode=ro`; le contrôle d'accès à l'historique et des comptes protégés est exécuté avant le décodage des réponses.

## Choix de l'intervalle

Règle de choix : retenir le plus court intervalle d'archives où les deux séries `allTime.pnlHistory` et `allTime.accountValueHistory` ont une valeur observée à chaque borne, où les snapshots standard perp correspondent aux acquisitions des bornes, et où les pages ledger/funding archivées chevauchent la fenêtre. Cela choisit **2026-10-08 15:24:45.724 → 16:17:15.515 UTC** (52 min 29,791 s), avec bornes curve issues respectivement de `raw_observations:12391756` et `raw_observations:12392336`.

Le choix utilise une fenêtre étroite autour d'un transfert observé et de bornes curve disponibles; il ne signifie pas que toutes les pages d'événements sont exhaustives. L'événement `−12 000 USDC` du 7 octobre (`raw_observations:10176394`) est antérieur et donc exclu. Un second transfert de `−11 000 USDC` survient dans la fenêtre.

## Courbes et flux

| Mesure | Début | Fin | Variation |
|---|---:|---:|---:|
| `allTime.pnlHistory` déclaré | 552 382,257798 | 556 308,453586 | **+3 926,195788 USDC** |
| `allTime.accountValueHistory` | 233 473,459731 | 226 559,335426 | **−6 914,124305 USDC** |

La différence `ΔPnL − ΔaccountValue` est **+10 840,320093 USDC**. La page `userNonFundingLedgerUpdates`, référence `raw_observations:12392352`, contient un événement `send` à `15:28:15.207Z` : `−11 000 USDC` pour cette adresse, fee et native fee à zéro. Il est externe à la frontière de cette adresse; le lien économique entre l'adresse destination et un éventuel compte lié est inconnu. La requête archivée couvre `1791460222588–1791476243872`, inclut les deux bornes de l'intervalle, mais `complete=0` et `pagination_only_retention_unknown` interdisent de considérer la réponse comme preuve d'exhaustivité historique.

Pour montrer l'effet de signe sans imposer une convention non vérifiée, le pont arithmétique conditionnel est : `ΔPnL = ΔaccountValue − flux externe signé` (un retrait est négatif). Il donne `−6 914,124305 − (−11 000) = +4 085,875695 USDC`, contre `+3 926,195788` déclaré, soit un **résidu conditionnel de −159,679907 USDC**. Sous cette convention, le retrait explique environ `+11 000 USDC` de la différence brute et en explique la majeure partie. Ce montant n'est pas présenté comme une attribution certifiée : la couverture ledger reste inconnue et l'API ne confirme pas l'appartenance de la destination à la même entité économique.

## Frais, funding et positions observés

- **Fills/fees :** 6 957 fills uniques dédupliqués par `(coin,time,tid-or-hash)` dans la fenêtre; fees observées `+387,231866 USDC`. Les quatre pages qui portent des événements de l'intervalle sont `raw_observations:12393535`, `12393536`, `12483045`, `12483598`; chacune contient 2 000 lignes, `complete=0` et `page_budget_exhausted`. Ce total est donc un sous-total archivé, pas une somme garantie complète.
- **Funding :** 18 événements normalisés, `−0,410559 USDC`, dans `raw_observations:12392351`; la requête chevauche les deux bornes, retourne 54 lignes et est marquée `complete=0`, `pagination_exhausted`, rétention inconnue. Les instruments observés n'ont pas de préfixe DEX; la couverture complète et le périmètre historique ne sont pas prouvés.
- **Positions standard perp :** les snapshots d'acquisition liés aux bornes sont observés 3,076 s après la borne de début (`raw_observations:12391758`) et 4,930 s après celle de fin (`raw_observations:12392338`). Ils montrent 18 positions aux deux moments. La somme brute des champs `positionValue` passe de `579 772,164170` à `25 859,447789`; la somme des `unrealizedPnl` passe de `+1 188,796753` à `+38,901463`. Ce sont des instantanés du DEX perp standard, pas une equity consolidée ni une PnL à ajouter à la courbe.

| Coin | `szi` début | `szi` fin |
|---|---:|---:|
| 0G | −3 114 | 177 |
| ADA | −910 | 6 836 |
| ALGO | 2 853 | −1 700 |
| APT | 6 748,07 | 3 042,29 |
| AR | −1 204,42 | 136,06 |
| DOT | −1 296,1 | 3 031,2 |
| HYPE | 5 038,12 | −16,53 |
| MET | 2 659 | 1 103 |
| MORPHO | −1 210,8 | 548,5 |
| NEAR | −11 521,3 | −478,8 |
| POL | 6 319 | 8 546 |
| PUMP | −1 208 584 | 93 854 |
| SEI | 22 206 | 4 480 |
| SOPH | 45 656 | −12 872 |
| SPX | −513,5 | 1 910,2 |
| TRUMP | 8 455 | 1 407,3 |
| TRX | −1 028 | −255 |
| ZEC | −52,82 | 6,9 |

## Inclusion des coûts dans la courbe et prévention du double comptage

La documentation Hyperliquid décrit `accountValue` comme comprenant le PnL latent des positions cross/isolated et les soldes vault; elle décrit la courbe PnL comme dérivée de la valeur de compte et des dépôts/retraits, échantillonnée sur les mouvements et toutes les quinze minutes. L'API ne fournit pas de ventilation reliant chaque fee ou funding de cette fenêtre à chacun des points `pnlHistory`. L'interprétation prudente est donc que les frais/funding réglés sont déjà reflétés dans la valeur de compte si leur impact y est comptabilisé; ils restent affichés séparément et **ne sont pas déduits une seconde fois**. Cette inclusion par événement n'est pas prouvée par ces pages. Les états d'unrealized PnL ne sont pas ajoutés à la courbe.

L'API des fills précise que `fee` est le total, builder fee comprise; `builderFee` n'est donc pas ajouté séparément. La formule de la courbe est documentée, mais son signe ne remplace pas le rapprochement des flux signés de cette adresse et de la couverture réelle des pages. [Graphiques de portefeuille](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs) · [Info endpoint et limites des fills](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint).

## Inconnues et action minimale

- La page des fills est explicitement épuisée par budget. L'API limite `userFillsByTime` à 2 000 résultats par réponse et aux 10 000 fills les plus récents; les 6 957 observations de cette fenêtre ne prouvent donc pas qu'aucun fill n'a manqué. Au débit observé, le lot des 10 000 derniers fills peut couvrir seulement quelques heures. Une récupération rétroactive fiable de cet intervalle n'est pas garantie.
- Les pages funding et ledger marquent `complete=0`; aucune absence d'événement ne vaut zéro. Le transfert vers l'adresse destination est externalisé à la frontière a880, sans preuve d'indépendance économique.
- Les positions comparent seulement le DEX standard à deux instants. Spot valorisé, vaults, autres adresses, et toute période entre snapshots ne sont pas consolidés.
- La somme de `387,231866 USDC` de fees et le funding de `−0,410559 USDC` sont des observations séparées, pas une preuve qu'ils expliquent le résidu de `−159,679907`.

Pour fermer ce test de mécanisme à l'avenir, la collecte minimale distincte serait un intervalle **prospectif** comparable : les deux snapshots `portfolio` et `clearinghouseState` aux bornes, plus `userFillsByTime`, `userFunding` et `userNonFundingLedgerUpdates` archivés en tranches de cinq minutes avec curseurs continus, comptes de pages et statut complet explicites. Cinq minutes restent sous 2 000 fills par réponse au débit observé, avec marge; les pics restent à surveiller. **Aucune collecte n'a été lancée dans ce lot.** L'intervalle historique du 8 octobre peut ne plus être récupérable via la rétention des 10 000 derniers fills.

## Reproduction

Depuis la racine du dépôt, en lecture seule :

```sh
python scripts/archive-account-reconcile.py \
  --db data/tamtam.sqlite3 \
  --archive-audit docs/continuous-research/economic-performance-archive-check-20261012.json \
  --start-ms 1791473085724 \
  --end-ms 1791476235515 \
  --output docs/continuous-research/archive-reconciliation-a880-20261008.json
```

L'artefact JSON contient les valeurs exactes, références, montants normalisés, bornes des requêtes et statuts de couverture. Il est dérivé uniquement des pages locales référencées; il ne contacte aucun fournisseur.
