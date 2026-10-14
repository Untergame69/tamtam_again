# Recherche 67f7 / ETH — résultat du 14 octobre 2026

## Décision

La tâche conclut `needs_data` : les archives étayent une association descriptive entre l’inventaire avant exécution et les fills, mais elles ne déterminent ni une politique de placement d’ordres ni un effet causal. Le calcul manquant a été réalisé hors IA. Comme des cotations ETH BBO/l2Book et des instantanés d’état du compte existent déjà localement, la prochaine action persistée est une analyse hors ligne de leur alignement avec les fills. Elle ne lance aucune collecte, aucun appel IA ni paper.

La route conserve le besoin d’observations prospectives après cette analyse locale. Pour examiner les décisions de placement, il faudrait des événements d’ordres ; ils ne sont pas archivés pour ce compte. Ce besoin ne transforme pas les motivations privées du trader en condition de recherche.

## Parcours et appels

- Tâche autorisée : `2b7bf5b9d35a8059bba6d0af645000f357d6494577ec99a8377fbff8f1a3c6f6`, paquet scellé d’empreinte `0adfcd71fcadeb56955b4daf232a7f0b64dc38bdbbe750f8105d69c9a70e4700`.
- Le premier appel a renvoyé une proposition, rejetée par le validateur car elle citait des chemins de sections JSON au lieu de références de preuves. La réponse brute et le diagnostic sont préservés. L’adaptation `eth-evidence-path-projection-v1` projette seulement les chemins explicitement reconnus vers les références présentes dans le paquet ; les chemins de politique sont écartés. Le contenu de la proposition et le paquet scellé n’ont pas été réécrits.
- La demande de calcul des distributions conditionnelles a été résolue par le calcul déterministe versionné ci-dessous. La critique autorisée, deuxième et dernier appel, a été reçue et validée. Aucun retry n’a été effectué.
- Usage cumulé : **2 appels**, **69 237 tokens d’entrée**, **3 063 de sortie**, **97 972 ms**. Les deux appels sont comptabilisés comme inclus en abonnement ; aucune réservation ou dépense USD n’a été déclarée. Les plafonds de la tâche (160 000 entrée, 10 000 sortie, 240 000 ms) restent respectés. L’enveloppe dédiée ne se renouvelle pas.
- Décision persistée : `needs_data`; promotion et rentabilité non démontrées. La route initiale est conservée dans l’historique. La nouvelle route demande d’abord un rapprochement déterministe des archives locales.

## Hypothèse examinée

**Hypothèse principale.** La part des exécutions taker et la part de quantité exécutée qui réduit l’inventaire ETH tendent à augmenter avec la taille absolue de la position avant fill. Les inversions sont coupées au passage par zéro : la quantité qui ferme l’ancienne exposition est distincte de celle qui ouvre la position opposée.

**Explication concurrente.** Les changements directionnels, le flux de marché, la liquidité et la sélection des fills peuvent produire cette association sans règle de réduction d’inventaire. Des fills ne révèlent pas les ordres non exécutés, l’intention, les annulations ou le choix initial de placement.

La critique juge le mécanisme testable comme association mais non identifié causalement. Elle demande de conserver séparément les parts pondérées par quantité et les fréquences de fills, comparer maker/taker, segment et journée, fixer le plan de comparaison et traiter les observations comme regroupées. Une absence d’augmentation de la fréquence taker opposée à la position, une inversion du résultat entre segments, ou l’attribution de l’association aux quantités d’ouverture d’inversions contredirait la prédiction forte. Même une répétition prospective ne prouverait pas la causalité sans contrôle des conditions de marché.

## Ce que montrent les archives ETH

La coupe scellée retient **23 140 fills ETH** issus de 57 pages archivées entre le 6 octobre 09:24:22 et le 11 octobre 23:29:20 UTC. Les 57 pages sont marquées incomplètes ; pagination épuisée ne prouve ni rétention exhaustive ni continuité. Le calcul local retrouve deux segments, séparés par une rupture de **106 439 824 ms** (environ 29,6 h) où la position enregistrée passe de `+2,5643` à un nouveau `startPosition` de `−3,1339`.

