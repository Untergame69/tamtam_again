# Observation prospective publique 67f7 / ETH — v1

## Protocole scellé

- Identifiant : `67f7-eth-public-observation-24h-20261014-v1`
- Empreinte : `d6a499b1d25af199b65b791635b01345aa81d269f8563b31204ee3a0f9290ce1`
- Départ : **2026-10-14 15:00 UTC / 17:00 Europe-Paris**
- Premier bilan : **2026-10-14 21:00 UTC / 23:00 Europe-Paris**
- Fin irrévocable : **2026-10-15 15:00 UTC / 17:00 Europe-Paris**
- Aucun prolongement ni promotion paper, quel que soit le résultat.

Question principale : les fills taker qui réduisent la position ETH ont-ils un
markout directionnel médian à 60 secondes différent des fills taker qui ouvrent
ou augmentent la position ? Un quote antérieur doit être strictement antérieur
au fill, frais et taille sont conservés, et une inversion est séparée avec
quantités de fermeture/ouverture arithmétiques. Elle n'est pas reclassée comme
une simple réduction ou ouverture. Le premier milieu BBO ou meilleur niveau
l2Book dans les 5 secondes après la cible est une mesure de conséquence, jamais
un signal rétrospectif. Un quote pré-fill âgé de plus d'une seconde ne contribue
pas au markout principal ; les couvertures sont aussi décrites à 100 ms, 5 s et
30 s. Ces seuils reprennent la comparaison exploratoire déjà documentée.

Le complément post-réception prend comme origine l'arrivée locale de la page
REST qui rend le fill visible à notre collecteur. Il mesure ensuite le mouvement
à 60 secondes à partir du dernier quote localement reçu avant cette page, avec
un dépassement maximal de 5 secondes et un temps source strictement ultérieur
au quote de base. Ce n'est pas l'heure de réception de
l'exécution chez le trader. Les résultats distinguent quatre états : signal
exploratoire favorable, défavorable, indéterminé ou données insuffisantes. Une
médiane descriptive ne constitue pas une preuve statistique : les fills sont
dépendants et la fenêtre ne dure qu'un jour.

## Acquisition et temps

Le collecteur partagé fournit déjà BBO et l2Book ETH via WebSocket. Le compte
67f7 n'est pas ajouté à la limite WebSocket de dix utilisateurs. Ses exécutions
sont lues par une page REST `userFillsByTime` toutes les cinq minutes, avec une
minute de recouvrement et déduplication par `tid`. Les pages saturées, échecs,
réponses, hashes, identifiants, demandes et réceptions restent persistés. La
requête utilise le `Telemetry` partagé (`INFO_WEIGHT_LIMIT_PER_MINUTE=900`) ;
le plafond global n'est pas modifié. L'endpoint REST est au niveau du compte et
peut renvoyer d'autres coins ; l'analyse ne retient que les fills ETH.

Pour chaque quote, l'artefact conserve l'heure d'événement, l'heure locale de
réception de frame, l'heure d'archivage, le canal, la connexion, les meilleurs
prix/quantités et la référence/hash du lot. Les latences événement→réception et
réception→archivage sont descriptives ; les horloges ne sont pas supposées
synchronisées. Les heartbeats et acknowledgements indiquent la santé du flux,
pas la continuité du carnet. Les événements BBO/l2Book et les lacunes observées
restent l'évidence de marché.

## Automatisation et reprise

`tamtam-again-eth-observation.timer` déclenche un service one-shot isolé toutes
les 30 secondes, sans prendre le verrou du scheduler de recherche. Les polls,
erreurs, interruptions de worker, rapports checkpoint/final et routes sont
stockés dans SQLite. Chaque rapport est immuable par étape ; son rejeu retourne
la même ligne. Une panne de calcul produit un rapport diagnostique insuffisant.
À l'échéance finale, le worker fige le rapport puis arrête son propre timer ; le
collecteur partagé reste actif.

## Démarrage observé

À 2026-10-14 15:00:00 UTC, systemd a lancé le service ; il est sorti en succès
à 15:00:03.194 UTC. La base lie le lancement réel à `actual_started_ms=1791990000373`
(15:00:00.373 UTC) et le run est en état `observing`. La première page
`userFillsByTime` a répondu HTTP 200, 120 unités de poids réservées, zéro retry,
zéro fill ETH sur les premières millisecondes, et `complete=1`; sa référence
brute est `raw_observations:50804540` avec hash
`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

Après le départ, des événements BBO et l2Book ETH sont arrivés sur la connexion
`f7189c7d363a49f9bcb53fc388b75d7e`. Exemples vérifiés : BBO
`raw_observations:50809535` (événement 15:00:35.032 UTC, reçu 15:00:35.588,
archivé 15:00:35.623, hash `9c6b81adbd2a319d8a07712ded85619fed196bc90f79fd97960cdc4b77c6d03a`) ;
l2Book `raw_observations:50809492` (événement 15:00:34.895, reçu 15:00:35.317,
archivé 15:00:35.398, hash `420b3ae130a1cdbc84e5a21a5d162d6f8de0378e2af432b502725e75de085cc8`).
Le deuxième tick automatique s'est terminé avec succès sans refaire la requête ;
le prochain poll REST est prévu cinq minutes après le précédent. Aucun bilan
6 h n'existe encore à ce contrôle.

Commandes de contrôle :

```sh
systemctl --user status tamtam-again-eth-observation.timer tamtam-again-eth-observation.service
journalctl --user -u tamtam-again-eth-observation.service --since '2026-10-14 16:55:00 CEST'
```

Les rapports structurés sont dans `eth_observation_reports`, le prochain état
dans `eth_observation_routes`, et les polls/pages bruts dans
`eth_observation_polls` et `raw_observations`. Le chemin direct de consultation
reste la base locale `data/tamtam.sqlite3`; aucune archive n'est nettoyée.

```sh
sqlite3 data/tamtam.sqlite3 "select protocol_id,status,actual_started_ms,finalised_ms,next_poll_ms,diagnostic_json from eth_observation_runs where protocol_id='67f7-eth-public-observation-24h-20261014-v1';"
sqlite3 data/tamtam.sqlite3 "select stage,json_extract(report_json,'$.decision'),json_extract(report_json,'$.input_fingerprint') from eth_observation_reports where protocol_id='67f7-eth-public-observation-24h-20261014-v1' order by created_ms;"
sqlite3 data/tamtam.sqlite3 "select status,count(*),sum(record_count),sum(complete=0) from eth_observation_polls where protocol_id='67f7-eth-public-observation-24h-20261014-v1' group by status;"
```

Le test d'intégration utilise un needs-data 67f7/ETH déjà présent en fixture :
un tick de l'observation y laisse le processus en état `observing`, puis le
scheduler local réalise la jointure et l'analyse économique sans appel IA. Cela
vérifie que l'attente de l'échéance ne monopolise pas le scheduler.
