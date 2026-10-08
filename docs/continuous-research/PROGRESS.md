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

## Onzième incrément — mémoire causale

Bibliothèque structurée et preuves typées, releases explicites de périodes
terminales selon politique versionnée, sans effacer résultat ou burn original.
Contrôles d'accès avant écriture/export, scope account-wide pour observations
multi-marchés, cutoff de création et taille bornée. Intégration optionnelle aux
futurs paquets de recherche, sans changement des jobs scellés.

169 tests passent. Contrôle réel metadata-only : un descripteur de population
archivé/exporté, aucune période pilote libérée, aucun nouveau dispatch IA.
Preuves/rollback : RESEARCH-MEMORY.md et memory-control-20261007.json.
Ingestion automatique/revue/utilité de la mémoire, procédure adaptative complète
et autres tâches restent à livrer. Goal demeure actif.

## Douzième incrément — allocation et témoins datés

Politique quotidienne configurable 12 exploration/12 approfondissement/4
uniformes/4 classement public, cap deux époques d'approfondissement, décisions
séparant états inconnus/blocages/adverse/performance/observabilité/reproductibilité.
Application aux slots REST sans dépasser 32 en présence de baux running,
retraits conservés et snapshots immuables. Références des cohortes dans les jobs.

175 tests passent. Cohorte réelle avec 970 décisions, quatre budgets remplis,
32 REST actifs, 20 retirés et dix directs préservés. Mesure 30 min avant activation :
847 poids réservés/min sur budget local 900, aucune 429 ; marge faible, charge de
rattrapage de la rotation à surveiller. Preuves/rollback ALLOCATION-POLICY.md et
allocation-control-20261007.json. Qualification économique, appariement des
témoins et évaluation de la sélection/adaptation restent à terminer.

## Rotation des marchés de découverte — 2026-10-07

Ajout de `discovery_rotation.select_markets` : calendrier déterministe indépendant des cohortes de comptes, entrelacement des DEX et rotation des instruments, exclusion des marchés réservés et délistés, refus de catalogues disponibles après la décision. Chaque sélection expose version, époque, références du catalogue et biais. Le budget concerne les marchés observés, pas une population uniforme de comptes.

Vérification : quatre tests ciblés passent (couverture de rotation, déterminisme, causalité du catalogue, univers vide/petit). Cette étape prépare la découverte continue ; aucun nouveau timer ni service activé. La connexion, les limites de tampon, la conservation des fenêtres sans activité et la recette réelle restent à intégrer.

## Sessions de découverte bornées — 2026-10-07

`discovery_runtime.collect_session` conserve chaque session et ses fenêtres sans activité, borne les octets et messages conservés, limite la file WebSocket, active le heartbeat du transport et journalise les erreurs par classe sans recopier leur texte. Exclusion des marchés réservés avant connexion et partition des messages par instrument. Couverture explicitement non exhaustive, provenance des participants séparée. Douze tests de découverte passent après correction du schéma de fixture. Aucun service supplémentaire activé ; raccordement au calendrier et recette réelle encore nécessaires.

## Découverte périodique activée — 2026-10-07

Script `discovery-tick.py` raccordé au catalogue public déjà collecté, sans appels REST supplémentaires. Recette réelle de cinq secondes : cinq marchés para:CIEN, xyz:AAPL, HYPER, io:GPRO, mkts:US500 ; 47 nouveaux candidats, 42 196 octets reçus, arrêt normal. Preuve dans `discovery-runtime-20261007.json`. Douze tests ciblés passent. Timer utilisateur `tamtam-again-discovery.timer` activé : sessions de 45 secondes, intervalle de 900 secondes après chaque terminaison, un maximum de cinq marchés et une connexion supplémentaire temporaire. Sessions et choix archivés en SQLite ; zéro abonnement utilisateur supplémentaire. Collecteurs et timer population constatés actifs avant activation.

Retour arrière : `systemctl --user disable --now tamtam-again-discovery.timer` puis `systemctl --user stop tamtam-again-discovery.service` ; conserver les observations et registres. La recette courte ne démontre pas une capacité soutenable ; les prochaines sessions nécessitent une mesure de charge. Le classement reste une seconde voie existante, mais son intégration complète au registre de provenance comparable reste à finir.

## Provenance comparable des deux sources — 2026-10-07

Classement intégré au registre discovery_windows/provenance : snapshot daté, rangs par fenêtre/métrique, règle de sélection et biais, sans recopier les métriques financières. Hook de collecte future et import du dernier snapshot par chaque tick découverte, sans redémarrer les collecteurs ni ajouter un appel réseau périodique. Contrôle réel ponctuel : snapshot c499aca36ae546b888fbf1aa1bdbe974, 47 345 lignes source, 70 candidats sélectionnés, 69 adresses avec provenance après exclusion des pilotes. Treize tests ciblés passent. Premier service discovery terminé avec Result=success/ExecMainStatus=0 ; 45 secondes, cinq abonnements reconnus, aucune erreur de décodage.

Correction : les nouvelles archives de sessions portent explicitement complete=False ; les sessions existantes ne sont pas requalifiées. Les limites de couverture étaient déjà enregistrées dans leurs métadonnées. Le rapport latest généré est ignoré par Git. Retour arrière du code ciblé ; conserver registres et données. La comparabilité de provenance ne prouve pas la comparabilité économique des populations.

## Causalité des conversions de frais — 2026-10-07

Correction du reducer comptable : une date de cotation antérieure au fill ne suffit plus ; disponibilité effective <= date de décision explicitement exigée, avec horodatages cohérents et taux fini positif. Formats invalides bloquent les métriques sans inventer une conversion. Vingt-sept tests account/accounting passent, dont connaissance ultérieure du même taux historique, timestamp invalide et taux nul/négatif/non fini. Aucun rapport historique ou donnée brute modifié, aucun pilote consulté. La consolidation des valorisations et les preuves de couverture restent partielles.

## Qualification descriptive héritée : périmètre corrigé — 2026-10-07

Le résumé legacy ne calcule plus le ratio totalNtlPos/accountValue comme levier : le capital soutenant les positions et le mode de compte ne sont pas prouvés. Les snapshots HIP-3 sont exclus du dernier état standard, et les fills HIP-3/spot identifiables par leur symbole sont exclus des sommes monétaires standard. Les limites sont explicites au rapport ; disponibilité basée sur observed_at plutôt que requested_at. Deux tests synthétiques ciblés passent. Aucun rapport ancien recalculé, aucune observation réservée lue, aucun service redémarré. Cette correction empêche des indicateurs trompeurs ; elle ne remplace pas la qualification comptable consolidée encore à terminer. Retour arrière : code ciblé, données conservées.

