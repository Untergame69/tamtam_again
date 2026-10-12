# Compte rendu pour revue externe — reprise TAMTAM-164452b

Date : 12 octobre 2026. Politique historique v2.0. Cutoff immuable : `1791789394195` ms (`2026-10-12T07:16:34.195Z`). Rapport descriptif : [JSON complet](historical-selection-20261012/report.json), [classement Markdown](historical-selection-20261012/report.md), [CSV](historical-selection-20261012/accounts.csv).

## Résultat et limites

Au cutoff, 153 comptes autorisés ont été analysés. Le classement comprend 3 présélections courbes+activité, 9 PnL déclarés positifs en attente d'activité fréquente, 16 positifs mais concentrés ou trop clairsemés, 97 insuffisamment documentés et 28 négatifs sur au moins un horizon mesuré. Ces états sont mutuellement exclusifs. Ils ne valident ni rendement net ni stratégie. Pour chacun des 153 comptes, `economic_validation` reste faux et `economic_research_readiness` est bloqué. Un dossier IA doit aussi disposer d'une validation économique indépendante approuvée et référencée.

Le rapport du 9 octobre, ses CSV/SVG et ses décisions persistées restent intacts. Le rapport du 12 octobre utilise la nouvelle version et ne modifie pas l'interprétation du rapport ancien. Les décisions v2 sont ajoutées de façon idempotente.

## Corrections de revue

### R1 — attribution mensuelle et hebdomadaire

Les buckets partagent les mêmes bornes UTC échantillonnées ; les changements entre buckets sont attribués une seule fois à l'intervalle suivant. Aucun point n'est interpolé. Le retard maximal est de sept jours ; le gap maximum est de 15 jours par mois et 10 jours par semaine. Les buckets sans limites fiables, couverture suffisante ou nombre minimal d'échantillons restent inconnus. Chaque résultat expose le delta d'horizon, la somme attribuée, le résidu non attribuable, le nombre de périodes mesurées/inconnues et la complétude. La concentration n'est calculée que si la couverture est complète. Version de politique : `historical-curves-v2.0`; les anciennes décisions restent conservées sous leur ancienne version.

### R2 — activité observée, pagination et rétention

La couverture utile est construite à partir de `covered_until_ms` (ou de la borne de continuation archivée), en fusionnant les plages qui recouvrent la fenêtre récente. Les pages éloignées ne rendent plus une couverture récente insuffisante. Les états de pagination sont conservés séparément ; aucune pagination terminée ne vaut preuve de rétention API complète. Les fills dédupliqués établissent une borne inférieure : 20 fills sur quatre jours UTC donnent un statut de fréquence observée, sans exiger une plage continue de 25 jours. L'échantillon ne prouve pas une cadence mensuelle stable ni des décisions indépendantes.

### R3 — cutoff des preuves et reprise des réservations

Pour un candidat non scellé, le gate vérifie qu'au moins une observation compte dans l'intervalle `(dernière requête, cutoff du rapport]`. Une observation arrivée après le cutoff ne rend plus invalide une preuve plus ancienne incluse au rapport. Pour une réservation déjà scellée, la reprise valide l'empreinte du paquet, son adresse, réseau, empreinte de recherche et disponibilité antérieure à la réservation, ainsi que la décision historique au cutoff de la réservation. Elle ne demande pas de données arrivées après la création de cette réservation. Le plafond global existant reste appliqué.

### R4 — présélection et qualification économique

Le statut `credible_deep_dive_candidate` reste une présélection descriptive sur les courbes et l'activité. Il ne suffit plus à autoriser l'IA. Le gate exige simultanément `economic_validation=true`, `economic_research_readiness.status=approved_for_re`, l'éligibilité explicite et des références de preuves. Les rapports de ce lot ne portent aucune approbation économique.

Le compte `0x87f9cd15f5050a9283b8896300f7c8cf69ece2cf` a d'abord été contrôlé contre les listes protégées et les libérations historiques au cutoff ; il n'était pas protégé et l'historique était libéré avant lecture des deux payloads de ledger référencés. Pour les limites `1791458734427`–`1791479504849`, les points natifs utilisables les plus proches sont à 8,1 s avant le début et 2,6 s avant la fin :

| Série native | Valeur début | Valeur fin | Changement observé |
|---|---:|---:|---:|
| `allTime.pnlHistory` | 19 412 287,119326 | 18 145 133,667188 | −1 267 153,452138 |
| `allTime.accountValueHistory` | 44 415 017,007359 | 47 602 545,830967 | +3 187 528,823608 |
| `perpAllTime.pnlHistory` | −26,687063 | −26,687063 | 0 |
| `perpAllTime.accountValueHistory` | 1 178 399,352937 | 5 634 443,352937 | +4 456 044,000000 |

