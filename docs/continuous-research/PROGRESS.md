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

## Deuxième incrément — population REST indépendante

Commit f19cd26 : population-policy v1, ordonnanceur à bail transactionnel,
32 comptes REST supplémentaires sélectionnés par adresse avec graine versionnée.
Les 10 comptes directs et les adresses des plans réels sont exclus de cet
élargissement. Cadence pilote 1 h, bornée 5 min–6 h ; réserve de rétention
choisie à 50 % des 10000 fills. Paramètres exploratoires configurables,
ni garantie de complétude historique ni seuils économiques.

Inventaire public : mode userAbstraction, userRole (poids 60), subAccounts,
spot, portfolio, liste des dex et clearinghouseState pour chaque dex.
Aucun collatéral de dex n'est additionné. Le probe de fills est une page unique,
explicitement incomplète ; pagination/rattrapage complets restent à intégrer
à la qualification périodique. Le signal follower n'accepte pas cette source REST.

82 tests passent : population >10, baux concurrents, reprise d'une interruption,
rejet d'une ancienne complétion, rétention, compte unifié multi-dex sans addition
de capital et curseur à la borne de requête, pas à l'heure de traitement ultérieure.
Premier tick réel livré dans population-first-tick-20261007.json : compte unified,
11 dex publics interrogés, performance non qualifiée. Deux inventaires achevés
au contrôle suivant, 32 comptes planifiés et dix abonnements directs conservés.

Le premier tick était déjà exécuté quand le test a identifié l'écart entre
borne de fills et fin du traitement : le curseur a été reculé à la borne réelle
avec un enregistrement population_state_corrections. L'essai et son rapport
originaux restent immuables. Cette correction conserve la fenêtre intermédiaire
au lieu de la perdre ; elle ne déclare pas de nouvelles observations complètes.

Nouveau service/timer local tamtam-again-population (oneshot, un job/tick,
prochain tick 60 s après fin, timeout/bail 600 s) installé et activé.
Même base de quota que le collecteur existant. L'ajout peut allonger les cycles
REST existants ; la capacité doit être revue sur mesures avant élargissement.
Aucun redémarrage du collecteur nécessaire pour cette étape.

Retour arrière propre à cet incrément : arrêter/désactiver
`tamtam-again-population.timer`, arrêter son service, conserver tables,
observations et tentatives. Les anciens collecteurs et les pilotes continuent.
Les fiches de périmètre, la comptabilité comparable et les autres exigences
restent à terminer ; les comptes inventoriés ne sont pas déclarés rentables.

## Troisième incrément — rapprochement comptable et adaptateur réel

- dbfc6ea : reducer de période explicite, frais/remises et conversions causales,
  flux internes/externes, capital/latent aux bornes, écarts de réconciliation,
  Modified Dietz estimatif et TWR/drawdown échantillonné seulement si calculables.
- Adaptateur population-only : garde des adresses réservées avant lecture, scopes
  séparés, références d'observation et disponibilité. Les devises HIP-3 et le spot
  incomplets ne reçoivent pas une valorisation inventée.
- Rapport réel de sept comptes sur une période commune :
  population-accounting-20261007.json ; aucun rendement validé. Funding/ledger,
  valorisation consolidée, bornes et complétude encore insuffisants.
- 96 tests passent, incluant absence de lecture des autres sources, refus des
  pilotes, page courte non assimilée à une preuve et doublons de réception d'une
  même exécution sans double compte ni faux conflit.
- Documentation officielle des modes de compte relue : en mode unifié, prendre
  le capital d'un perp dex comme capital global n'est pas valide. Les anciens
  ratios restent des observations non qualifiées tant que le mode est inconnu.

La tâche 6 reste partielle : les fondations de calcul et le diagnostic réel sont
livrés, mais il faut normaliser et collecter les preuves manquantes, démontrer
la valuation par mode et tester des cas réels contrastés réconciliables.
Aucune modification des règles de promotion ni des périodes réservées.

## Quatrième incrément — historiques bornés et reprenables

Les fills, fundings et ledger non-funding disposent désormais de curseurs
indépendants, avec trois pages maximum par endpoint/passage. Les pages précèdent
l'avancement des curseurs ; reprises inclusives, backlog à borne stable et baux
empêchent les sauts après interruption et les écritures d'un ancien worker.
Une saturation au même timestamp est explicitement bloquée, sans saut de 1 ms.
La télémétrie distingue ces historiques entre rattrapage et incrémental.

105 tests passent. Contrôle réel achevé : 72 événements de funding, zéro fill
et zéro ledger retournés pour ce compte sur la fenêtre demandée. Ce sont des
comptes de réponses, pas une preuve d'absence d'activité ou de complétude.
14 comptes distincts ont un inventaire achevé au contrôle ; ils ne sont pas
économiquement qualifiés. Preuve : population-history-control-20261007.json.

Le collecteur et le timer population sont actifs, le passage réel a terminé
sans erreur. Aucun redémarrage du collecteur, aucun changement des pilotes.
La migration ajoute population_history_cursors ; les pages restent incomplete
avec rétention inconnue. Procédure et rollback : POPULATION-HISTORY.md.
Normalisation des transferts/funding et valorisation consolidée restent à faire.

