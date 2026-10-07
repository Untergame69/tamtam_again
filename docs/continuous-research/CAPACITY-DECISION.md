# Décision de capacité — préparation du 7 octobre 2026

## Recommandation actuelle

Conserver l'infrastructure locale et terminer la qualification/couverture avant achat. Le goulot mesuré est le budget REST, pas une saturation démontrée du processus principal. Examiner d'abord le coût des appels marchés et la duplication éventuelle avec les flux existants, sans modifier les paramètres figés des pilotes. Le simple ajout de machines n'établit pas la complétude des données.

## Mesures et limites

Preuves : capacity-classified-20261007.json et resources-first/second-20261007.json. Environ 851 poids REST réservés/min sur le budget local 900 ; la collecte marchés en représente environ 507. La réserve de reprise pilote de 20 % laisse zéro marge d'expansion mesurée. Le poids réservé n'est pas une mesure de facturation serveur.

Sur deux relevés séparés de 59,34 secondes : croissance de pages SQLite environ 54 874 octets/s et CPU du processus principal environ 0,072 cœur. RSS environ 564 Mo, base logique environ 7,58 Go. Ce petit intervalle mélange les tâches ; aucune projection mensuelle soutenable déduite. Enfants, workers, charge totale et pics restent à mesurer.

## Options comparées

| Option | Capacité / couverture attendue | Coût incrémental | Latence, maintenance et pertes |
| --- | --- | --- | --- |
| REST local moins fréquent | Plus de comptes seulement si le coût complet par compte et la rétention le permettent ; aucune hausse chiffrée prouvée | 0 abonnement ; calcul et stockage existants | Latence de polling ; risque de dépasser la rétention ; reprise de pagination nécessaire |
| Flux mutualisés par marché | Découverte de plusieurs participants sans slots utilisateurs ; observation partielle distincte du suivi individuel | 0 abonnement public ; stockage et décodage supplémentaires | Reconnexions, snapshots, fenêtres silencieuses ; priorité de file inconnue |
| Deux collecteurs sur IP stables | Scénario de deux budgets locaux de 900 : plafond réservé agrégé 1800/min, hors autres clients et réserve ; pas une capacité soutenable en comptes | Hypothèse de planification 10–20 EUR/mois par machine légère, donc 20–40 EUR/mois, stockage/transfert et TVA séparés ; devis non obtenu | Attribution des shards, horloges, spool durable, doublons, transfert et supervision ; pas de rotation de proxies |
| Fournisseur HyperCore | Capacité différente selon méthodes/crédits/filtres ; historique et garanties à vérifier avant migration | Quicknode Build affiché 49 USD/mois ou 34 USD/mois avec facturation annuelle, hors dépassements ; coût de notre charge inconnu | Dépendance fournisseur, frais de flux, modalités de reprise et profondeur historique à mesurer |
| Nœud propre | Accès à l'état/événements du nœud, avec service d'indexation à construire ; ne remplace pas automatiquement nos endpoints ou l'historique | Hypothèse budgétaire exploratoire 150–400 EUR/mois pour matériel adapté + stockage/maintenance ; devis et dimensionnement non obtenus | Exigences importantes, synchronisation, indexation, surveillance et pertes de logs ; disproportionné à la preuve actuelle |

Les montants de planification ne sont pas des tarifs fournisseurs vérifiés. La page Hetzner consultée décrit notamment des machines 2 vCPU/4 Go/40 Go, mais le rendu accessible ne fournit pas de montant exploitable et affiche une disponibilité limitée : demander un devis actualisé avant toute décision. [Offre officielle](https://www.hetzner.com/cloud/cost-optimized/).

Le tarif et ses modalités ci-dessus proviennent de la [page Quicknode](https://www.quicknode.com/pricing). Build ouvre HyperCore WebSocket/gRPC, avec cinq streams, cinq filtres nommés par stream et cinq valeurs pour les champs user/coin/type ; ces limites ne démontrent pas le suivi de 125 comptes indépendants, car les flux, filtres et crédits se cumulent. [Documentation Hyperliquid du fournisseur](https://www.quicknode.com/docs/hyperliquid/pricing-faq).

Le dépôt officiel recommande pour un non-validator 16 vCPU, 128 Go RAM et 500 Go SSD, Ubuntu 24.04, avec ports gossip publics. Cela exige une architecture dédiée et un chiffrage distinct. [Nœud officiel](https://github.com/hyperliquid-dex/node).

## Découpage concret préparé, sans déploiement

1. Coordinateur local : registre candidats/cohortes, baux exclusifs account/endpoint, politique, critères et journaux.
2. Collecteurs REST : shards stables d'adresses et endpoints, budget par IP, curseurs indépendants, reprise inclusive des timestamps ; aucun raisonnement IA.
3. Collecteurs marchés : shards d'instruments, identités de session, acknowledgements/heartbeats, spool durable borné ; pas de collecte de réserves par la recherche.
4. Ingestion centrale : conservation event_time, collector_received_at, ingestion_available_at, collector_id, boot/session et séquence ; disponibilité du moteur égale à l'arrivée centrale réellement utilisable, sans rétrodatation au premier hôte.
5. Déduplication : identité économique par événement + conservation de chaque réception/provenance ; payloads contradictoires isolés. Réception dupliquée ne double pas le PnL.
6. Recherche/validation : paquets causaux autorisés depuis l'archive centrale ; mêmes moteurs et versions ; export temporel protégé.

L'ingestion distribuée n'est pas encore implémentée. Avant dépense : mesurer au moins des cycles complets de rattrapage/incrémental, coûts de jobs par périmètre, rétention à l'activité réelle, croissance/pics et backlog ; comparer une charge identique chez un fournisseur avec budget explicite. Aucun achat, compte fournisseur, VPS ou port réseau créé pendant ce travail. Coût engagé : 0 nouvel abonnement.
