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

## Contrôle prolongé du 8 octobre

`capacity-sustained-20261008.json` remplace les seules fenêtres de démarrage
comme preuve de charge REST observée : 23,002 heures disponibles, 22 buckets
horaires complets, 850,57 poids réservés/min en moyenne, p95 empirique 858,05,
maximum 858,65. Les 22 buckets dépassent 720/min, budget opérationnel choisi
avec réserve de reprise de 20 % sur le plafond local 900. Aucune extrapolation
à un nombre soutenable de comptes ni intervalle de confiance indépendant.
Les bords partiels sont exclus ; les heures inactives resteraient incluses.

689 essais population inscrits : 688 terminés, un running à l'instant du
contrôle ; maximum terminé 130,249 s. 32 slots actifs, intervalles courants
3600 s, un slot non running dû depuis 0,357 s. Ce dernier état est ponctuel,
pas un SLA historique. La fenêtre couvre plusieurs passages horaires mais
pas encore une époque entière de rotation UTC ni une reprise après incident.
Les phases backfill/incrémental/inventaire sont ventilées par heure. Les deux
appels ciblés non classifiés restent visibles au lieu d'être ignorés.

2739 mesures WS couvrent 82737 s ; pic de file 2595 messages, retard maximal
flush 12,392 s. Ces maxima nécessitent un diagnostic de contexte avant toute
promesse de latence. Les seuls deux samples ressources existants sont espacés
de 59,342 s : ils ne mesurent **pas** les 23 heures ni les enfants IA. La
capacité CPU/stockage soutenable reste à instrumenter sur cycles complets.

Décision actuelle : maintenir le nombre de slots ; aucune augmentation de
cadence/adresses n'est justifiée avec la marge de reprise retenue. Un autre
budget de reprise doit être une décision explicite, pas un moyen de déclarer
une capacité supérieure. Priorité : mesurer les besoins réels par endpoint et
réduire les appels redondants sans altérer les périodes pilotes avant de payer
une capacité externe. Ce contrôle n'engage aucune dépense ni modification de
service et ne prouve aucune couverture comptable complète.

Reproduire en lecture seule (aucune création/migration de base) :

```sh
PYTHONPATH=src .venv/bin/python scripts/sustained-capacity.py \
  --telemetry data/tamtam.telemetry.sqlite3 --db data/tamtam.sqlite3 \
  --hours 24 --output /tmp/capacity-sustained.json
```

Retour arrière : retirer le script et le reducer ; aucune table, configuration,
ordonnanceur ou abonnement n'a été modifié. Conserver le contrôle daté.

## Mesures machine régulières

Service/timer projet `tamtam-again-resources` activé le 8 octobre. Environ une
minute entre prélèvements (OnUnitInactiveSec=60, précision 5 s), lecture seule
PRAGMA page_count/freelist/page_size et stat DB/WAL/SHM, propriétés explicitement
choisies des six services projet. Les samples restent dans la base de télémétrie
séparée sous service-resources-v1. Aucune commande/env/secrets/archive lus.
L'instrumentation ne change aucun service partagé ni collecteur existant.

CPUUsageNSec/InvocationID donnent une différence uniquement à invocation
identique et compteur croissant ; redémarrage, compteur absent ou inversé reste
inconnu. Mémoire de cgroup inclut cache et descendants : memory.stat distingue
anon/file/kernel/shmem, donc MemoryCurrent n'est jamais annoncé comme RSS.
Services oneshot très courts entre prélèvements peuvent être manqués ; ceci ne
certifie pas l'ensemble des coûts paper/IA. Le runtime IA extérieur aux cgroups
projet et les autres usages machine restent hors attribution.

Preuves initiales service-resources-first-20261008.json et
service-resources-activation-20261008.json : commandes réussies, timer actif.
Ces samples initiaux n'établissent pas une capacité prolongée. Revoir après une
époque de collecte et une reprise, en distinguant les intervalles inconnus.
Le script sustained-capacity lit encore l'ancien canal resources : ne pas
présenter ce canal comme la nouvelle série ; exploitation de service-resources-v1
à intégrer au rapport prolongé.

Retour arrière, sans arrêter la collecte :

```sh
systemctl --user disable --now tamtam-again-resources.timer
systemctl --user stop tamtam-again-resources.service
```

Retirer seulement les deux unités resources installées et daemon-reload pour
annuler l'installation ; conserver les mesures. Zéro endpoint/paiement/recherche
IA déclenché, aucune migration dans l'archive principale.

## Série ressources raccordée au rapport

Le contrôle sustained-capacity v2 ajoute service_resource_series, sans remplacer
les deux anciens samples resources. Moyennes CPU pondérées seulement sur mêmes
InvocationID et compteurs croissants ; trous >180 s (paramètre pilote explicite)
exclus, bornes non observées non remplies. Couverture CPU par unité et couverture
stockage divisées par la fenêtre demandée ; maxima mémoire échantillonnés, pas
pics continus. Le rapport déclare toujours capacity_forecast=false.

capacity-resources-current-20261008.json : 10 samples, ~500,5 s storage connu,
soit ~0,59 % d'une fenêtre REST de 23,516 h. Collecteur ~0,130 cœur sur les seuls
intervalles connus ; paper ~1,000 cœur sur ~380 s connus, ~121 s inconnus.
Ce coût paper sans session active mérite diagnostic ; moyenne conditionnelle
non extrapolée à toute la journée. 705 passages population complets et zéro
slot overdue au contrôle ponctuel. Pas de capacité machine soutenable prouvée.

Reproduction : commande sustained-capacity ci-dessus. Retour arrière du seul
raccord : retirer resource_series.py et son appel dans le script ; timer et
mesures peuvent continuer indépendamment. Aucun archive payload ou résultat
réservé consulté pour ce contrôle.