## Cinquième incrément — événements comptables normalisés

Funding signé par instrument, dépôts et transferts selon frontière de l'adresse
normalisés et reliés aux observations. Les flux HyperCore restent distincts
des scopes perp, sans allocation arbitraire ni consolidation des sous-comptes.
Les devises HIP-3, retraits avec frais et autres mécanismes non établis restent
inconnus. Les contradictions sur une même identité sont conservées en diagnostic.

115 tests passent. Contrôle réel de 15 comptes sur bornes communes : deux scopes
avec funding observé non nul ; aucun événement ledger normalisé dans cette
fenêtre et aucune qualification économique. Preuve résumée dans
account-events-control-20261007.json, règles dans ACCOUNTING-CONTRACT.md.
Les mécanismes non supportés, la complétude des périodes, le collatéral et la
valorisation consolidée restent à terminer ; la tâche 6 reste partielle.

## Sixième incrément — métadonnées de collatéral causales

Catalogue public versionné, rafraîchissement partagé dans le worker population,
deux appels par heure configurée. Preuves de devise par token index/tokenId et
instrument, sans inférence par position dans les tableaux ni prix FX supposé.
L'adaptateur utilise uniquement une métadonnée disponible avant l'événement.

123 tests passent, dont garde contre métadonnées futures et réutilisation du
cache sans réinitialisation de disponibilité. Contrôle réel : 11 DEX et 535
instruments ; USDC, USDH, USDE et USDT0 rencontrés. Preuve et rollback :
collateral-control-20261007.json et COLLATERAL-CATALOG.md.
Anciennes périodes et pilotes non modifiés. La comptabilité reste partielle,
notamment valorisation, couverture, frais/transferts non normalisés et FX.

## Septième incrément — comportements observés

Profils causaux par marché, maker/taker/inconnu, tailles et rythmes, concentration
des notionnels observés, ordres multi-fills et excursions d'inventaire séparées
de la performance. Groupes multi-marchés descriptifs et questions explicites,
sans affirmation d'arbitrage. Intégration au rapport de chaque passage population
et commande d'analyse de toutes les pages archivées, protégée des pilotes.

131 tests passent après retrait des champs monétaires descriptifs. Contrôle réel final : 19
comptes, 9428 fills observés, 999 excursions d'inventaire ; couverture inconnue
et aucune validation. Preuves : behavior-control-20261007.json et
BEHAVIOR-PROFILES.md. Tâche 7 partielle : mécanismes de marché et trajectoire de
risque consolidée restent à livrer, ainsi que les autres exigences du Goal.

## Huitième incrément — mécanismes et précision d'exécution

Fiches depuis métadonnées publiques, intégrées aux inventaires population ;
535 instruments décrits avec limites explicites. Extension optionnelle des
nouvelles specs v2 : precision/lot/minimum et borne de levier du marché,
disponibilité causale et refus de comptabilité non-USDC. Les anciennes specs
ne sont pas modifiées et gardent leurs limites documentées.

139 tests passent après intégration dans les inventaires population.
Comparaison explicite baseline : huit plans et trois specs/critères identiques,
sans lecture brute réservée. Contrôle réel dans
market-mechanisms-control-20261007.json, procédure dans MARKET-MECHANISMS.md.
La liquidation exacte, marge isolée par tiers, références spécifiques HIP-3,
profils d'expériences et moteur multi-instruments restent à compléter.

## Neuvième incrément — familles expérimentales

Profils justifiés/bornés sur horizon, délai et taille, provenance et catégories
distinctes, échecs conservés et gel des combinaisons sur un nouveau plan.
Sélection unique sur comparaisons terminales passées, classement stress net PnL
fixé par contrat et refus de finale des autres variantes avant lecture pipeline
ou consommation de réserve moteur. Budgets existants conservés.

147 tests passent au premier contrôle ; recette synthétique complète huit
comparaisons et une finale dans une base temporaire. Aucun plan réel ajouté.
Preuves et rollback : EXPERIMENT-FAMILIES.md et experiment-recipe-20261007.json.
La tâche 9 reste partielle pour la calibration par mesures réelles ; allocation,
moteur multi-instruments, adaptation et autres tâches restent à terminer.

## Dixième incrément — premier moteur portefeuille expérimental

Contrat d'extension explicite et état unsupported_mechanism. Référence fixe deux
perps USDC avec comptabilité partagée, expositions agrégées, funding propre,
latences et santé par marché, IOC indépendantes, jambe manquante/partielle et
flatten après timeout. Journal versionné et reprise/idempotence vérifiées.

160 tests passent, y compris reconnexion invalidant la quote précédente. Recette portfolio-recipe-20261007.json
synthétique normal/stress et clôture de l'inventaire effectif après jambe absente.
Aucun plan réel ou session paper créé. Contract/rollback dans
HARNESS-EXTENSIONS.md. Tâche 10 partielle : validation réelle/N2, règles de lots,
marges/FX et collecte multi-marchés restent à intégrer. Goal complet conservé.