| Mesure | Résultat descriptif |
|---|---:|
| Fills maker (`crossed=false`) | 19 279 (83,3 %), quantité 9 848,0295 ETH |
| Fills taker (`crossed=true`) | 3 861 (16,7 %), quantité 2 996,7920 ETH |
| Frais signés archivés, maker / taker / total | −746,342482 / +1 263,373854 / +517,031372 USDC |
| Fills comparés à `startPosition` : hausse / baisse de l’exposition absolue | 11 594 / 11 546 |
| Fills d’inversion ; quantité clôturant / ouvrant l’exposition | 1 611 ; 1 227,5229 / 1 207,3045 ETH |
| Épisodes localement bornés entre inversions | 1 609 ; aucun retour exact à zéro |
| Durée d’épisode p50 / p95 / maximum | 72,959 ms / 954,300 ms / 6 240,001 ms |
| Position absolue maximale dans un épisode p50 / p95 / max | 2,3153 / 5,6071 / 10,1813 ETH |
| Taille d’un fill p50 / p95 / max | 0,1 / 2,3787 / 2,5153 ETH |

Les frais indiqués sont les montants signés présents dans les fills ; leur signe est conservé sans les transformer ici en mesure de rentabilité. Les résultats de prix des épisodes bornés sont calculés avant frais et funding. Ils totalisent **+490,84092** unités de cotation dans le segment 1 (5 970 fills, 388 épisodes) et **+1 176,08481** dans le segment 2 (17 170 fills, 1 221 épisodes). Les frais signés portés par les parts de ces épisodes sont respectivement **+89,954146** et **+425,759955 USDC**. Les montants de frais de l’ensemble des fills et les frais attribués aux épisodes restent deux mesures différentes.

| Jour UTC | Fills maker / taker | Épisodes bornés | Résultat de prix des épisodes |
|---|---:|---:|---:|
| 6 oct. | 2 792 / 444 | 205 | +138,37895 |
| 7 oct. | 2 249 / 485 | 183 | +352,46197 |
| 8 oct. | 4 123 / 1 237 | 365 | +668,21723 |
| 9 oct. | 4 200 / 1 002 | 318 | +379,21067 |
| 10 oct. | 2 722 / 212 | 226 | −70,14370 |
| 11 oct. | 3 193 / 481 | 312 | +198,80061 |

Les résultats quotidiens et par segment sont des reconstructions locales sur les épisodes bornés, pas un historique exhaustif ni des observations indépendantes. La concentration temporelle, les deux segments et les extrémités censurées limitent fortement l’inférence.

## Résolution de la prédiction par inventaire

Les seuils quartiles de la position absolue pré-fill sont 1,0494 / 1,9892 / 2,9452 ETH. De Q1 à Q4, la fraction de fills taker passe de **11,7 % à 21,0 %** pour les positions longues et de **12,9 % à 24,3 %** pour les positions courtes. La fraction de quantité taker qui ferme l’inventaire monte également : long 12,1 % → 63,5 %, short 19,6 % → 77,8 %.

La comparaison maker nuance le résultat : la part de quantité maker qui clôture monte aussi (long 18,8 % → 81,0 %, short 18,1 % → 75,1 %). En Q4, la part de clôture taker est plus faible que maker sur les longs (63,5 % contre 81,0 %) et proche sur les shorts (77,8 % contre 75,1 %). La hausse des quantités clôturées est mécaniquement favorisée par une position pré-fill plus grande ; elle ne démontre pas une règle d’agressivité. Les deux métriques doivent donc rester séparées.

