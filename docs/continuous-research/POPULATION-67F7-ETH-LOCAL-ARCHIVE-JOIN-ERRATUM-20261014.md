# Rectificatif v3 — jointure locale ETH du 67f7

Date : 14 octobre 2026

Ce rectificatif est lié au rapport [Recherche 67f7 / ETH — résultat du 14 octobre](POPULATION-67F7-ETH-RESEARCH-RESULT-20261014.md) et à la nouvelle [résolution locale v3](POPULATION-67F7-ETH-LOCAL-ARCHIVE-JOIN-20261014-v3.json.gz).

## Conclusion retirée

La conclusion v2 selon laquelle aucun BBO ou `l2Book` ne tombait dans les intervalles des fills est retirée. Les v1/v2 ne lisaient que les messages individuels alors que les archives récentes stockaient les messages dans des lots `events[]`. Le lecteur rejetait ainsi 481 509 lots BBO et 483 837 lots `l2Book`; ce sont des nombres de lots, pas d’événements. Les fichiers v1 et v2 restent préservés comme artefacts historiques, mais leur conclusion d’absence de carnet contemporain ne doit plus être utilisée.

## Résultat corrigé

La v3 prend en charge les messages individuels et les lots. Elle conserve par événement le temps source, l’heure de réception locale et l’heure à laquelle le lot complet a été archivé. Elle vérifie le réseau, le marché ETH, le canal attendu, les références de source et le cutoff scellé `2026-10-12T07:16:34.195Z`. Les limites de traitement sont explicites : par flux, 600 000 lots, 4 000 000 événements et 1 000 000 000 octets canoniques décodés ; par lot, 16 000 000 octets.

- BBO : 484 129 lots, dont 481 509 groupés et 2 620 individuels ; 3 230 899 événements admissibles, zéro événement rejeté.
- `l2Book` : 484 670 lots, dont 483 837 groupés et 833 individuels ; 1 135 567 événements admissibles, zéro événement rejeté.
- Les 23 140 fills ont un prédécesseur dans les deux flux par temps d’événement. L’âge p95 est environ 4 h 57 min ; le 8 octobre porte des prédécesseurs vieux de plusieurs heures. L’appariement n’est donc pas synonyme de fraîcheur.
- Les appariements selon réception locale ont un âge médian inférieur à une seconde, mais leur repère est la réception tardive de la page REST contenant le fill, pas la réception du fill ni une décision du moteur. L’heure source et l’heure locale ne sont pas calibrées l’une contre l’autre.
- Les snapshots de compte restent espacés : 17 170 comparaisons selon temps d’événement, aucune égalité exacte avec `startPosition`, et 5 970 fills sans snapshot antérieur sous cette horloge. Les observations ne prouvent pas la continuité de position.

L’artefact v3 rapporte les trous par segment/jour, conserve les cas non appariés et distingue la couverture d’événements de celle des lots. Il ne donne pas les instants d’ordre/décision, la disponibilité directe avant fill, les ordres annulés ou non exécutés, ni une preuve causale. Aucun seuil de fraîcheur n’a été ajouté.

## Preuves opérationnelles

La reprise réelle du scheduler a créé la v3 avec l’empreinte `7c9127a0c44cc1bfe801cf3a5ce74949b9e96d5ef610630fbaf3f2117b744169` à partir des sources scellées `70b2293f578f6576bd4976b19955f00dca59895cd8901f71e4612c953201d7a7`. Le passage de contrôle a rendu `unchanged` avec la même empreinte. Les tests ciblés couvrent les deux formats, les horodatages et cutoff, la taille de lot, les plafonds de décodage, le rejeu et le scheduler. Aucun appel IA, collecte, paper ou ordre réel n’a été exécuté.