## Bornes de valorisation explicites — 2026-10-07

L’adaptateur ne substitue plus observed_at à un temps de valorisation absent, invalide ou futur. Diagnostics par périmètre : bornes exactes, références disponibles avant/après, distances temporelles et action attendue, sans interpolation de l’equity. Les valeurs de réception ne prouvent pas la date économique d’une position. Vingt-neuf tests account/accounting passent, dont snapshots sans date et bornes proches mais inexactes. Aucun recalcul des pilotes ni mutation des archives. Prochaine étape : organiser des périodes aux bornes réellement observées et traiter la couverture des événements ; les métriques économiques demeurent inconnues en leur absence.

## Périodes comptables observées — 2026-10-07

Sélection versionnée de fenêtres adjacentes entre valorisations horodatées, sans classement économique ; doublons contradictoires exclus comme bornes et disponibilité contrôlée. Script account-observed-periods.py produit le rapport de la dernière fenêtre disponible par compte standard-perp, ou un motif d’attente ; les périodes propres aux comptes ne sont pas présentées comme comparables pour un classement. Contrôle réel : 42 comptes population hors pilotes, quatre disposent chacun d’une fenêtre, aucun timestamp contradictoire ou observation rejetée. Quatre rapports comptables produits dans /tmp/tamtam-observed-accounting.json ; aucune validation économique. Preuve agrégée account-periods-control-20261007.json. Tests account/accounting ciblés : 31 passent. Pas de service ou migration, retour arrière du code, archives inchangées. La preuve de couverture des événements et la consolidation restent à construire.

## Diagnostics de couverture des historiques — 2026-10-07

Les rapports comptables exposent désormais par endpoint la réunion des fenêtres dont la pagination est terminée, les lacunes exactes, pages inachevées et références disponibles au cutoff. Une pagination couvrant la période ne devient jamais une preuve de rétention ou de périmètre économique. Quatre tests dédiés contrôlent chevauchement, trou interne, page saturée et page reçue trop tard ; 35 tests account/accounting passent. Rapports réels aux bornes observées régénérés dans /tmp uniquement ; preuve agrégée account-coverage-control-20261007.json. Aucune archive modifiée, aucun pilote lu, aucun critère de validation assoupli. Retour arrière du code uniquement.

## Lacunes de fin de passage et capacité actuelle — 2026-10-07

Diagnostic réel : les quatre périodes avaient une queue non interrogée de 15–20 secondes, car now_ms était capturé avant les inventaires ; deux avaient aussi un rattrapage des fills non achevé. Correction : cutoff historique après les appels d’inventaire, en conservant les targets des backlogs et le temps fixe injecté des recettes. Test ciblé simule des appels avançant l’horloge et vérifie les trois endpoints ; 16 tests population passent. Les données déjà archivées ne sont pas requalifiées. Prochain worker oneshot chargera le code sans restart du collecteur principal.

Mesure 60 min : 851,37 poids réservés/min, marge locale 48,63/min sur 900 ; source capacity-current-20261007.json. Flux principal : environ 184,67 frames/s, 52 184,87 octets/s, queue max 1335 messages et flush max 4,22 s. Ces mesures ne représentent pas encore la totalité de la découverte séparée ni une preuve de capacité maximale soutenable. Aucun changement de cadence ni dépense ; privilégier fermeture du rattrapage et classification du budget. Retour arrière code ciblé, archives/cursors conservés.

## Budget classé par charge — 2026-10-07

Décomposition reproductible intégrée au rapport capacity : backfill, historique incrémental, inventaires, métadonnées, marchés et ancien collecteur mixte ; tâches inconnues conservées dans unclassified. Trois tests passent. Mesure 60 min : marchés 506,98 poids/min ; ancien collecteur mixte 156,67 ; backfill population 102,67 ; inventaires 82 ; historique incrémental 2,17 ; métadonnées 0,67. Preuve capacity-classified-20261007.json. Hypothèse explicite de réserve de reprise 20 % du budget local : aucune marge supplémentaire mesurée. Cette réserve est une hypothèse de planification configurable, aucune modification du quota runtime ni de la cadence. Capacité soutenable en comptes volontairement inconnue tant que coûts de jobs complets et cycles représentatifs ne sont pas établis. Retour arrière du module/rapport uniquement ; aucune donnée de collecte modifiée.

## Contrat de consolidation testé — 2026-10-07

Reducer de valorisation pour pools indépendants, avec garde contre somme de collatéral partagé, scopes manquants/doublons, dates économiques désalignées et conversions non contemporaines ou futures. Quatre tests dédiés, 39 tests account/accounting passent. Capacité pure sur fixtures uniquement : intégration des preuves réelles de capital et valorisation spot reste à faire ; aucune consolidation réelle revendiquée. Aucune mutation d’archive ni service, rollback du module/documentation.

## Modèle de capital selon le mode — 2026-10-07

Documentation officielle relue : en unified/portfolio margin, spotClearinghouseState expose les balances/holds et les états utilisateur par DEX ne donnent pas un capital fiable. Adaptateur corrigé : refus des bornes de capital perp pour modes partagés/discontinué et changements observés ; balances spot conservées comme observations non valorisées. Quarante tests account/accounting passent dont fixture unified avec deux montants contradictoires entre sources. Pas de donnée réservée lue ou archive modifiée. Contrat et lien officiel dans ACCOUNTING-CONTRACT.md. La consolidation réelle exige encore valorisation des balances, engagements et positions, preuves de périmètre et dates alignées ; aucune validation économique.

## Journal de diagnostic population raccordé — 2026-10-07

Chaque fin de job population enregistre transactionnellement une décision immuable si mode, marchés, volume observé ou état de pagination changent. Identité source attempt, fingerprint descriptif, preuve, diagnostic, condition de réveil et prochaine action de collecte/qualification conservés ; contenu inchangé ne rouvre aucune analyse. Aucun appel IA ni promotion autorisé par ce diagnostic. Test dédié couvre replay/idempotence/entrée inchangée/changement ; 16 tests population passent. Migration additive adaptation_events et index, chargée par le prochain oneshot ; aucune relance du collecteur direct. La boucle proposition/comparaison/promotion/surveillance demeure partielle, ce journal n’en atteste pas l’achèvement. Rollback arrêt du worker population si nécessaire, retour du code, garder la table et toutes les preuves.

