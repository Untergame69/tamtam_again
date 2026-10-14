# 67f7 / ETH — association inventaire/exécutions avec contexte de marché

**Conclusion : association descriptive persistante dans la coupe couverte ; portée historique limitée par une sélection non uniforme.** Les résultats ne démontrent ni causalité, ni politique de placement d’ordres. Fills et jours sont regroupés : les 19 821 fills couverts ne sont pas 19 821 réplications indépendantes.

## Méthode et coupe

L’analyse réutilise la jointure [v3](POPULATION-67F7-ETH-LOCAL-ARCHIVE-JOIN-20261014-v3.json.gz), paquet scellé et cutoff inchangés, et ajoute l’analyse versionnée `population-inventory-market-context-v2`. Pour le contexte, une cotation n’est antérieure que si `data.time < fill.time`. Les observations au même milliseconde sont exclues du contexte et référencées comme ordre relatif inconnu : au moins un flux a une égalité pour **19 693 fills**. Chaque ligne conserve les références d’observation, l’heure source, `events[].received_at` (ou `observed_at` pour les messages individuels), l’archivage du lot, et la réception de la page REST contenant le fill. Les deux temps locaux sont comparés seulement au reçu local de cette page ; aucune heure de réception du fill ou de décision n’existe et les horloges source/locale ne sont pas calibrées.

Le contexte principal exige BBO et meilleur niveau `l2Book` strictement antérieurs et âgés d’au plus **30 s**, avec un mouvement BBO sur 30 s. Le point de départ du mouvement est le dernier BBO à ou avant `fill−30 s`, accepté seulement s’il se trouve entre **30 et 60 s avant le fill**. Cette marge garde une mesure locale malgré la cadence d’archive. Le spread utilise le BBO courant ; la profondeur est la taille au meilleur bid/ask, et la profondeur du côté de réduction de l’inventaire est rapportée séparément. Les sensibilités d’âge (0, 1, 5, 30, 60 et 300 s) décrivent la fraîcheur ; elles ne fixent pas une règle d’exécution et n’héritent pas du seuil paper d’une seconde.

| Âge maximal des deux meilleurs niveaux | Fills couverts | Part des 23 140 |
|---:|---:|---:|
| 0 s | 0 | 0,0 % |
| 1 s | 19 241 | 83,2 % |
| 5 s | 19 821 | 85,7 % |
| 30 s | 19 838 | 85,7 % |
| 60 s | 19 856 | 85,8 % |
| 300 s | 19 856 | 85,8 % |

Le contexte principal complet est disponible pour **19 821 fills (85,7 %)**. Par jour/segment : 6 oct. **3 213/3 236 (99,3 %)** ; 7 oct. **2 731/2 734 (99,9 %)** ; 8 oct. **2 067/5 360 (38,6 %)** ; 9 oct. **5 202/5 202** ; 10 oct. **2 934/2 934** ; 11 oct. **3 674/3 674**. La sélection varie aussi selon l’inventaire : couverture principale Q1–Q4, regroupée long+short, **90,7 %, 91,3 %, 89,4 %, 71,2 %**. L’absence de cotation récente touche donc davantage le 8 octobre et les positions Q4.

## Association observée

Les quartiles de position absolue sont ceux des 23 140 fills : 1,0494 / 1,9892 / 2,9452 ETH. Les inversions sont coupées à zéro ; le fill compte comme ayant une composante de clôture si sa quantité ferme l’exposition ancienne. Le rapport sépare cette fréquence de la quantité taker de clôture, et indique aussi si le fill entier a diminué la position absolue.

| Côté | Coupe | Taker avec clôture / tous les fills Q1 → Q4 | Quantité taker de clôture / quantité exécutée Q1 → Q4 |
|---|---|---:|---:|
| Long | Tous les fills | 5,33 % → 12,30 % (**+6,97 pp**) | 2,12 % → 16,96 % (**+14,84 pp**) |
| Long | Contexte principal | 4,73 % → 12,17 % (**+7,44 pp**) | 1,97 % → 15,65 % (**+13,67 pp**) |
| Short | Tous les fills | 7,16 % → 18,87 % (**+11,71 pp**) | 3,54 % → 25,78 % (**+22,24 pp**) |
| Short | Contexte principal | 6,53 % → 18,74 % (**+12,21 pp**) | 3,26 % → 25,02 % (**+21,75 pp**) |