Le détail complet, avec les lignes par segment, jour, côté d’inventaire, quartile, type crossed, quantité d’ouverture/clôture et frais signés, est dans [l’artefact de calcul déterministe](POPULATION-67F7-ETH-INVENTORY-ASSOCIATION-20261014.json), empreinte d’analyse `d668af00c21593ab4de006f3457c4c9b922a5f8df3fa41beda4920de73af0ee9`. Il est reproductible avec `scripts/prepare_population_inventory_association.py` et le cutoff scellé. Son empreinte de détail source est `7b3137cdf04d0fe72f01b7010924b0ad9965c5e18d3e97466f6aee5b5b5ae511`.

## Données déjà disponibles et inconnues

| Besoin | État dans les archives autorisées |
|---|---|
| Fills ETH, `startPosition`, crossed et frais réellement portés par chaque fill | Disponibles dans les pages REST archivées, avec limites de pagination et sans réception horodatée par fill. |
| BBO ETH | 484 129 observations du 2 au 12 octobre ; médiane entre réceptions 1,176 s, trou maximal 191 987 086 ms (environ 53,3 h). Le payload porte aussi son temps d’événement. |
| `l2Book` ETH | 484 670 observations sur la même période ; médiane entre réceptions 1,166 s, trou maximal 191 987 712 ms (environ 53,3 h). Les meilleures offres, prix et quantités sont donc localement calculables, mais le flux n’est pas continu. |
| Instantanés `clearinghouseState` du compte | 539 observations du 7 au 11 octobre ; écart médian 1,533 s, trou maximal 224 343 880 ms (environ 62,3 h). Ils peuvent servir à un rapprochement historique ponctuel ; ils ne certifient pas la continuité. |
| Cycle des ordres de 67f7 (soumission, ack, amendement, annulation, ordres non remplis) | Aucune ligne d’ordre archivée pour ce compte dans la coupe contrôlée. Les deux observations d’inventaire d’ordres trouvées dans cette source concernent un autre compte. Les fills ne comblent pas ce manque. |
| Heure de réception locale par fill et ordre de décision | Absents des pages REST au niveau du fill ; seule l’heure de réception de la page est conservée. Les observations WebSocket ont `observed_at` et un temps d’événement dans le payload, mais leurs grands trous doivent être rapprochés des fills avant usage. |
| Barème daté, palier et rétrocession applicable au compte | Non trouvés dans les observations archivées de ce compte. Les montants de frais réalisés dans les fills, eux, sont disponibles. |
| Motivation, cible interne et couverture de hedges externes | Inobservables dans ces archives et inutiles pour l’hypothèse limitée aux exécutions observées. |

Le paquet d’analyse IA scellé est conservé à [POPULATION-67F7-ETH-RESEARCH-PACKET-20261014.json](POPULATION-67F7-ETH-RESEARCH-PACKET-20261014.json). Il maintient ETH séparé de DRAM ; une gestion commune de l’inventaire reste possible mais n’est pas démontrée ici. La réponse brute rejetée, son diagnostic, l’adaptation, la critique validée et l’usage sont conservés dans le registre de recherche local.

## Prochain travail persisté

**Rapprocher hors ligne les fills ETH de 67f7 avec les observations BBO/l2Book et `clearinghouseState` déjà présentes**, en gardant chaque heure d’événement et de réception, en calculant l’âge et les trous autour des fills, puis en comparant les positions snapshot à la chaîne `startPosition`. Le résultat doit distinguer lignes appariées, non appariées et inconnues, sans reconstruire un ordre ou une intention. C’est la route `local_archive_analysis_required`, enregistrée après la décision `needs_data` ; aucun nouvel appel IA ou collecte n’est autorisé par cette route.

Ce rapprochement décidera si les archives locales suffisent à une étude descriptive contextuelle. Si la question est ensuite de tester une règle de placement d’ordres plutôt qu’une association entre fills observés et inventaire, il faudra préenregistrer une collecte prospective des ordres et de leurs temps locaux ; ce besoin est distinct et n’est pas activé ici. Le mécanisme n’est pas compatible avec le moteur passif actuel (files d’attente maker non simulées) ; intérêt de recherche et compatibilité moteur restent séparés.