## Évaluation de procédure : premier reducer — 2026-10-07

Rejeu de choix datés, coûts des essais échoués et changements, attentes, références fixe/cash ; garde temporelle et inconnues explicites. Quatre tests synthétiques passent. Aucune trace réelle ou avantage mesuré ; export causal depuis registres et positions ouvertes encore à intégrer. Journal adaptation réel vérifié : un événement needs_data, aucun appel IA ni promotion autorisé ; preuve adaptation-runtime-control-20261007.json. Pas de nouvelle promotion ou lecture de réserve. Retour arrière code ciblé, journal conservé.

## Export chronologique réel des registres — 2026-10-07

Trace metadata-only raccordée aux registres existants et CLI reproductible, cutoff causal, derniers états mutables jamais rétrodatés. Contrôle réel : huit créations IA, huit derniers états, trois variantes figées, 53 débuts population/52 fins et deux diagnostics ; aucun début paper. Performance inconnue, aucune sélection/issue reconstruite rétrospectivement. Six tests procedure passent. Preuve procedure-trace-control-20261007.json et trace complète /tmp/tamtam-procedure-trace.json. Export des connaissances détaillées, sélections de politique et résultats autorisés au reducer encore à terminer. Archives/réserves intactes ; rollback code ciblé.

## Mesures stockage et processus — 2026-10-07

Script resource-capacity.py collecte métadonnées SQLite en lecture seule (pages allouées/libres), tailles DB/WAL/SHM, espace disque et CPU/RSS Linux du PID demandé, puis conserve un échantillon dans la télémétrie additive. Delta uniquement à identité DB/processus stable, redémarrages non assimilés à une baisse de coût. Deux tests passent. Premier relevé réel : 7 574 216 704 octets de pages SQLite, RSS collecteur principal 568 164 352 octets ; preuve resources-first-20261007.json. Un premier point ne donne pas de croissance ni de taux CPU : seconde mesure requise. Les enfants, autres workers et fluctuations de checkpoints restent distingués ; pas de prévision automatique de capacité. Commande : PYTHONPATH=src .venv/bin/python scripts/resource-capacity.py --db data/tamtam.sqlite3 --telemetry data/tamtam.telemetry.sqlite3 --pid PID --output /tmp/resources.json. Aucun service ou cadence modifié ; rollback script/module, historique télémétrique conservé.

## Préparation de la montée en capacité — 2026-10-07

Comparaison REST/flux mutualisés/IP stables/fournisseur/nœud et architecture ingestion/provenance/déduplication préparées dans CAPACITY-DECISION.md. Sources officielles consultées, tarifs Quicknode et modes de facturation distingués ; VPS/nœud restent hypothèses budgétaires non devisées. Deuxième relevé resource : intervalle 59,34 s, croissance logique ~54 874 octets/s, CPU principal ~0,072 cœur, aucune projection soutenable. Recommandation actuelle conserver local et vérifier coût/couverture avant dépense. Aucun achat ou déploiement.

## Changement de session paper protégé — 2026-10-07

Création paper atomique sous BEGIN IMMEDIATE, idempotence même version active ; autres sessions du même compte/marché doivent être retirées, sans position ni ordre pending. Retrait explicite journalisé, état/ledger conservés. Redémarrer une version retirée exige un motif, empêchant la pipeline de réactiver automatiquement une ancienne session. Capital de chaque nouvelle session explicitement indépendant, politique/motif archivés dans paper_session_policy. La pipeline expose les blocages de handover sans interrompre tous les autres jobs. Test synthétique positions ouvertes/retrait/ledger/motif et tests validation : 31 passent. Aucun paper réel activé ; raccordement CLI et politique automatique de suspension/remplacement encore à compléter. Rollback code ciblé, garder tables/sessions ; ne pas effacer des positions simulées.

## Commandes de retrait et redémarrage paper — 2026-10-07

CLI raccordée aux mêmes gardes transactionnelles : `PYTHONPATH=src .venv/bin/python -m tamtam_again --db CHEMIN paper-retire SESSION --reason MOTIF`, puis, pour la même version retirée, `paper-start VARIANTE --restart-reason MOTIF`. Retrait refusé avec position ou ordre en attente ; pas de liquidation implicite. Historique conservé et nouvelle session à capital indépendant. Aides CLI vérifiées et suite complète : 214 tests passent en 17,453 s. Aucune commande exécutée sur une session réelle. Cette interface permet une action opérateur ; la politique automatique de remplacement et la mesure du capital continu de procédure restent à compléter. Retour arrière du seul code CLI sans effacer les tables ni les journaux.

## Retraits dans la trace de procédure — 2026-10-07

Export metadata-only des retraits immuables à leur date propre, avec référence au journal ; ni motif libre, ni état courant, ni résultat réservé exporté. Test avant/après cutoff : un retrait futur ne modifie pas une trace passée. Sept tests procedure passent. L'absence de table reste compatible avec les anciennes bases. Les issues économiques et les choix de politique restent à raccorder avant toute comparaison réelle de la procédure. Retour arrière du module uniquement, journal de retrait conservé.

## Détection de contenu à volume égal — 2026-10-07

Le rapport population conserve désormais un fingerprint du contenu des fills de la passe, canonique et indépendant de leur ordre ou répétition. Le diagnostic l'inclut : une correction ou de nouveaux fills à compteur égal ne sont plus considérés comme une entrée inchangée. Deux tests adaptation et seize tests population passent. Pas de nouveau droit d'appel IA ou de promotion. Les anciens rapports sans fingerprint restent lisibles ; la première passe au nouveau format peut produire un diagnostic de changement de descriptor, sans modifier les anciens événements. Les fenêtres de passe restent différentes d'un historique cumulatif complet. Aucun redémarrage du collecteur direct ; prochain worker oneshot charge le code. Rollback code ciblé, rapports et événements conservés.

## Suspension paper persistante — 2026-10-07

Journal additif paper_suspensions : date et diagnostics conservés dans la même transaction que l'état, le cursor et le statut suspendu. Trace chronologique exporte uniquement l'identifiant et la date ; absence de journal sur anciens incidents non reconstruite. Tick revérifie le statut après acquisition du verrou, évitant de réactiver une session retirée entre lecture et transaction. Feed synthétique refuse également une session inactive. Test de la branche scheduler sur base fixture, archive mockée sans lecture réelle, vérifie journal/état/cutoff/refus du feed ; 32 tests validation passent. Politique de suspension actuelle inchangée (diagnostics moteur, continuité, budget de durée) ; règles de dégradation financière et remplacement restent à intégrer. Retour arrière ciblé du code, garder journal et positions ; aucun paper réel activé.

