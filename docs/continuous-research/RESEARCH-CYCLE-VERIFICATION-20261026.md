# Vérification de la boucle de recherche — 26 octobre 2026

Branche `mission/research-cycle-verification-20261026`, créée depuis
`b1797b10b83db7edc1ef86d8f60ca056904f6ed7`. Le checkout principal n’a pas été
modifié. Le dépôt `tamtam_again` ne contient pas d’`AGENTS.md` à sa racine ; les
instructions fournies pour cette mission ont été suivies.

## Résultat de l’intégration isolée

Le nouveau test `tests/test_population_research_cycle_integration.py` utilise une
base SQLite et un répertoire d’artefacts temporaires. Il insère des observations
brutes de test, puis appelle les points d’entrée habituels : l’observateur
construit et persiste le rapport, la file prépare le paquet et le contrat, le
scellement v2 autorise la tâche, le runtime valide deux réponses fournisseur
simulées, et le scheduler résout les références locales et actualise la mémoire.
Le test compare l’artefact gzip écrit, y compris au rejeu, à l’enregistrement
SQLite correspondant ; ces écritures restent dans son dossier temporaire.

Le chemin observé est :

1. Rapport final ETH généré par `eth_prospective_observation.tick` depuis des
   lignes brutes de test.
2. `research_work_queue.tick` produit un paquet scellé et son contrat local ; le
   test vérifie leurs références au rapport persisté.
3. Deux réponses simulées produisent une demande bornée de données et une route
   `local_archive_analysis_required`.
4. `population_scheduler.tick` exécute la résolution depuis les références du
   contrat, enregistre l’artefact, crée la route courante
   `local_archive_analysis_complete` et révise la mémoire sans promouvoir la
   stratégie.
5. Une tâche générale admissible au cutoff futur explicitement simulé, après le
   délai existant de 24 h, est scellée. Son paquet contient la révision de mémoire
   et la référence typée à la résolution.
6. Le rejeu ne rappelle ni le fournisseur ni les lecteurs d’archives, ne crée
   aucun calcul ou artefact supplémentaire, ne change pas la mémoire et conserve
   le fingerprint du paquet initial.

Le test séparé ajouté rejette un premier candidat via une réponse runtime
simulée et confirme que le scheduler scelle le candidat suivant.

## Scénarios ciblés

- Archives partielles, cotations absentes, source de rapport absente et opération
  hors contrat : `test_population_local_archive_resolution`.
- Plafond v2 épuisé, épuisement non renouvelable, tâche suivante après rejet,
  interruption sans retry et reprise/routage : `test_research_work_queue`,
  `test_population_pilot`, `test_population_runtime` et le nouveau test de rejet.
- Conservation de l’ancienne route, sélection de la seule route courante,
  révision de mémoire consommée par le paquet suivant et rejeu idempotent : le
  nouveau test et `test_population_resolution_memory`.
- Génération du rapport final, données insuffisantes, interruption de collecte
  simulée et rejeu du rapport : `test_eth_prospective_observation`.

Commande reproductible, depuis la racine du worktree :

```sh
PYTHONPATH=src python3 -m unittest \
  tests.test_population_research_cycle_integration \
  tests.test_eth_prospective_observation \
  tests.test_population_local_archive_resolution \
  tests.test_population_pilot \
  tests.test_population_resolution_memory \
  tests.test_population_runtime \
  tests.test_research_work_queue -v
```

Résultat : **62 tests réussis** en 22,42 s. `git diff --check` passe.

## État opérationnel lu séparément

La base active `/home/Untergame/tamtam_again/data/tamtam.sqlite3` faisait 165 Go
à la lecture. Les requêtes ont d’abord listé les tables et colonnes utiles, puis
agrégé uniquement les registres de tâches, appels, files courantes et
observations ; aucun dump ni scan des archives n’a été lancé. Snapshot
SQLite read-only au cutoff `2026-10-26T13:02:45.596Z` :

- tâches population : 8 `hypothesis_recorded`, 4 `needs_data`, 2 `suspended` ;
- autorisations pilote : 3 tâches 67f7, 2 a880, 1 be504 dans leurs états
  historiques ; appels : 6 `result_validated`, 2 `structurally_revalidated`,
  1 `response_rejected` ;
- file courante : 4 `completed`, 3 `technical_required`, 9 `waiting_data` ;
- une observation ETH finalisée.

Pour la tâche ETH historique `501c352c…aece`, la ligne job reste
`hypothesis_recorded`, tandis que la dernière route historique est
`completed` et la file courante est `completed`. Les anciennes routes sont
conservées. Cela distingue le statut du résultat runtime de la décision
opérationnelle courante.

Le compte rendu opérationnel daté du 26 octobre indique aussi que le dernier
tick `--prepare-only --max-jobs 1` n’a fait aucun appel modèle ni nouvelle
résolution et a retourné `no_admissible_candidate`. La voie générale avait 0
candidat qualifié, autorisé et budgété. La préparation de ce test ne réactive
donc pas une tâche réelle.

L’accès au bus systemd est refusé dans cet environnement (`Failed to connect to
bus: Operation not permitted`) ; l’état actif du timer n’a pas pu être constaté.
La lecture directe des tickets YouTrack n’est pas disponible ici non plus ; les
articles locaux ciblés `TAMTAM_AGAIN-A-1` et `TAMTAM_AGAIN-A-2` renvoient l’état
courant au ticket 12, sans export local de son journal.

## Conclusion pour Luna

Le parcours assemblé passe sur la base temporaire, jusqu’à la consommation de la
mémoire par une nouvelle tâche admissible. Aucun défaut de raccordement n’a été
reproduit dans ce scénario. La limite opérationnelle prouvée est en amont : au
cutoff vérifié, aucune nouvelle tâche réelle n’est admissible. Le compte rendu
`ETH-LOOP-RECHECK-20261026.md` documente déjà l’absence d’un état
`descriptive_research_readiness` dans la voie générale ; cette vérification ne
change ni cette règle ni les autorisations existantes.

La démonstration synthétique ne prouve pas le fonctionnement live du timer,
l’exécution réelle du fournisseur, ni l’existence d’un prochain candidat
autorisé. Aucun appel IA réel, collecte, paper, ordre, changement de quota,
permission, service ou base active n’a été déclenché.