Dans le contexte principal, la différence Q4−Q1 reste positive quand on stratifie séparément selon chacune des trois conditions, avec trois strates Q1/Q4 en support commun par côté :

| Stratification séparée | Long : fréquence taker avec clôture / quantité de clôture | Short : fréquence taker avec clôture / quantité de clôture |
|---|---:|---:|
| Direction du mouvement BBO 30 s | +7,39 / +14,11 pp | +11,88 / +21,97 pp |
| Tertiles du spread | +7,56 / +13,77 pp | +12,25 / +21,63 pp |
| Tertiles de profondeur côté de réduction | +6,58 / +13,17 pp | +9,68 / +20,60 pp |

Les contrôles sont un facteur à la fois, pondérés par le minimum d’effectifs Q1/Q4 de chaque strate ; ce n’est pas une régression simultanée ni un test d’hypothèse. Le contraste persiste descriptivement après ces distinctions simples, mais le sous-ensemble couvert n’est pas représentatif par construction : il sous-couvre Q4 et le 8 octobre. Le résultat ne permet pas d’attribuer le gradient à une règle de réduction plutôt qu’au flux de marché, à la sélection des fills, à la liquidité ou à d’autres variables non observées. Une inversion compte comme clôture partielle même si le reliquat ouvert rend la position absolue finale plus grande ; le nombre de fills qui diminuent toute la position absolue est séparé.

## Protocole prospectif minimal proposé — non lancé

Sur **20 jours UTC actifs consécutifs**, enregistrer pour chaque fill ETH : position juste avant fill, côté, quantité, `crossed`, temps source et reçu du fill/page ; BBO et meilleur bid/ask L2 avec temps source, reçu et disponibilité d’archivage ; retour médian BBO sur la fenêtre définie ci-dessus, spread, tailles au meilleur niveau et références. Une observation manquante reste manquante. Publier la couverture par jour et position, puis comparer les mêmes deux mesures (fréquence des fills taker de clôture et part de quantité taker de clôture) par côté, dans les strates marché avec support commun ; regrouper l’incertitude par jour et épisode, jamais par fill indépendant.

Critère de réfutation préenregistré : si, après 20 jours et avec support Q1/Q4 dans les strates, la différence Q4−Q1 est non positive pour les deux mesures dans les deux côtés et que sa borne supérieure d’intervalle bootstrap regroupé par jour est ≤0, l’association annoncée est réfutée sur cette période. Si la couverture ou le support commun manque, la conclusion reste indéterminée. Ce suivi mesurerait les exécutions observées ; il ne révélerait toujours pas les ordres non exécutés ni ne prouverait une intention de placement.

## Persistance et reproduction

Le résultat est persisté dans `population_inventory_market_contexts`, version `population-inventory-market-context-v2`, lié à la jointure v3 `7c9127a0c44cc1bfe801cf3a5ce74949b9e96d5ef610630fbaf3f2117b744169`. Empreinte d’analyse : `17fdf210f8230dd7de7eae7a3f410fa89536ea6d3cda4247216b2d105b792e79`. L’artefact par fill est [compressé ici](POPULATION-67F7-ETH-INVENTORY-MARKET-CONTEXT-20261014-v2.json.gz). L’artefact v1, calcul exploratoire antérieur avec une définition moins stricte de l’horizon de mouvement, est conservé séparément ; v2 le remplace pour l’interprétation.

Reprise déterministe, sans appel IA :

```sh
PYTHONPATH=src python scripts/population-research-tick.py \
  --db data/tamtam.sqlite3 \
  --policy config/population-research-policy.json \
  --resume-local-resolution 2b7bf5b9d35a8059bba6d0af645000f357d6494577ec99a8377fbff8f1a3c6f6
```

Le passage réel a persisté v2 ; le contrôle immédiat a rendu `unchanged` avec la même empreinte. Aucun appel IA, collecte, paper ou ordre réel n’a eu lieu.
