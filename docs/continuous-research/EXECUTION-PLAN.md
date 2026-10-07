# Recherche continue — plan d'exécution du 7 octobre 2026

L'objectif intégral est conservé dans OBJECTIVE.md. Ce document est un registre
local de progression, pas une approbation finale. La revue indépendante reste requise.

## État initial établi

Git fdb1264 ; 681 candidats (671 non suivis, 10 suivis), exclusivement découverts
par classement. Collecteur actif, mémoire environ 4 Go, base environ 7,2 Go.
REST marché 60 s, classement 900 s, comptes 900 s ; 30 marchés BBO/trades et
30 L2 rapide à cinq niveaux ; 10 utilisateurs fills/funding, une connexion.
Les effectifs de messages réels/abonnements reconnus restent à mesurer.
Le rattrapage historique et l'incrémental passent par les mêmes workers REST.

Huit plans, trois variantes figées, zéro évaluation et zéro session paper au
relevé. CL/XRP/HYPE/BRENTOIL : préserver les huit plans, toutes les empreintes et
les fenêtres réservées. Le diagnostic n'exporte aucun payload brut ni résultat
réservé. Le baseline contient uniquement métadonnées et empreintes.

Le moteur actuel exécute follower/leader_delta et autonomous/momentum, un marché.
Le passif ne simule aucune exécution. Horizon 120 s, taille/latence et familles
restreintes sont des paramètres du pilote, pas des limites universelles.
L'extension sera versionnée ; les pilotes ne changeront pas de reducer.

## Contraintes et constats

Source vérifiée le 7 octobre : documentation officielle Hyperliquid.
- REST : 1200 poids/minute/IP ; limite locale choisie 900 (marge de 25%).
- 10 connexions WS, 1000 abonnements, 10 utilisateurs distincts/IP.
- Le nombre de comptes interrogés en REST n'est pas limité à 10.
- WsTrade fournit users=[buyer,seller] : découverte par marché possible.
- userFillsByTime : 2000/page, 10000 dernières exécutions accessibles.
- userRole coûte 60 ; la liste des types légers coûte 2, les autres 20,
  certains historiques ont un supplément par nombre d'éléments retournés.
- Le code réservait à tort un supplément d'éléments pour le ledger non-funding.
  Corriger cette estimation, sans assimiler poids réservé et poids facturé.
- Mode de compte userAbstraction et périmètres HIP-3 absents de la qualification
  actuelle : ne pas sommer aveuglément les capitaux de chaque dex.
- L'âge d'un BBO inchangé n'est pas une interruption de connexion.

## Dépendances et ordre d'exécution

1. Baseline protégé, références officielles, instrumentation et tests quotas.
2. Budget mesuré et ordonnanceur REST indépendant des slots directs.
3. Provenance multiple et découverte par participants, exploration de marchés.
4. Inventaire des périmètres puis qualification comptable réconciliée.
5. Profils comportementaux, politique d'allocation et cohortes témoins.
6. Profils d'expérience, contrat d'extension et reducer multi-instruments.
7. Adaptation causale, mémoire protégée, évaluation de la procédure entière.
8. Capacité/coûts comparés, recette, documentation et compte rendu indépendant.

## Matrice de suivi (aucune complétude implicite)

| Exigence | État au début | Preuve attendue |
|---|---|---|
| 1 Diagnostic | En cours | baseline métadonnées + plan et contraintes sourcées |
| 2 Capacité | À faire | mesures REST/WS et scénarios reproductibles |
| 3 Ordonnanceur | À faire | >10 comptes REST avec slots directs distincts |
| 4 Découverte | À faire | classement et participants, provenance et couverture |
| 5 Périmètre | À faire | standard/HIP-3/spot/mode/relations documentées |
| 6 Comptabilité | À faire | bornes explicites, flux, réconciliation et inconnues |
| 7 Comportements | À faire | descripteurs causaux, coordination non interprétée |
| 8 Allocation | À faire | politique versionnée, cohortes/témoins et retraits |
| 9 Expériences | À faire | profils justifiés, coûts/délais/liquidité sensibles |
| 10 Extension | À faire | multi-instruments, risque des jambes, tests comptables |
| 11 Adaptation | À faire | transitions automatiques et reprise sans faux succès |
| 12 Évaluation système | À faire | rejouabilité des choix et références fixes/témoin |
| 13 Mémoire | À faire | preuves, accès temporels, aucune réserve divulguée |
| 14 Montée capacité | À faire | coûts/capacités/maintenance/risques chiffrés |
| 15 Vérification/livraison | À faire | tests, contrôles réels, CR et retour arrière |

## Sources

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint

## Vérification et retour arrière

`python3 scripts/research-baseline.py --db data/tamtam.sqlite3 --output /tmp/baseline.json`
Recomparer les identifiants et empreintes aux plans/variantes du baseline initial.
Les diagnostics de développement ne doivent jamais lire les événements réservés.
Les migrations seront additives ; la télémétrie vit dans une base séparée.
Revenir sur le code ciblé et conserver toutes les bases : aucune restauration
complète de la base active ne doit supprimer la collecte accumulée.
