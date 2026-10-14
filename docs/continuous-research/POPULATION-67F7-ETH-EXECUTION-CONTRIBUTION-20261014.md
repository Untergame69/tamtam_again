# 67f7 / ETH — contribution économique exploratoire

**Décision : l’intérêt suffit pour une observation prospective bornée.** Les épisodes bornés restent positifs après les frais observés et le funding attribuable. Les fills taker qui réduisent l’inventaire sont suivis d’un markout médian dans le sens du fill, y compris avec une cible BBO proche. L’écart avec les fills taker ouvrants est toutefois modeste, les trous de carnet sont importants et les fills ne révèlent ni l’intention ni les ordres non exécutés. Cela justifie de vérifier la reproductibilité descriptive, pas de valider une stratégie ni de lancer un paper.

## Données et méthode

Analyse reproductible depuis la racine du dépôt :

```sh
PYTHONPATH=src python scripts/analyze_67f7_eth_execution_contribution.py
```

Le scheduler de recherche exécute désormais cette résolution déterministe après
la jointure locale scellée et son contexte. Il stocke le résultat dans
`population_eth_execution_contributions` et rattache sa version, son empreinte
et sa référence de fichier à la route. Un rejeu retourne `unchanged` sans
recalculer ni créer de seconde ligne. Le passage de vérification sur la base
locale a retrouvé l’empreinte ci-dessous, avec zéro appel IA et aucune collecte.

L’artefact est [POPULATION-67F7-ETH-EXECUTION-CONTRIBUTION-20261014-v1.json.gz](POPULATION-67F7-ETH-EXECUTION-CONTRIBUTION-20261014-v1.json.gz). Empreinte d’analyse : `17f762c9ccda22abef0610c0e15114360f1553d9d9dc73336c9a7d43f24a4266`. Il est rattaché à la jointure scellée v3 `7c9127a0c44cc1bfe801cf3a5ce74949b9e96d5ef610630fbaf3f2117b744169` et au contexte inventaire/marché v2 `17fdf210f8230dd7de7eae7a3f410fa89536ea6d3cda4247216b2d105b792e79`. La source BBO utilisée est couverte par l’empreinte `07e5635631ab384d70e897742dc46c8a97e3959dcd51324b872272d10e2092fe`.

Les 23 140 fills ETH sont issus de 57 pages REST toutes marquées incomplètes ; 11 pages ont épuisé leur budget de pagination. L’archive contient également 2 461 fills d’autres marchés, exclus des calculs ETH. Les 484 129 lots BBO ont fourni 3 230 899 événements admissibles au cutoff, sans rejet de format ou de marché. La période des fills va du 6 au 11 octobre 2026. La continuité de l’archive n’est pas démontrée.

Pour chaque fill, le prix est comparé au dernier milieu BBO dont l’heure d’événement est **strictement antérieure**. Un BBO au même milliseconde est exclu. Les horizons futurs sont 1 s, 60 s, 5 min et 15 min : le premier mesure la réaction courte, 60 s est proche de la durée médiane d’épisode (72,959 ms), 5 min explore des épisodes plus longs et 15 min approche leur p95 (954,300 ms, soit 15 min 54 s). Le maximum observé est 1 h 44 min. Le premier BBO à ou après la cible ne constitue qu’une conséquence mesurée, jamais un signal historique.

Les retours sont directionnels selon le côté du fill. Les frais sont les frais signés réellement archivés (`+` débité, `−` rétrocédé). Lors d’une inversion, la fee du fill unique est ventilée au prorata des quantités de fermeture et d’ouverture ; cette répartition est une convention arithmétique, pas un détail fourni par l’exchange. Aucun coût de notre exécution n’est estimé. Les markouts et les flux d’épisodes se recouvrent économiquement et sont présentés séparément, sans les additionner.

## Épisodes bornés

Les épisodes sont les reconstructions locales qui commencent à position zéro et se terminent au retour à zéro ou à une inversion. Résultats de prix, frais et funding restent distincts ; le net ci-dessous est simplement `résultat de prix − frais signés + funding strictement attribué`, en USDC.