## Budget de perte paper prédéclaré — 2026-10-07

Nouveaux plans peuvent déclarer `paper_monitoring` avec version `paper-loss-budget-v1`, `max_net_loss_usdc` strictement positif/fini et `justification`. Le plan entier est immuable et fingerprinté : changer ce budget exige un nouveau plan. Au tick N2, résultat net inférieur ou égal à l'opposé du budget déclenche suspension journalisée, sans fermer fictivement la position ni choisir une remplaçante. Contrôle aux ticks, pas garantie d'un plafond de perte en temps continu ; dépend de la valorisation et continuité du moteur. Drawdown figé dans la stratégie reste un garde distinct. Paramètre choisi de risque, aucune preuve de disparition d'avantage statistique. Deux tests purs et 32 tests validation passent, dont raccordement à la suspension sur fixture avec métriques mockées. Pilotes existants sans ce champ inchangés. Aucun seuil universel ni nouvelle session réelle. Retour arrière des modules ciblés, conserver plans/journaux ; remplacement automatique demeure à compléter.

## Remplacement paper atomique prédéclaré — 2026-10-07

Contrat paper_replacement validé avant enregistrement du plan : prédécesseur existant de même périmètre/provenance, délai minimal positif et justification. Start après N1 cible passé peut retirer automatiquement le prédécesseur uniquement suspendu/flat/sans pending, puis créer et lier la nouvelle session dans une transaction. Pipeline existante emprunte cette même fonction ; pas de nouvelle sélection IA. Test synthétique initialement bloqué par réutilisation de finale, corrigé avec nouvelles fenêtres sans assouplir le garde. Vérifie cooldown, position ouverte, rollback d'incident SQLite et idempotence. Suite complète : 220 tests passent en 17,990 s. Contrat/limites PAPER-HANDOVER.md ; capital indépendant, continuité économique de procédure encore à établir. Aucun paper réel ou plan pilote modifié. Table additive paper_handovers et trace causalement raccordée. Retour arrière ciblé sans effacer tables, sessions ou collecte.

## Instantanés paper immuables — 2026-10-07

Table additive paper_snapshots enregistre métriques, disponibilité, cursor et fingerprint d'état au démarrage et à chaque tick, dans la transaction de session. Répétition identique idempotente, disponibilité antérieure à information traitée/instantané précédent refusée. Trace registry expose seulement identité/date/session/référence, pas les résultats à la recherche. Aucun historique mutable ancien rétroconstruit. Trois tests paper et 33 tests validation passent, dont rollback et instantané de suspension ; branche réelle exercée uniquement via mocks sur fixture. Rejeu causal des issues de procédure encore à raccorder ; métriques du modèle, pas preuve indépendante de coûts/continuité. Volume ajouté par tick à mesurer quand une session réelle sera admissible. Aucun paper réel démarré, migrations chargées au prochain démarrage/tick autorisé. Retour arrière ciblé en préservant snapshots, sessions et collecte.

## Résultats de période raccordés au reducer — 2026-10-07

Adaptateur paper_outcome + script paper-period-outcome.py : différence de PnL net cumulé entre deux instantanés exacts de même session, cutoff, flat/pending, diagnostics et métriques comptables vérifiés ; budget de risque dérivé du contrat figé. Absence/ambiguïté de borne ou position ouverte reste inconnue, aucun état actuel utilisé. Fixture raccordée à evaluate_procedure et propagation d'outcome inconnu ; cinq tests paper et sept procedure ciblés passent. Suite complète : 223 tests passent en 18,283 s. Modèle uniquement, coûts déjà comptés non soustraits deux fois ; références comparables, complétude et capital continu restent à établir. Aucun résultat réel ou réserve brute lu, zéro nouvelle session réelle. Documentation PROCEDURE-EVALUATION.md corrigée sur portée de la trace existante. Retour arrière modules/scripts, garder snapshots et collecte.

## Audit du raccordement population vers IA — 2026-10-07

Lecture actuelle research._prepare : candidats issus de cohort_research_status et alias des seuls comptes tracked, max_plans global du pilote, cycles exploitables et archive live obligatoires. run_job enforce_profile limite encore à template/horizon et deux signaux. Les profils REST descriptifs ne peuvent donc pas entrer dans cette préparation sans adaptateur séparé ; relever max_plans ou transformer des fills REST en signaux live serait incorrect. Étape suivante : paquet descriptif population causal distinct, budget/registre indépendant, proposition ouverte puis routage vers capacités exécutables ou extension ; aucun pilote à modifier.

Correction immédiate : proposeur et critique peuvent déclarer unsupported_mechanism, conservé comme état terminal avec wake explicite et action assess_engine_extension. Une incapacité du moteur ne devient plus une erreur/rejet économique ni une relance. Dix tests research passent dont une réponse multi-instrument fixture, un seul appel mocké, aucune variante ni session créée et replay sans inférence. Aucun appel réel. Retour arrière research.py ciblé ; conserver essais et diagnostics.

## Paquet descriptif population causal — 2026-10-07

population_packet et script population-research-packet.py livrés : dernière fiche disponible au cutoff, champs descriptifs whitelist, profil temporel contrôlé, protection avant payload, multi-marché sans template de deux minutes ni conversion REST/live. Budget complet ou needs_data, aucune troncature. Deux tests dédiés passent. Contrôle réel 52 comptes hors réserves : 51 packet_ready, un rapport dépassant le budget ; exemple lexical actif BTC/ETH/SOL 1041 fills observés, 178790 caractères, aucune qualification économique. Preuve population-packet-control-20261007.json. Aucun appel IA, lecture brute, mutation d'archive ou service. Registre distinct et runtime ouvert restent à intégrer, contrat POPULATION-RESEARCH.md. Retour arrière module/script sans toucher collecte.

## Registre borné de recherche population — 2026-10-07

