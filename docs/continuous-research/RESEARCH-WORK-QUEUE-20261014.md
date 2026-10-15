# File persistante de recherche — 14 octobre 2026

## Raccordement livré

`research_work_queue` enregistre les travaux par source et empreinte d’entrée, avec un journal persistant des transitions. Il distingue `packet_prepared`, `analysis_ready`, `analysis_running`, `analysis_skipped`, `analysis_completed`, `resolution_ready`, `waiting_data`, `waiting_deadline`, `budget_exhausted`, `technical_required` et `completed`. Les doublons sont écartés par contrainte SQLite et empreinte sémantique. Une attente ou une route terminale n’occupe pas le créneau d’exécution des autres travaux.

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

Le timer existant du scheduler utilise ce fichier v2 et reste actif. Le fichier installé dans `~/.config/systemd/user` était resté sur v1 malgré le service versionné en v2 ; il a été remplacé par la copie versionnée puis rechargé avec `systemctl --user daemon-reload`. Le passage réel `--prepare-only` du 15 octobre à 08:24 CEST a retrouvé les trois candidats sans preuve nouvelle, zéro tâche IA nouvelle et zéro appel v2. Le prochain tick du timer était prévu à 08:33:56 CEST. Le timer et le protocole de l’observation ETH restent inchangés.

À l’arrivée du bilan final, le scheduler contrôle sa décision déterministe et son contenu sémantique. `data_insufficient` ou une décision sans question nouvelle devient `analysis_skipped` avec motif et action persistés, sans appel. Sinon, il scelle une nouvelle tâche 67f7 liée à l’empreinte du bilan et à ses échantillons de fills, dans le pilote v2. Le tick suivant utilise `population_runtime` pour proposition et critique (au plus deux appels), puis le scheduler existant exécute toute résolution locale déjà prise en charge. Le journal distingue la préparation du paquet, l’analyse et la résolution. Les erreurs/interruption deviennent techniques sans retry. Une issue favorable ne promeut pas un paper. Le scheduler vérifié le 15 octobre à 08:24 a trouvé l’observation toujours `observing`, sans bilan `final_24h` ; seule l’étape `checkpoint_6h` est persistée. La file conserve donc `waiting_deadline` jusqu’à la fin figée, le 15 octobre à 15:00 UTC. Le passage réel n’a ni modifié l’observation ni appelé le runtime.

## Projection bornée du bilan ETH

`eth_report_projection.py` fournit une projection commune à la file et au paquet runtime. Elle recalcule les effectifs, médianes, sensibilités d’âge, frais signés et quantités sur tous les fills, puis les ventile par jour UTC, maker/taker/inconnu et ouverture/réduction/inversion/inconnu. Elle résume la couverture REST, les cotations BBO/l2Book, les gaps, polls, santé du flux et télémétrie. Les exemples sont séparés des agrégats : au plus deux par strate jour × exécution × effet de position, choisis par hash d’identité stable sans examiner prix, frais ou markout. Les empreintes et références renvoient au rapport complet et aux observations sources, restés dans leur stockage existant.

La vérification hors ligne a projeté le rapport réel `checkpoint_6h` du 67f7/ETH. Ce n’est pas le bilan final et il n’a pas été soumis au runtime. Le rapport persisté (26 901 871 caractères) comprend 4 617 771 caractères de fills et 21 505 121 de couverture, dont 107 897 références de cotations. La projection en fait 47 755 caractères, avec les statistiques de 2 031 fills et 12 exemples. En recomposant le paquet complet avec l’historique autorisé et la question du pilote v2, la taille est 89 029 caractères ; le prompt de proposition exact est 93 466 caractères. Les limites restent respectivement 225 000 et 260 000 caractères. Le rapport intermédiaire et son empreinte n’ont pas changé.

Le parcours simulé utilise 4 000 fills répartis sur une journée UTC et 12 000 références de cotations : l’entrée dépasse 225 000 caractères, tandis que la file, le paquet complet avec historique et le prompt restent sous leurs plafonds. Proposition et critique sont simulées ; leurs deux prompts passent le contrôle runtime par caractères. Aucun appel réel n’est effectué.

## Vérifications et limite opérationnelle

Tests ciblés : 54 tests réussis dans `test_eth_report_projection`, `test_research_work_queue`, `test_population_pilot`, `test_population_runtime` et `test_population_local_join`. Ils couvrent attente/échéance, motif d’insuffisance sans appel, budget épuisé, cohérence des empreintes persistées, persistance/réouverture, rejeu idempotent, sélection d’exemples indépendante des résultats, volume supérieur à une journée, tailles paquet/prompt sous limites, déduplication sémantique jusque dans la file (un contexte enrichi crée un nouvel élément ; un horodatage de sérialisation seul retrouve le même), un bilan simulé parcourant sealing → proposition → critique → décision persistée → reprise sans nouvel appel, et un échec technique local qui laisse traiter la tâche suivante. Le passage réel du 15 octobre n’a effectué aucun appel IA.

Les tickets YouTrack concernés n’étaient pas accessibles par un connecteur dans cette session ; ce rapport et le commit gardent la preuve locale. L’observation demeure inchangée jusqu’au 15 octobre 15:00 UTC. Son bilan final déclenchera le traitement installé au prochain tick du scheduler. Le jugement sur la suite après la décision IA et toute transition vers une nouvelle expérience restent humains ; aucun paper ni ordre n’est automatique.