| Segment / jour de sortie UTC | Épisodes | Prix (USDC) | Frais signés (USDC) | Funding attribué (USDC) | Net observé attribué (USDC) |
|---|---:|---:|---:|---:|---:|
| Segment 1 | 388 | +490.84092 | +89.95415 | +0.087338 | +400.97411 |
| Segment 2 | 1,221 | +1,176.08481 | +425.75995 | +0.391954 | +750.71681 |
| 6 oct. | 205 | +138.37895 | +25.79544 | −0.266206 | +112.31731 |
| 7 oct. | 183 | +352.46197 | +64.15871 | +0.353544 | +288.65680 |
| 8 oct. | 365 | +668.21723 | +344.73852 | +0.155638 | +323.63435 |
| 9 oct. | 318 | +379.21067 | +123.39490 | −0.040779 | +255.77499 |
| 10 oct. | 226 | −70.14370 | −65.21274 | +0.156324 | −4.77464 |
| 11 oct. | 312 | +198.80061 | +22.83927 | +0.120771 | +176.08211 |

Au total, les 1 609 épisodes donnent +1,666.92573 de résultat de prix, +515.71410 de frais signés et +0.479292 de funding attribué, soit +1,151.69092 après ces postes observés. Le 8 octobre porte 40 % du résultat de prix positif agrégé. Le plus grand épisode représente 5.34 % de la somme des valeurs absolues du segment 1 et 1.96 % du segment 2 ; leurs cinq plus grands épisodes en représentent respectivement 18.93 % et 6.67 %. Les épisodes sont dépendants et ces concentrations ne sont pas des statistiques de portefeuille exhaustif.

Les 23 140 fills comportent +517.031372 de frais signés au total : makers −746.342482 (rétrocessions) et takers +1,263.373854 (débits). Dans les parts d’épisodes bornés, +515.714101 sont attribués ; +1.317271 reste hors de ces parts, notamment aux extrémités censurées et fermetures gauches. Aucun fill archivé n’a un champ de frais manquant. Sur 134 événements funding, 102 (+0.479292) satisfont l’attribution stricte à un épisode et à la position antérieure exacte ; 32 (+0.630881) restent non attribués.

Deux épisodes restent ouverts/censurés aux limites observées. Les positions après le dernier fill sont +2.5643 ETH et −2.7433 ETH. Une rupture distincte de 106,439,824 ms (29 h 34 min) sépare les segments ; elle conserve un passage de +2.5643 à −3.1339 au redémarrage de l’observation. Aucun flux d’épisode borné ne franchit cette rupture.

## Prix d’exécution et mouvements ultérieurs

Sur les 19 279 fills maker, le coût signé médian contre le BBO antérieur est −0.1995 bp (prix en moyenne meilleur que le milieu à la médiane). Sur les 3 861 fills taker, il est +0.2002 bp. L’âge médian du BBO antérieur est 135 ms, mais son p95 atteint 17,865,239 ms, près de 5 heures. Le nombre de quotes antérieures est complet si l’on accepte n’importe quel âge ; il ne l’est pas au sens d’une quote fraîche : 8 045 fills (34.8 %) ont une quote âgée d’au plus 100 ms, 19 246 (83.2 %) d’au plus 1 s, 19 822 (85.7 %) d’au plus 5 s, et 19 838 (85.7 %) d’au plus 30 s. Le coût médian reste proche de −0.20 bp maker et +0.20 bp taker dans les groupes jusqu’à 5 s ; les coûts calculés avec des quotes âgées de plus de 5 min deviennent dominés par les ruptures de données et ne sont pas interprétés comme slippage.

| Exécutions | Nombre | Quantité qui réduit | Quantité qui ouvre | Frais signés observés (USDC) | Markout directionnel médian à 60 s, événement BBO cible à ≤5 s (avant-fill non filtré) |
|---|---:|---:|---:|---:|---:|
| Maker — ouverture / augmentation | 9,456 | 0 | 4,172.5782 ETH | −316.238206 | ≈ 0 bp |
| Maker — réduction | 8,566 | 3,886.4434 ETH | 0 | −294.482083 | 0 bp |
| Maker — inversion | 1,257 | 862.3614 ETH | 926.6465 ETH | −135.622193 | ≈ 0 bp |
| Taker — ouverture / augmentation | 1,321 | 0 | 1,043.3102 ETH | +439.201403 | +1.22 bp |
| Taker — réduction | 2,186 | 1,307.6623 ETH | 0 | +551.695071 | +2.30 bp |
| Taker — inversion | 354 | 365.1615 ETH | 280.6580 ETH | +272.477380 | — |