population_research.seal utilise un registre indépendant du pilote, transaction BEGIN IMMEDIATE, paquets/politiques conservés, unicité compte/input, budget global et cooldown. Même descriptor que diagnostic adaptation ; report_id/date seuls ne rouvrent rien. Sans activité ou digest contenu, attente plutôt qu'inférence. La première table est chargée uniquement au scellement autorisé, aucun worker réel activé ici. Test dédié budget/deux versions/replay/cooldown/preuve originale passe ; deux tests adaptation et deux packet passent après factorisation du descriptor. Créations raccordées à trace metadata-only. État sealed, zéro appel/modification pilote ; scheduler/runtime/routage encore à faire. Rollback modules ciblés, garder requêtes/rapports et budgets historiques.

## Runtime d'hypothèse population isolé — 2026-10-07

Réutilisation verify/call du runtime isolé, verrou commun, réservation deux appels avant dispatch, paquets seuls, propositions multi-instrument/horizons ouverts, critique de cohérence et état hypothesis_recorded sans variante/validation/promotion. Contrat structuré avec preuves limitées au paquet ; réponses brutes/usage conservés, timeout suspendu sans retry, coût incomplet inconnu. Deux tests dédiés mockés passent : proposition/revue et replay, isolation manquante sans appel, timeout/réservation conservée. Aucun appel réel ou service activé. Scheduler et reprise après interruption restent à raccorder, puis routage expérimental distinct. Rollback module uniquement, conserver requêtes, réponses et budgets.

## Ordonnanceur et reprise population IA — 2026-10-07

Tick sous verrou kernel commun, scellement borné de population active/hors réserves, dispatch borné, récupération running en interrupted sans retry ni effacement de checkpoint/réservation. Aucun worker coopérant vivant peut être récupéré car il tient le même verrou durant ses appels ; coûts distants éventuels restent inconnus. Checkpoints réponse/usage après chaque retour, requêtes trop anciennes expirées avant inférence selon max_request_age_ms prédéclaré. Quatre tests runtime (dont reprise/expiration) et un registry passent. Suite complète 231 tests passe en 22,520 s ; trace metadata-only inclut derniers états/coûts au temps d'update, pas de rétrodatation. Script population-research-tick.py avec prepare-only et max-jobs, pas de timer ou politique réelle activé ici. Aucun appel IA réel, pilote inchangé. Prochaine étape activation mesurée avec politique dédiée, puis routage vers expérience ; rollback code ciblé, garder budgets et checkpoints.

## Premier contrôle IA population réel — 2026-10-07

Politique dédiée ajoutée : première tranche huit requêtes, cooldown 24 h, expiration 1 h, un job par tick, deux réservations 1 USD/job, timeout 120 s/appel et sortie 5000 tokens. Budgets choisis, pas seuils de preuve ; budget maximal de réservation 16 USD, aucun achat/abonnement nouveau. verify réel réussit (zéro outil). Un paquet scellé puis un appel réel : 37365 tokens entrée/1586 sortie, 58089 ms, coût retourné included 0 USD. Réponse hypothèse mais diagnostic objet et références déjà présentes dans projections internes refusaient le contrat trop étroit ; requête conservée suspended, actual_cost historique inconnu, réservation 2 conservée, aucun retry. Correction pour prochains appels : diagnostic structuré non vide, références des profils/mécanismes présents dans le paquet admises, références inventées refusées. Réponse conservée vérifiée structurellement sans inférence ni mutation de son état. Cinq tests runtime passent, 23 tests population avant correctifs passent. Coûts futurs inconnus seulement lorsqu'un appel n'a pas retourné ; erreur de contrat après retour conserve coûts connus. Preuve population-runtime-control-20261007.json. Unités service/timer préparées et systemd-analyze verify réussit, non installées/activées ; première recette complète à refaire uniquement sur nouvelle entrée. Collecteur PID 447350 actif, huit plans/trois variantes/zéro paper conservés. Retour arrière : code/config ciblés ; garder requête, réponse, réservations et données.

## Recette réelle complète et timer population IA — 2026-10-07

Nouvelle entrée distincte 2291b04a… termine hypothesis_recorded après deux rôles : 59461 ms/4609+1545 tokens, puis 19639 ms/5794+467 tokens, usages included 0 USD, réservation 2. Première erreur conservée sans retry. Suite complète 232 tests passe en 25,156 s. Timer dédié installé/activé (backup de présence préalable), premier service vivant PID 509168 au contrôle, collecteur original PID 447350 inchangé. Preuve population-runtime-success-20261007.json : huit plans/trois variantes/zéro paper, pas de promotion ou preuve de rentabilité. Premier job timer encore running au relevé, à observer sans redémarrage. Plafond global huit requêtes ne se réarme pas automatiquement. Contrat opérationnel/rollback POPULATION-RESEARCH.md. Restent routage vers expériences exécutables, mémoire automatique et comparaison économique de la politique ; Goal toujours en cours.

## Premier passage timer terminé — 2026-10-07

Même service PID 509168 observé terminal via systemd : Result=success, MainPID=0, timer active/waiting. Requête cdef25f1… hypothesis_recorded avec deux appels (55285 ms et 15070 ms, usages included 0 USD), aucun diagnostic d'erreur et aucune promotion. Preuve population-timer-control-20261007.json. Deux hypothèses réelles enregistrées au total, une première requête suspendue conservée ; trois requêtes sur plafond huit. Pas de redémarrage forcé ou nouvel appel sur entrée inchangée. Résultat technique, aucun avantage établi ni paper activé.

## Mémoire automatique des hypothèses population — 2026-10-07

Preuve typée population_research admise uniquement pour hypothèse revue disponible et période source intégrale explicite, soumise aux réserves existantes. Importer population_memory idempotent, lien de requête, statut hypothesis/aucune expérience inventée ; scheduler reprend imports sans réinférence. Deux hypothèses réelles importées, replay mêmes IDs, zéro appel ou release et pilotes huit/trois/zéro préservés : population-memory-control-20261007.json. Six tests runtime et neuf mémoire passent. Paquets suivants peuvent inclure mémoire autorisée au cutoff/budget, mais nouvelle mémoire seule ne change pas le déclencheur descriptif (évite auto-boucle). Période source conservatrice 0..disponibilité+1 peut bloquer une réutilisation tant qu'une réserve chevauchante demeure ; aucun assouplissement automatique. Retour arrière code ciblé, garder knowledge/liens/requêtes et données. Routage vers expériences exécutables toujours à terminer.

### Protection des preuves mémoire population

