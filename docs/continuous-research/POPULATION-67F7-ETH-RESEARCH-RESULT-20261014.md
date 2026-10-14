# Recherche 67f7 / ETH — résultat du 14 octobre 2026

## Décision

La décision IA reste `needs_data` : les archives étayent une association descriptive entre l’inventaire avant exécution et les fills, mais elles ne déterminent ni une politique de placement d’ordres ni un effet causal. La résolution locale demandée a maintenant été exécutée sans IA. La route persistée est `local_archive_analysis_complete` ; elle n’active aucune collecte, aucun appel IA ni paper.

La route conserve le besoin d’observations prospectives après cette analyse locale. Pour examiner les décisions de placement, il faudrait des événements d’ordres ; ils ne sont pas archivés pour ce compte. Ce besoin ne transforme pas les motivations privées du trader en condition de recherche.

## Parcours et appels

- Tâche autorisée : `2b7bf5b9d35a8059bba6d0af645000f357d6494577ec99a8377fbff8f1a3c6f6`, paquet scellé d’empreinte `0adfcd71fcadeb56955b4daf232a7f0b64dc38bdbbe750f8105d69c9a70e4700`.
- Le premier appel a renvoyé une proposition, rejetée par le validateur car elle citait des chemins de sections JSON au lieu de références de preuves. La réponse brute et le diagnostic sont préservés. L’adaptation `eth-evidence-path-projection-v1` projette seulement les chemins explicitement reconnus vers les références présentes dans le paquet ; les chemins de politique sont écartés. Le contenu de la proposition et le paquet scellé n’ont pas été réécrits.
- La demande de calcul des distributions conditionnelles a été résolue par le calcul déterministe versionné ci-dessous. La critique autorisée, deuxième et dernier appel, a été reçue et validée. Aucun retry n’a été effectué.
- Usage cumulé : **2 appels**, **69 237 tokens d’entrée**, **3 063 de sortie**, **97 972 ms**. Les deux appels sont comptabilisés comme inclus en abonnement ; aucune réservation ou dépense USD n’a été déclarée. Les plafonds de la tâche (160 000 entrée, 10 000 sortie, 240 000 ms) restent respectés. L’enveloppe dédiée ne se renouvelle pas.
- Décision IA persistée : `needs_data`; promotion et rentabilité non démontrées. La route initiale reste conservée dans l’historique ; la route ultérieure lie la demande au résultat local v2.

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
| Durée d’épisode p50 / p95 / maximum | 1 min 12,959 s / 15 min 54,300 s / 1 h 44 min 0,001 s |
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
| BBO ETH | 484 129 lots archivés du 2 au 12 octobre ; leur écart de réception médian est 1,176 s et le maximum 191 987 086 ms (environ 53,3 h). Les lots contiennent 3 230 899 événements en v3 ; le trou événementiel maximal dans les jours/segments des fills est 11 331 436 ms. |
| `l2Book` ETH | 484 670 lots archivés sur la même période ; leur écart de réception médian est 1,166 s et le maximum 191 987 712 ms (environ 53,3 h). Les lots contiennent 1 135 567 événements en v3 ; le trou événementiel maximal dans les jours/segments des fills est 11 331 767 ms. |
| Instantanés `clearinghouseState` du compte | 539 observations du 7 au 11 octobre ; écart médian 1,533 s, trou maximal 224 343 880 ms (environ 62,3 h). Ils peuvent servir à un rapprochement historique ponctuel ; ils ne certifient pas la continuité. |
| Cycle des ordres de 67f7 (soumission, ack, amendement, annulation, ordres non remplis) | Aucune ligne d’ordre archivée pour ce compte dans la coupe contrôlée. Les deux observations d’inventaire d’ordres trouvées dans cette source concernent un autre compte. Les fills ne comblent pas ce manque. |
| Heure de réception locale par fill et ordre de décision | Absents des pages REST au niveau du fill ; seule l’heure de réception de la page est conservée. Les observations WebSocket ont `observed_at` et un temps d’événement dans le payload, mais leurs grands trous doivent être rapprochés des fills avant usage. |
| Barème daté, palier et rétrocession applicable au compte | Non trouvés dans les observations archivées de ce compte. Les montants de frais réalisés dans les fills, eux, sont disponibles. |
| Motivation, cible interne et couverture de hedges externes | Inobservables dans ces archives et inutiles pour l’hypothèse limitée aux exécutions observées. |

Le paquet d’analyse IA scellé est conservé à [POPULATION-67F7-ETH-RESEARCH-PACKET-20261014.json](POPULATION-67F7-ETH-RESEARCH-PACKET-20261014.json). Il maintient ETH séparé de DRAM ; une gestion commune de l’inventaire reste possible mais n’est pas démontrée ici. La réponse brute rejetée, son diagnostic, l’adaptation, la critique validée et l’usage sont conservés dans le registre de recherche local.

## Résolution locale fills → carnet et positions — rectifiée par v3

Les conclusions de couverture de la v1 et de la v2 sont retirées : leur lecteur ne traitait que les messages individuels. Les lots `events[]` ont été décodés en v3, sans changer le cutoff scellé (`2026-10-12T07:16:34.195Z`) ni les archives autorisées. Le détail et la portée du rectificatif sont dans [l’erratum v3](POPULATION-67F7-ETH-LOCAL-ARCHIVE-JOIN-ERRATUM-20261014.md) ; les artefacts v1/v2 sont conservés.

