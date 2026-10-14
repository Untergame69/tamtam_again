# File persistante de recherche — 14 octobre 2026

## Raccordement livré

`research_work_queue` enregistre les travaux par source et empreinte d’entrée. Les états sont `ready`, `waiting_data`, `waiting_deadline`, `budget_exhausted`, `technical_required` et `completed`. Les doublons sont écartés par contrainte SQLite. Le tick du scheduler fait avancer les échéances, prépare un paquet compact à partir d’un bilan ETH final persisté, et conserve le résultat pour reprise. Il ne fait aucun appel IA. Une attente ou une route terminale n’occupe pas le créneau d’exécution des autres travaux.

Les routes déjà présentes sont reflétées dans la file sans réécrire leur historique. Le traitement déterministe local existant et le traitement des paquets ETH restent sous le verrou du scheduler.

## Preuve opérationnelle

Le scheduler existant a été exécuté deux fois sur `data/tamtam.sqlite3` avec `dispatch=False` et l’autorisation dédiée v2. Aucun appel fournisseur n’a été engagé. Au premier passage, le protocole `67f7-eth-public-observation-24h-20261014-v1` a été enregistré en `waiting_deadline`, réveil fixé à sa fin scellée (`2026-10-15 15:00 UTC`). Le second passage a retrouvé cette ligne sans doublon.

Le second passage a visité les trois candidats :

- a880 : `unchanged_no_inference`, même question, cutoff et empreinte des fills ;
- 67f7 : `unchanged_no_inference` pour les mêmes raisons ;
- be504 : `unchanged_no_inference` pour les mêmes raisons.

Un paquet a880 préparé par erreur au premier passage n’a pas été activé. Il est conservé avec l’état `needs_data` et le diagnostic `unchanged_evidence_no_inference`. Aucun compteur d’appel ou de token n’a bougé. Le contrôle inter-allowances empêche désormais qu’un changement de version du sérialiseur soit pris pour de nouvelles preuves.

Au second passage, la file contenait 1 échéance ETH, 9 entrées d’attente de données, 3 interventions techniques et les entrées terminées conservées. Les entrées non prêtes n’ont pas bloqué le tick.

## Enveloppe

`config/research-loop-pilot-v2.json` est distincte du pilote v1 consommé. Elle garde le mode abonnement et les plafonds autorisés : 3 tâches, 6 appels, 480 000 tokens d’entrée, 30 000 de sortie et 720 secondes cumulées, avec les limites existantes par appel et tâche. Aucun USD n’est réservé ou déclaré. Utilisation réelle : 0 appel, 0 token déclaré, 0 ms d’appel. Une tâche v2 préparée est conservée en attente, sans activation fournisseur ; deux places de tâche restent disponibles. Aucun ancien essai n’a été réarmé.

Le timer existant du scheduler a été rechargé avec ce fichier v2 ; il reste actif. Son prochain passage observé était prévu le 14 octobre à 17:32 CEST. Le timer de l’observation ETH reste actif et inchangé.

Après le bilan final, le scheduler suivant prépare automatiquement le paquet `eth-observation-review-packet-v1` référencé par l’empreinte du bilan, marque ce travail terminé et laisse la décision de recherche en revue humaine. Un bilan favorable ne promeut pas un paper. Aucune inférence n’est lancée à ce stade : aucune question nouvelle n’est encore justifiée avant les résultats de l’observation.

## Vérifications et limite opérationnelle

Tests ciblés : `tests.test_research_work_queue` (4 tests) et `tests.test_population_pilot` (18 tests), succès. Ils couvrent attentes et échéances, absence de blocage des autres travaux, persistance/réouverture, rejeu idempotent, états budget/technique et non-répétition d’une même question sur les mêmes preuves. Le passage réel est distinct de ces tests simulés.

Les tickets YouTrack concernés n’étaient pas accessibles par un connecteur dans cette session ; ce rapport et le commit gardent la preuve locale. Prochaine étape automatique : observation inchangée jusqu’au 15 octobre 15:00 UTC, puis collecte finale et paquet déterministe au prochain tick du scheduler. La revue humaine de la recommandation reste nécessaire ; aucune activation IA, paper ou ordre n’est automatique.