Le contrôle générique de sauvegarde exige désormais la critique cohérente et les deux drapeaux économiques explicitement faux dans la preuve population, même si un appelant contourne le helper d'import. Test supplémentaire : une hypothèse ETH issue d'une fiche globale ne peut masquer une période BTC réservée du même compte. Le refus ne crée ni connaissance ni lien d'import ; aucun appel IA ni libération de période. Sept tests runtime ciblés passent. Retour arrière : annuler le commit ciblé de code/tests, conserver les connaissances, requêtes et périodes existantes.

### Routage des hypothèses population

Routes persistantes automatiques après revue : données absentes, spécification
absente, mécanisme/adaptateur absent ou plan prospectif à enregistrer. Aucune
traduction implicite en leader_delta/momentum, aucun changement aux pilotes.
Contrôle réel des deux hypothèses revues : needs_data, sans appel ni promotion.
La condition de réveil descriptive n'est pas une preuve de complétude ; les
besoins inaccessibles et le raccordement de plans restent à traiter. Tests de
rejeu immuable, absence de création de variante/plan et capacité structurée.

### Ordres publics ciblés, sans nouvelle cadence automatique

Ajout de historicalOrders et frontendOpenOrders au client lecture seule, borne
réservée historique 120 poids et coût de réponse mesuré par items. Commande
explicite partageant la télémétrie/quota existants, maximum trois inventaires DEX,
refus des comptes réservés avant requête. Snapshots archivés avec réception et
périmètre ; aucun cycle complet, cible privée ou priorité de file certifié.
Résumé causal optionnel dans les paquets suivants, empreinte de contenu d'ordres
pour signaler une information nouvelle, sans altération des paquets scellés.
Contrôle réel : 1 890 ordres historiques, 570 statuts canceled, deux ordres ouverts
sur DEX standard ; paquet ultérieur prêt et résumé inclus. Les besoins des deux
hypothèses restent non satisfaits. Preuve population-orders-control-20261007.json.
Trente-quatre tests population passent en 7,205 s. Aucun timer ni collecteur
redémarré, aucune inférence demandée par ce contrôle.

### Mémoire héritée et chronologie de la procédure

Correction : import population conserve toutes les périodes et preuves de mémoire
héritée, même pour d'autres comptes. save_knowledge vérifie preuves, dates et
union explicitement déclarée. Date disponible du paquet >= création des
connaissances exportées ; empreinte descriptive seule inchangée par mémoire.
Test d'héritage multi-compte et suppression de période refusée. Aucun import
antérieur réécrit ni réserve libérée.

Trace metadata-only étendue aux cohortes, ordres, routages, connaissances,
imports et libérations, avec dates propres. Test de cutoff et absence de lecture
du payload. Contrôle réel : 4 requêtes population, 3 imports mémoire, 4 routes,
1 rapport d'ordres au relevé ; huit plans/trois variantes, aucun événement paper.
Preuve procedure-memory-trace-control-20261007.json. Résultat économique de
procédure inconnu. Suite combinée complète : 244 tests passent en 20,485 s.
Retour arrière ciblé des modules, conserver tables/registre/mémoire et preuves.

### Hypothèse exécutable vers expériences prospectives — étape 11

Raccordement explicite à une famille bornée, plan et profil distincts, même
compte/réseau/marché, pas de donnée requise non résolue, revue cohérente sans
certification économique. Nouvelle comparaison future, exploration couvrant
l'information exposée, anciennes variantes préservées. Lien immuable/rejouable,
reprise entre commit famille et lien sans double variante. Recette synthétique
comparaison→sélection→finale→paper synthétique, refus promotion réelle.
Compilation automatique des règles en prose et création des plans encore
manquantes ; aucun plan réel ni pilote modifié par cette recette.

### Création prospective bornée — étape 11

Préparation plan+famille depuis hypothèse exécutable et politique/profil explicites.
Ancre et contrat immuables en population_plan_drafts avant commits dépendants,
reprise sans décaler finale, plafond global de plans, embargo couvrant toutes
les variantes et budget couvrant fenêtres/comparaisons/finale. Refus des données
non disponibles et des besoins unresolved ; aucun nouveau plan réel ni appel IA.
Cinq tests plans dédiés, 46 tests population ciblés passent (9,627 s avant dernier
contrôle de disponibilité). Compilation IA et profils par hypothèse encore à
raccorder ; aucun paramètre universel ajouté au timer. Trace référence les drafts.

### Runtime vers préparation automatique — étape 11

Contrat optionnel executable_spec+experiment_profile dans les deux rôles
existants, sans nouvel appel ajouté : fidélité marchés/type, identité requête,
preuves axes du paquet, validation capacité/profil. Unknown mechanism reste
unsupported sans rejet économique ni conversion forcée. Scheduler prépare les
plans avec une politique explicite par requête fournie hors modèle, sous verrou
commun sans réacquisition, bornée max_jobs et liens déjà créés ignorés.
Recette intégrée simulée runtime→mémoire/route→plan, absence sans politique et
rejeu sans doublon/inférence ; aucun paramètre universel ni fichier de politiques
activé en production. Les anciennes réponses et variantes sont conservées.

### Preuves de délais déclarés mesurés — étapes 9/11

Le point de compilation exige une référence typée d'exécution disponible dans
le paquet pour measured_reference, avec cutoff/date exacte/valeur et distinction
REST vs exécution. Preuves des axes contrôlées aussi sur les chemins explicites
plan et expérience, avant réservation de draft/gel. Paquets actuels sans preuve
d'exécution : les délais restent expérimentaux simulés. Tests référence absente,
future, mauvaise nature/date et contournement direct refusés. Contrat sans
promotion ni nouvelle inférence ; anciens registres préservés. Le raccordement
de mesures d'exécution véritables reste à établir avec l'environnement paper.

### Parcours scheduler jusqu'au paper synthétique — étape 11

Recette reproductible indépendante en base temporaire : inventaire→paquet→deux
rôles simulés→mémoire/route→plan/famille→pipeline comparaison/sélection/finale→paper
synthétique→reconnexion et rejeu. Le pipeline refuse le mode fixture si un plan
réel existe ; tick ordinaire ignore les variantes synthétiques. Test d'échec de
comparaison sans paper et provenance synthetic/promotable=false conservée.
Artefact population-recipe-control-20261007.json, aucune requête fournisseur ni
inférence réelle, isolation explicitement simulée, aucun changement production.
La recette ne qualifie aucune stratégie réelle et ne termine pas les autres
capacités du Goal. Commande/limites/rollback POPULATION-RESEARCH.md.