Le passage réel du scheduler avec `--resume-local-resolution` a recalculé la seule résolution locale, sans IA ni collecte. L’artefact est daté du 14 octobre 2026 à 10:12:05 CEST ; le contrôle `unchanged` a suivi à 10:13:42 CEST. La version est `population-offline-archive-join-v3`. L’artefact [v3](POPULATION-67F7-ETH-LOCAL-ARCHIVE-JOIN-20261014-v3.json.gz) porte l’empreinte d’artefact `7c9127a0c44cc1bfe801cf3a5ce74949b9e96d5ef610630fbaf3f2117b744169`, l’empreinte des sources `70b2293f578f6576bd4976b19955f00dca59895cd8901f71e4612c953201d7a7` et l’empreinte d’analyse `ed93f7c2e8502ded632bea2691a02056a8b9c1e64f1e9daadc7438195d973441`.

| Source | Lots lus | Lots avec `events[]` / individuels | Événements décodés et admissibles | Octets canoniques décodés | Rejets d’événements |
|---|---:|---:|---:|---:|---:|
| BBO ETH | 484 129 | 481 509 / 2 620 | 3 230 899 | 811 555 191 | 0 |
| `l2Book` ETH | 484 670 | 483 837 / 833 | 1 135 567 | 660 042 138 | 0 |

Les compteurs de lots et d’événements sont distincts : les sommes des `record_count` annoncés sont 3 228 279 et 1 134 734, alors que le décodage effectif compte 3 230 899 et 1 135 567 événements. Les limites appliquées par flux sont 600 000 lots, 4 000 000 événements et 1 000 000 000 octets décodés ; chaque lot est limité à 16 000 000 octets. Les horodatages source de chaque événement, sa réception locale et l’heure d’archivage du lot qui le contient restent séparés dans l’artefact. Le marché ETH, les canaux BBO/`l2Book`, le réseau, les références et le cutoff ont été validés. Aucun événement rejeté pour marché, canal, forme ou heure après cutoff n’a été trouvé dans la coupe scellée.

Les 23 140 fills ont un contexte antérieur selon l’horloge d’événement pour BBO et `l2Book`, et aussi selon l’horloge de réception locale. Cela établit une couverture d’appariement, pas une fraîcheur uniforme. Pour BBO, l’âge événement→fill est p50 **0 ms**, p95 **17 865 239 ms** (4 h 57 min), maximum **22 881 565 ms** ; pour `l2Book`, p50 **278 ms**, p95 **17 865 646 ms**, maximum **22 881 972 ms**. Le 8 octobre explique le gros des prédécesseurs anciens : les âges médians ce jour-là dépassent 3 h 46 min pour les deux flux. Les 6–7 et 9–11 octobre ont généralement des prédécesseurs bien plus proches, avec des trous locaux allant jusqu’à 11 331 436 ms BBO et 11 331 767 ms `l2Book`.

Selon l’horloge locale, l’âge de réception du quote sélectionné jusqu’à la réception de la page REST contenant le fill est p50 **771 ms** BBO et **919 ms** `l2Book` (p95 2 285 ms et 1 760 ms). L’âge de disponibilité de son lot archivé à cette même réception de page est p50 **612 ms** et **582 ms** (p95 2 136 ms et 1 146 ms). La page REST est une borne tardive et groupée, pas l’arrivée du fill ; ces valeurs ne démontrent donc pas que le quote était disponible avant la décision ou le fill. Les différences brutes réception locale − temps d’événement ont une médiane de 354 ms BBO et 401 ms `l2Book`, mais l’écart et la dérive des horloges ne sont pas calibrés : ce ne sont pas des mesures de transport.

Les instantanés de position selon temps d’événement précèdent 17 170 fills ; 5 970 restent inconnus selon cette horloge. Aucun des 17 170 n’égale `startPosition` (écart absolu médian 2,036 ETH). En horloge de réception de page, les 23 140 comparaisons diffèrent aussi, avec écart médian 1,9892 ETH et âge médian 8,725 s. Ce sont des points espacés, pas une preuve de continuité ou d’un champ fautif. Les deux segments et la rupture antérieure restent tels que décrits dans l’analyse initiale.

Cette v3 permet de comparer descriptivement les fills au contexte de marché observé, en rapportant l’âge et l’horloge de chaque appariement. Elle ne permet pas une comparaison proche du fill sur chaque journée (notamment le 8 octobre), une disponibilité avant décision, une reconstruction des ordres non remplis ni une conclusion causale. Aucune borne de fraîcheur nouvelle n’est imposée. Le moteur paper n’est pas modifié.

## Prochain état persisté

Le routeur conserve `local_archive_analysis_complete`, maintenant lié à l’empreinte v3 `7c9127a0c44cc1bfe801cf3a5ce74949b9e96d5ef610630fbaf3f2117b744169`. Le passage scheduler de contrôle retourne `unchanged`; il ne relance ni analyse, ni collecte, ni IA sur des données inchangées. Prochaine action : revue humaine des comparaisons historiques et de leur limite de fraîcheur. Aucun nouveau besoin de collecte n’est inscrit automatiquement. Si une recherche de décisions de placement est souhaitée ensuite, les journaux d’ordres prospectifs seraient nécessaires ; leur activation reste manuelle. Le mécanisme d’exécution passif n’est pas simulé par le moteur actuel, indépendamment de l’intérêt descriptif.
