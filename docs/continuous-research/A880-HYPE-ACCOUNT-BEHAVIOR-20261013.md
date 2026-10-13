# a880/HYPE — comportement observable du compte

Analyse exploratoire, arrêtée à l’archive autorisée du **13 octobre 2026 à 10:02:11.701 UTC**. Reproduction en lecture seule :

```sh
PYTHONPATH=src python scripts/analyze_a880_hype.py \
  --database data/tamtam.sqlite3 --as-of-ms 1791885731701 \
  --output docs/continuous-research/A880-HYPE-ACCOUNT-BEHAVIOR-20261013.json
```

Le script vérifie la libération de l’historique avant de décoder les observations. Aucune collecte, expérience ou décision paper n’a été lancée.

## Adaptation de la réponse IA conservée

La réponse fournisseur de la tâche `3104a45166193c26e56e33a55011b7de6c553807373f764dea5acb73d303533f` reste intacte et rejetée. L’adaptateur `copy-exact-object-to-root-v1` copie l’objet existant `diagnostic.hypothesis` dans le champ racine requis ; aucun champ ni valeur n’est créé ou réécrit. L’empreinte de la réponse source reste `a4bc436f121726cf38f0da0ea0238c5a59b91cd67d5dce2f16d234b09329d5`.

La revalidation hors ligne dépasse maintenant l’erreur de forme initiale, puis échoue sur `evidence_reference_invalid` dans `hypothesis.evidence_refs`. Plusieurs références données par la réponse ne sont pas dans la liste autorisée du paquet, dont `paper_experimental_sessions:…` et `raw_observations:36711853..36927113`. Aucune référence n’a été normalisée ou remplacée. Le validateur étant à arrêt sur première erreur, les contrôles suivants — champs non vides, types de `required_data` et compilation — restent non exécutés et inconnus. L’adaptation est classée **diagnostic de notre exécution**, non recherche validée, et n’est pas promue. L’artefact versionné contient la réponse adaptée, les deux diagnostics, les empreintes et la liste des validations non atteintes : [adaptation v1](V5-REJECTED-RESPONSE-ADAPTATION-20261013.json).

## Fills, rythme et frais

L’archive contient **32 921 fills HYPE uniques** du 7 octobre 18:46 au 11 octobre 23:36 UTC. Les 170 pages REST sont toutes marquées incomplètes; plusieurs ont atteint 2 000 lignes. La rétention, l’absence de pages manquantes et les périodes sans exécution restent indémontrées.

| Mesure des fills archivés | Achats | Ventes |
|---|---:|---:|
| Nombre | 13 930 | 18 991 |
| Quantité HYPE absolue | 271 498,76 | 270 840,76 |
| Notionnel observé | 23,232 M USDC | 23,175 M USDC |

La somme signée des tailles observées est `+658 HYPE`; ce n’est pas une position ni un rendement : l’inventaire initial et la complétude de la séquence ne sont pas établis. La taille médiane d’un fill est 2,16 HYPE, le 95e percentile 82,49 et le maximum 808,92. L’intervalle médian entre fills observés est 2,012 s, le 95e percentile 42,928 s; le maximum atteint 16 h 17 min, avec un seul trou supérieur à une heure. Ces rythmes agrègent des pages incomplètes et ne décrivent pas la continuité du marché.

Sur ces fills, le champ `fee` totalise **−524,60745 USDC** : 1 538 fills `crossed=true` portent +736,137691 USDC, tandis que 31 383 `crossed=false` portent −1 260,745141 USDC. Le schéma officiel définit `crossed` comme le franchissement du spread (taker ou non) et les frais négatifs comme des rebates. C’est donc un crédit net observé dans ces pages, pas une estimation de la tarification future ni une preuve de stratégie rentable. Aucun champ `builderFee` séparé n’est renseigné. Le `closedPnl` archivé somme −58,177781 USDC; selon la définition officielle par fill il inclut le fee (pour une ouverture, le champ est seulement le fee). Il ne faut donc pas soustraire à nouveau le total `fee`, ni traiter ce sous-total incomplet comme le résultat du compte.

## Positions et résultat observable

Les 852 snapshots `clearinghouseState` montrent HYPE non nul dans 79 observations, chaque fois dans une séquence d’un seul snapshot non nul. La cadence est en rafales : le p50 entre observations est 1,537 s, mais le p95 est 61,45 min et le maximum 25,34 h. Ces points prouvent l’exposition aux instants observés; ils ne permettent pas de dater les entrées/sorties entre snapshots. Les pages de fills étant incomplètes, **aucune durée exacte d’épisode de position n’est reconstructible**. Le sous-total `closedPnl` et les états échantillonnés ne forment pas une performance consolidée.

La v5 paper reste une expérience distincte et incomplète, censurée avec `−0,61 HYPE` et un ordre de réduction en attente. Ses liens causaux historiques ne sont pas recherchés à nouveau et sa position n’est pas interprétée comme une position du compte source.

## Décision de recherche

**Poursuivre le suivi descriptif du compte et de HYPE; ne pas engager maintenant l’étude d’un mécanisme autonome.** Le volume et la répartition fee/rebate distinguent clairement le comportement observé, mais la couverture incomplète, l’inventaire initial inconnu et l’impossibilité de dater les épisodes empêchent d’expliquer le comportement par une règle ou un résultat économique. Le prochain usage de ces archives peut rester descriptif; il n’est pas nécessaire de produire une nouvelle stratégie. Aucun nouveau travail de collecte n’est lancé ici.

Références de schéma officielles : [Info endpoint / fills](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [Subscriptions / champs `crossed` et `fee`](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), [Fees / rebates maker](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Entry price and PnL / `closedPnl`](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/entry-price-and-pnl).