### Attentes et issues dans le journal causal — étape 12

Correction dedup pipeline : preuves incluses, les variantes différentes ne sont
plus perdues sous un même diagnostic d'attente. Nouveau journal terminal des
évaluations, statut/date après calcul, commit atomique avec résultat, erreur
incluse et finale toujours consommée ; rejeu sans changement de date. Trace
metadata-only des décisions et terminaisons sans lecture de résultats réservés.
Anciens événements manquants non reconstitués/non rétrodatés. Tests preuve
changée vs rejouée, date disponible/cutoff, absence de lecture de diagnostic ou
preuves JSON, statut terminal immuable et chemin erreur réel du moteur sur fixture.
L'adaptateur complet de sélection/résultats autorisés reste à terminer.

### Coûts de recherche de toute la procédure — étape 12

Adaptateur metadata-only des registres population et isolé, fenêtre explicite,
inscription/settlement séparés, échecs inclus, coûts manquants non remplacés par
réservations. Jobs isolés suspendus conservativement inconnus (coût partiel
possible). Contrôle réel en lecture seule dans procedure-provider-costs-control-
20261007.json ; aucune donnée réservée ni appel modèle. Agrégat limité aux
registres, hors infrastructure. Références de procédure et capital continu
restent à intégrer avant une performance adaptative complète.

### Vérification des bornes de capital — étape 12

Contrat facultatif strict du reducer : capital initial disponible, bornes USDC
sans flux, périodes contiguës et réconciliation PnL ; remise à zéro rejetée,
borne absente inconnue, ancienne trace explicitement non vérifiée. L'adaptateur
paper fournit capital initial du modèle plus PnL cumulatif aux instantanés plats.
Coûts externes séparés de la balance du moteur. Transfert entre sessions et
comparateurs contemporains toujours manquants ; aucune stratégie réelle validée.

### Transmission du cash paper lors d'un remplacement — étape 12

Option explicite du plan immutable carry_flat_cash, prédécesseur suspendu plat,
cash positif et fingerprint d'instantané disponible exigés. Transfert atomique
avec retraite/lien/session, base de capital propre au nouveau state et compteurs
séparés. Anciennes règles inchangées, anciens plans indépendants par défaut.
Aucune activation réelle ; limites risque comparatif/coûts externes et rollback
spécifique aux sessions transférées dans PROCEDURE-EVALUATION.md.

### Préenregistrement de procédure et références — étape 12

Registre additif content-addressed avec périodes futures, références disponibles
et choix immuables datés par l'horloge locale. Relecture conserve dates, écriture
après début ou révision d'un choix refusées ; attente précédente non effaçable.
Tests de temporalité/idempotence/connaissance future. CLI explicite sans runtime
ni archive. Exécution des références et adaptateur d'évaluation complet restent
à raccorder ; aucun contrat réel ou paper créé.

### Liaison prospective des résultats paper — étape 12

Registre additif de sessions liées aux rôles avant période, identité/version/
scope contrôlés, relecture immuable. Résolution via instantanés paper uniquement,
période non terminée et preuves absentes inconnues, aucune archive réservée.
CLI explicite sans lancement de session. Références multi-comptes et raccordement
complet des coûts au reducer restent ouverts ; aucune liaison réelle créée.

### Périmètres explicites de témoins — étape 12

Références avec scope network/address immutable ; témoin de sélection exige
preuve de cohorte datée et justification de matching. Liaison contrôlée au scope
prévu plutôt qu'au compte adaptatif. Sans fusion de positions/résultats ni
promotion ; comparabilité économique et assemblage coût/reducer encore ouverts.

### Rapport de procédure raccordé aux registres — étape 12

Lecture contrat/choix immuables, liens paper puis reducer par référence. Coûts
fournisseur de tous les essais de la fenêtre inclus même après dernier choix ;
unknown sur coût manquant/changement non chiffré/choix absent, waiting avant fin.
CLI lecture seule. Attribution réseau/compte et fenêtre, coût de référence séparé,
preuves de matching et coûts de changement à revoir indépendamment. Aucun rapport
réel ni exécution automatique de référence ajouté.

### Sessions de comparaison distinctes — étape 12

Références N2 séparées par contrat/période/rôle, même gate N1 que les sessions
ordinaires, attribution indépendante et exclusion des conflits de remplacement.
Tick pipeline borne à une tentative, contrats/choix futurs seulement, fixtures
non activées par le scheduler réel. Test coexistence ordinary/reference, rejeu
avant début et refus après début. Contrôle réel Oct8 : collectors actif,
8 plans/3 variantes/0 paper, 8 requêtes IA (7 hypothèses/1 suspendue), tranche
non augmentée. Aucun contrat/session réelle créé ; état metadata-only archivé.

### Recette comparative de procédure — étape 12

Base temporaire dédiée, N1 synthétique ordinaire, contrat prospectif, attente
puis règle, référence fixe à capital continu/cash, coût d'essai rejeté, replay
après reconnect exact et coût absent propagé. La meilleure référence scriptée
ne remplace pas le choix initial après coup. Pas de provider/IA/archive réel.
Recette exécutée et preuve procedure-comparative-recipe-20261008.json ; limites
remplacement actif/cohorte qualifiée/automatisation live restent explicites.

### Recette remplacement dans le bilan comparatif — étape 12

Troisième période sur fixture : deuxième variante/plan explicitement prévus,
N1 synthétique, choix avant borne, suspension scriptée et handover à cash continu.
Liaison adaptive nouvelle session à borne exacte autorisée, après borne refusée.
Ancien state inchangé, référence continue, coût changement distinct, rapport
reproductible et unknown sur coût absent. Preuve nouvelle conservée séparément
de la recette précédente ; aucune politique adaptative réelle qualifiée.

### Audit intermédiaire des quinze exigences — 8 octobre

AUDIT-20261008.md conserve le périmètre intégral, preuves identifiées et écarts
comptabilité/capacité/cohortes/autonomie/multi-instruments/CR. Pas de conclusion
complète depuis les seules recettes. Contrôle read-only des 8 plans/3 variantes
contre baseline : 11 empreintes inchangées, aucune observation/résultat réservé
lu ; preuve pilot-preservation-audit-20261008.json. Goal reste actif.

### Risque collatéral unifié — étape 6