Les inversions sont ventilées arithmétiquement entre quantité de fermeture et d’ouverture au prix unique du fill. Les markouts utilisent le côté complet du fill ; ils ne sont pas répartis entre ces deux jambes.

Toutes les exécutions ont un événement BBO ultérieur dans les archives jusqu’au cutoff, mais cela surestime la couverture utile à l’horizon : au target 60 s, 19 246/23 140 horodatages d’événement sont au plus 1 s après la cible et 19 839 au plus 5 s après. Le p95 du retard événementiel à la cible est 8,096,326 ms (2 h 15 min). Ces délais sont mesurés en heure d’événement et ne prouvent pas une disponibilité live à la cible. Parmi les taker réducteurs, le markout directionnel médian à 60 s est +1.91 bp en prenant toutes les quotes ultérieures disponibles. En exigeant à la fois un BBO antérieur âgé de ≤1 s et un horodatage d’événement BBO au plus 5 s après la cible, la couverture est de 1,779/2,186 (81.4 %) et la médiane est +2.30 bp. Les taker ouvrants ont aussi un markout positif : +1.47 bp avec cette même règle, mais sur 981/1,321 fills (74.3 %). Ce rapprochement brut ne montre donc pas un avantage propre aux réductions d’inventaire. Les médianes sont par fills observés, pas des observations indépendantes ni des ordres passifs simulés.

## Décision et protocole proposé

**Décision unique : mener une observation prospective, sans paper, sur la reproductibilité du markout des taker réducteurs par rapport aux taker ouvrants.** Le gain de flux sur épisodes et les markouts frais donnent une question mesurable. Les archives seules ne permettent pas d’attribuer une intention, des ordres non exécutés, une sélection des prix ou notre propre coût d’exécution.

Protocole à préparer, non lancé : observer les fills publics ETH de ce compte et le BBO reçu, avec les heures événement/réception/archivage conservées ; comparer réduction et ouverture taker sur le markout directionnel à 60 s, conditionné au jour, côté, mouvement BBO antérieur de 30 s et tertiles de spread/profondeur. L’unité de regroupement est le jour UTC.

- **Durée maximale : 14 jours calendaires consécutifs**, sans prolongation. La fenêtre permet deux cycles hebdomadaires ; les 2,186 taker réducteurs historiques en six jours suggèrent que 1,000 sont observables, mais les trous archivés interdisent de supposer ce débit acquis.
- **Minimum interprétable :** 1,000 fills taker réducteurs, au moins 10 jours avec données, et couverture conjointe d’un BBO strictement antérieur âgé de ≤1 s et d’une quote ≤5 s après la cible 60 s d’au moins 80 % dans les deux groupes. Cette barre est voisine de la couverture historique des réductions (81.4 %) et un peu au-dessus de celle des ouvertures (74.3 %) ; la collecte prospective doit donc réellement conserver le carnet en continu. Elle ne vaut pas filtre d’admission à une expérience.
- **Favorable :** le markout directionnel médian des réductions est positif et supérieur à celui des ouvertures dans chacune des deux semaines, et l’intervalle à 95 % obtenu par rééchantillonnage des jours UTC de la différence reste entièrement positif.
- **Défavorable :** avec le minimum interprétable atteint, la différence réduction moins ouverture est nulle ou négative dans les deux semaines, ou le markout médian des réductions est non positif dans les deux.
- **Indéterminé :** minimum de données/fraîcheur non atteint, semaines de signes opposés, support commun trop faible pour les cellules, ou intervalle recouvrant zéro.

Même favorable, ce résultat établirait uniquement une association prospective entre fills publics observés et mouvement ultérieur du milieu. Il ne validerait ni causalité de placement ni rentabilité de notre moteur.
