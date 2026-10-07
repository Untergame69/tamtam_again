# Compte rendu intermédiaire — 7 octobre 2026

Objectif actif, non terminé. Ce relevé sert à la revue des incréments ; il ne
constitue pas l'approbation finale indépendante demandée.

## État livré dans ce premier incrément

- Baseline métadonnées : 681 candidats, 10 suivis, 8 plans, 3 variantes,
  aucune évaluation ni session paper au relevé initial.
- Télémétrie additive séparée `data/tamtam.telemetry.sqlite3` : tentatives REST,
  erreurs/reprises, poids réservé, borne calculée depuis réponses, temps et bytes.
  Aucun contenu de réponse ni adresse dans cette base de mesures.
- Réservation locale partagée via transactions SQLite, budget 900 poids/minute.
  Le poids réellement facturé et la consommation des autres outils/IP sont inconnus.
- Mesures WS par fenêtre : frames, bytes, lag de flush, taille de file,
  subscriptions envoyées, BBO reconnus, utilisateurs et reconnexions.
- Correction du supplément de poids non documenté sur ledger non-funding.
- Correction mémoire : requête de sélection des abonnements limitée aux
  observations récentes, curseur itératif et exclusion des anciens fills avant
  déduplication. Les choix restent fondés sur l'activité des dernières 24 h.
- Registre de découverte indépendant, provenance multiple, couverture explicite,
  échantillonnage déterministe d'adresses uniques (pas un score au nombre de fills).
- Sonde réelle 45 secondes, BTC/ETH/SOL/SP500/GOLD : 286 nouveaux candidats,
  967 candidats au total (957 non suivis, 10 suivis). Zéro slot utilisateur
  consommé par cette sonde. Aucun marché pilote consommé par la sonde et
  aucune adresse appartenant à un plan réel ajoutée depuis les flux de sonde.

## Preuves et mesures

- `baseline-20261007.json` : périmètres, endpoints, cadences, métadonnées pilotes.
- `capacity-initial-20261007.json` : mesures initiales, fenêtres et hypothèses
  de scénarios. La charge de démarrage/rattrapage reste mêlée à l'incrémental.
  Il faut des cycles complets et une classification avant toute capacité promise.
- `discovery-probe-20261007.json` : connexions reconnues, marché et couverture,
  règle/limite d'échantillonnage et candidats nouveaux par fenêtre.
- 76 tests passent : anciens 66 + nouvelles garanties quota/métriques,
  causalité/provenance/déduplication/exclusion pilote et filtrage historique.
- 154 tentatives REST mesurées au contrôle ponctuel, aucune HTTP 429.
- Dernière fenêtre WS au contrôle : 4852 frames et 1,79 Mo en 43,33 s,
  110 abonnements envoyés, 30 BBO reconnus, 10 utilisateurs, une connexion.
  Lag maximum de flush 1,15 s ; pic 369 messages dans la file applicative.
  Cela ne mesure pas la totalité des buffers réseau/bibliothèque.
- Mémoire systemd au contrôle après correction : 305 Mo ; environ 4,3 Go au
  baseline et 5 Go après redémarrage sans la correction. Mesures ponctuelles,
  pas encore une comparaison sous charge identique pendant plusieurs heures.
- Comparaison explicite SQLite : 8 hashes de plans, 3 specs et 3 critères
  strictement identiques au baseline. Aucun événement réservé exporté pour
  concevoir cette évolution ; aucune nouvelle validation économique annoncée.

## Services et risques opérationnels

Deux redémarrages du seul collecteur projet pour activer instrumentation puis
correction mémoire. PID courant au contrôle : 447350, service actif.
Les timers recherche et paper ne sont pas modifiés. Les interruptions et sessions
restent archivées ; aucune exemption aux contrôles de continuité des pilotes.
Aucun ordre réel, abonnement payant, wallet, VPS ou changement de réseau.
Coût d'achat engagé : 0. Les ressources et quotas du serveur existant sont utilisés.

## Travaux restants — portée intégrale conservée

| # | État | Reste à prouver/livrer |
|---|---|---|
| 1 | Partiel | Diagnostic consolidé après mesures et dépendances actualisées |
| 2 | Partiel | Rattrapage/incrémental, cycles complets, capacité soutenable et croissance |
| 3 | À faire | Ordonnanceur REST >10, inventaire distinct de tous les états |
| 4 | Partiel | Découverte continue/diversifiée, rapprochement provenance classement |
| 5 | À faire | Inventaire modes, tous dex/spot, sous-comptes documentés |
| 6 | À faire | Périodes comparables, devises, flux, réconciliation et inconnues |
| 7 | À faire | Descripteurs et mécanismes de marché sans présumer une stratégie |
| 8 | À faire | Allocation progressive, cohortes et témoins causaux |
| 9 | À faire | Profils d'expériences justifiés et sensibilités |
| 10 | À faire | Contrat d'extension, état mécanisme non supporté et multi-actifs |
| 11 | À faire | Boucle continue, surveillance, suspension/remplacement/reprise |
| 12 | À faire | Évaluation de la procédure adaptative et références |
| 13 | À faire | Bibliothèque de recherche avec accès temporels protégés |
| 14 | À faire | Comparaison chiffrée REST/flux/IP/fournisseur/nœud sans achat |
| 15 | Partiel | Tests incrémentaux faits ; recette complète/doc/CR indépendant restant |

## Reproduction et retour arrière

```sh
.venv/bin/python -m unittest discover -s tests -q
python3 scripts/research-baseline.py --db data/tamtam.sqlite3 --output /tmp/baseline.json
PYTHONPATH=src .venv/bin/python scripts/collection-capacity.py --telemetry data/tamtam.telemetry.sqlite3 --output /tmp/capacity.json
```

La sonde est une mutation autorisée du registre ; ne pas la relancer pour simplement
relire son résultat : lire le JSON livré. Chaque nouveau lancement observe une
nouvelle fenêtre et crée de nouvelles preuves.

Retour arrière : arrêter le seul collecteur, revenir au code fdb1264 (ou annuler
les commits ciblés dans l'ordre inverse), redémarrer avec l'unité sauvegardée dans
`data/rollback/continuous-20261007/`. Conserver la télémétrie, les tables de
provenance et les candidats : anciennes versions peuvent ignorer ces tables.
Ne pas restaurer la base entière et ne pas supprimer les nouvelles observations.
Les unités installées n'ont pas changé ; le code chargé par le service a changé.