Reducer unified maintenance ratio et raccordement observations account_adapter.
Solde spot partagé unique par token, marge isolée soustraite, hold non ajouté,
collatéral insuffisant non assimilé à zéro risque. Mode/timestamps/périmètre/
mapping/availability manquants inconnus. Formule officielle vérifiée Oct8.
Consolidation equity/flux réelle toujours partielle ; aucun compte qualifié.

### Contrôle réel et diagnostics du ratio — étape 6

5 comptes non protégés, 20 snapshots spot, aucun timestamp économique présent.
Modes contrastés (unified/portfolio/default/disabled), aucun ratio ponctuel
certifié et zéro qualification. Preuve unified-risk-real-control-20261008.json,
read-only sans API. Diagnostic/action distingués par mode/changement/horodatage/
périmètre ; demander plus de fills ne résout pas l'absence de timestamp spot.

### Fenêtres locales d'acquisition — étape 6

Spot et composantes de marge exportent temps request/archive, durée et statut
sans inférer d'instant économique. Reducer de span distingue chevauchement local
et cohérence économique non prouvée. Contrôle réel metadata-only cinq comptes
hors pilotes ; preuve acquisition-window-control-20261008.json. Pas de nouveau
call/provider/collecte. Regroupement d'acquisition et valorisation restent à faire.

### Capacité prolongée réelle — étapes 2/14

Nouveau contrôle read-only REST/WS/metadata ordonnanceur : 23,002 h, 22 heures
complètes, 688 essais population terminés/1 running, 32 slots. Moyenne REST
850,57/min, p95 empirique 858,05, toutes les heures dépassent le budget 720/min
avec reprise 20 %. Aucune expansion justifiée. Buckets inactifs inclus, bords
partiels exclus, phases inconnues conservées ; pas de capacité déduite du quota.
CPU reste mesuré seulement sur 59 s, pas sur la fenêtre entière ; pas de SLA ni
preuve de reprise. Commande, limites et rollback CAPACITY-DECISION.md. Collecteur
systemd contrôlé active/running ; oneshots inactive hors tick ne signifie pas
arrêt des timers. Aucun changement service, budget ou données réservées.

### Témoins appariés prospectifs — étape 8

Matching disponible à cutoff, modes/DEX/spot/cadence/couverture/strate d'activité
identiques, marché commun, fenêtres de durée comparable ; paires disjointes,
maximum par chemins augmentants, budget et paramètres explicites. Enregistrement
immuable avant période future et replay conservé ; pilotes exclus avant payload.
Contrôle réel : deux paires exploration/uniforme ZEC et NEAR, six exclus,
17 sans paire ; aucun témoin classement compatible. Pas de critère relâché.
Preuve cohort-matching-control-20261008.json et nouvelle table additive.
Ce contrôle ne prouve ni équivalence du risque complet ni performance ;
comparaison économique dépend toujours de la qualification comptable.

### Diagnostic de suspension et reprise — étape 11

Tick paper réel inscrit demande/état/suspension/snapshot atomiquement ; pipeline
récupère jusqu'à huit suspensions sans diagnostic avec preuve de state cohérente.
Un seul diagnostic immuable par session. Collection défaillante prioritaire sur
attribution de perte ; signal retardé, performance, fin de budget et inconnu
routés explicitement. Aucun appel IA/reprise/promotion autorisé par cette demande.
Budget population non réarmé. Tests contrôlent disponibilité/mismatch/replay et
rollback injecté lors du tick ; aucune position/version ancienne modifiée.
La phase nouvelle proposition IA bornée et détection statistique restent à finir.

### Regroupement explicite des acquisitions — étape 6

Nouveaux passages population liés par attempt_id ; états DEX portent périmètre
attendu et référence au perpDexs du passage. Rapport comptable regroupe uniquement
ces preuves, distingue incomplet/conflit et laisse l'historique sans lien explicite.
Pas de regroupement heuristique ni capital inféré de la réception. Timestamps
économiques communs distingués du span local, equity toujours inconnue.
Précondition de valorisation réelle livrée ; cette valorisation reste à implémenter.
Pas d'endpoint/cadence/service/budget/schema modifié. Contrat et rollback dans
ACCOUNTING-CONTRACT.md ; contrôle metadata-only account-acquisition-control.

### Contrôle portfolio distinct — étape 6

Sources officielles portfolio/modes/portfolio margin revérifiées Oct8. Courbes
échantillonnées déconseillées pour comptabilité précise ; pas de substitut à
valorisation complète. Adapter exporte séparément contrôles de séries, bornes
exactes, conflits/points futurs, jamais rendement ou PnL reconstruit. Contrôle
réel cinq derniers comptes hors pilotes, zéro API/qualification ; preuve
portfolio-evidence-control-20261008.json. Valorisation consolidée reste ouverte.

### Instrumentation machine régulière — étapes 2/14

Nouveau service/timer resources projet activé environ chaque minute, mesures
metadata stockées dans télémétrie séparée. CPU de cgroups projet et InvocationID,
mémoire anon/cache/kernel distinguée, tailles DB/WAL/SHM/pages et espace disque.
Pas de différence CPU entre invocations ni unknown transformé en zéro. Services
oneshot courts et runtime IA externe peuvent manquer ; pas capacité complète.
Unités systemd vérifiées, exécution success/0 et timer actif. Preuves first et
activation datées ; suivi prolongé à analyser après accumulation.

### Dossier de revue indépendant — étape 15

REVIEW-REPORT-20261008.md rassemble état initial/courant, quinze exigences avec
écarts, commits/fichiers/migrations/services, preuves capacity/accounting,
critères choisis, tests/recettes, coûts inconnus, rollback et commandes readonly.
Contrôle metadata frais : 3294 candidats, 69 inventaires, 32 slots/37 retirés,
8 plans/3 variantes inchangés, zéro paper, sept needs_data et une suspension IA.
Deux recettes temporaires réexécutées, aucun fournisseur/modèle réel ni DB originale.
Ce dossier est partiel et ne marque pas les travaux restant comme terminés.

### Rapport ressources raccordé — étapes 2/14

Série service-resources-v1 maintenant exportée par sustained-capacity v2 avec
couverture réelle, trous/restarts exclus et moyennes pondérées sur intervalles
connus. 10 samples/~500 s, ~0,59 % fenêtre REST : pas dimensionnement prolongé.
Collecteur ~0,13 cœur, paper ~1 cœur conditionnel sur ses intervalles connus ;
coût paper sans session à diagnostiquer. Preuve capacity-resources-current.
337 tests passent en 29,483 s, bounds/restarts/gaps/DB remplacée couverts.