La tranche comptable précédente rapportait un changement de capital perp de `+4 447 750` USDC ; le changement natif `perpAllTime.accountValueHistory` diffère de `+8 294`. Les événements `userFunding` référencés (`raw_observations:12393255`) sont vides. Parmi les événements ledger externes USDC normalisés de la fenêtre (`raw_observations:12393256`), 162 totalisent `+1 746 631` net (`+5 271 804` entrants, `−3 525 173` sortants). La couverture ledger n'est pas prouvée. Ces valeurs ne réconcilient ni les différents périmètres de courbe, ni la variation de la tranche comptable ; ce cas reste sans validation économique.

## R5 — file historique légère et quotas

La file utilise les 8 504 candidats du registre existant : 7 456 issus des trades publics archivés et 1 048 des snapshots leaderboard. Un rang SHA-256 déterministe par adresse et graine assure l'ordre uniforme, sans PnL ni taille de compte. Les candidats protégés ou non libérés sont différés avant toute lecture/sauvegarde de payload ; la protection est vérifiée à nouveau après l'appel. Les observations portfolio déjà disponibles sont réutilisées. Les anciens exclus ne sont pas supprimés.

Politique versionnée `historical-curve-queue-v1` : au plus 4 requêtes `portfolio` toutes les 15 minutes, 6 essais maximum et temporisation de 6 heures après erreur. La charge moyenne réservée pour cette file est 5,333 poids/minute, à l'intérieur du budget local partagé de 900/minute. La mesure telemetry avant ce rapport donne 849,08 poids/minute sur les 60 dernières minutes et aucun HTTP 429. La limite officielle Hyperliquid est 1 200 poids/minute par IP ; les appels `info` ordinaires comptent pour 20 poids chacun ([documentation officielle des limites](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)). Le limiteur local reste la contrainte appliquée par tous les collecteurs.

La file a inséré 8 504 entrées. Le premier passage manuel a réussi avec 4 demandes et le premier passage périodique avec 4 demandes, zéro échec et zéro appel IA. À la publication du rapport, 8 comptes étaient en `fetched` et 8 496 en attente. Le timer systemd utilisateur est activé ; la cadence configurée est 15 minutes. Le classement lui-même a relu 61 030 payloads archivés, émis zéro requête fournisseur et persisté 153 décisions.

Les lectures de quota proviennent du compteur partagé : 5 min 4 024 poids (804,80/min), 15 min 12 682 (845,47/min), 60 min 50 945 (849,08/min), 24 h 1 229 464 (853,79/min), aucun HTTP 429 et aucune reprise enregistrée dans ces fenêtres. L'estimation ne promet pas un débit maximal futur ; les collecteurs existants gardent priorité via le même limiteur.

## Vérification et état d'exécution

Les 454 tests du dépôt passent (suite complète après le dernier correctif : 44,700 s). Les nouveaux tests reproduisent l'attribution d'un saut de frontière, les périodes inconnues, l'ancienne page de fills hors fenêtre, l'activité observée malgré une pagination non exhaustive, une observation postérieure au cutoff, la reprise d'un paquet scellé immuable, l'exclusion des entrées de file ajoutées après le cutoff et les limites de la file (4 appels, rang stable, compte protégé non interrogé et report sans consommation d'essai). Aucun test n'appelle l'API ou un modèle.

Aucun nouvel appel IA de recherche, aucune nouvelle enveloppe budgétaire et aucun ordre n'ont été créés pour ce lot. Le plafond de recherche existant est resté inchangé. Les tickets TAMTAM_AGAIN-6 et TAMTAM_AGAIN-12 ont été relus avec le client local ; des commentaires de suivi doivent référencer ce rapport et le commit/push.

## Fichiers et reproduction

Le classement se reconstruit sans réseau avec :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-historical-screen.py \
  --db data/tamtam.sqlite3 --as-of-ms 1791789394195 \
  --output-dir docs/continuous-research/historical-selection-20261012
```

La file périodique est décrite dans `config/historical-curve-queue-policy.json`, exécutée par `scripts/population-historical-queue-tick.py` et les unités `systemd/user/tamtam-again-historical-queue.{service,timer}`. Les fichiers SQLite locaux ne sont pas publiés dans Git.
