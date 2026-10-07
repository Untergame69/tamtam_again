# Recherche descriptive sur la population REST

Le paquet `population-descriptive-v1` est distinct des épisodes live du pilote.
Il contient la dernière fiche de périmètre disponible au cutoff : inventaire,
activité, profil descriptif multi-marché, mécanismes et limites connues. Champs
inattendus exclus, preuve account_scope_reports conservée, profil temporel
vérifié. Les comptes protégés sont refusés avant lecture des rapports.

Le paquet permet de poser une hypothèse falsifiable, une demande précise de
données, une non-identifiabilité ou une extension nécessaire. Il ne fournit pas
une règle validée ou un chemin d'exécution complet. Les fills REST ne deviennent
jamais des signaux follower live. Performance et reproductibilité restent
unproven, indépendamment d'un éventuel résumé favorable.

Commande :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-research-packet.py \
  --db data/tamtam.sqlite3 --address ADRESSE --as-of-ms CUTOFF \
  --max-chars 225000 --output /tmp/population-packet.json
```

225000 est un exemple de budget explicite, pas un minimum universel. Si la fiche
entière dépasse le budget, réponse needs_data avec taille nécessaire, aucune
troncature silencieuse. Une fiche sans activité peut être exportable mais ne
constitue pas à elle seule une raison d'appeler un modèle.

Contrôle réel : population-packet-control-20261007.json, 52 comptes hors réserve,
51 exportables et un dépassant le budget. Exemple fonctionnel : premier compte
lexical avec activité observée non nulle, trois marchés/1041 fills observés,
178790 caractères. Critère de choix descriptif explicite, aucun classement par
PnL. Paquet complet local /tmp/population-research-packet.json ; aucune archive
brute ou réserve lue, aucun appel IA.

`population_research.seal` conserve le paquet et la politique dans un registre
indépendant, avec plafond global de requêtes et cooldown par compte. Identité
d'entrée commune aux diagnostics population, incluant le contenu des fills :
un nouveau report_id ou une nouvelle disponibilité sans changement descriptif
ne crée pas de requête. Les anciens rapports sans digest de contenu attendent
une nouvelle collecte. Les rapports sans activité ne motivent pas d'inférence.
Le plafond compte également les échecs et ne se réinitialise pas en changeant
de version de politique. La requête reste sealed ; cette fonction ne dépense
rien et ne démarre pas un modèle. Table additive population_research_jobs ;
créations exportées dans la trace metadata-only.

`population_runtime.run` utilise le runtime isolé vérifié du pilote, avec verrou
partagé et réservation de deux appels avant le premier. Il propose un mécanisme
ouvert puis fait une revue de cohérence ; `hypothesis_recorded` est une hypothèse,
pas une variante, validation ou promotion. Les réponses doivent déclarer type,
marchés observés, signal, entrée/sortie, dimensionnement, risque, horizon justifié,
données requises, limites d'exécution, rejet et preuves présentes dans le paquet.
Réponses/usage conservés, timeout terminal sans retry ; coût incomplet reste
inconnu et réservation conservée. Aucune inférence si vérification d'isolation
échoue. Les comptes devenus protégés sont refusés avant lecture du paquet.

`population_scheduler.tick` détient le même verrou kernel pendant préparation
et appels. Après acquisition, toute requête running laissée par un ancien
worker coopérant devient interrupted, réservation et checkpoints conservés,
coût total inconnu et aucun retry. Le verrou prouve l'absence du worker local
coopérant ; il ne prouve pas que le fournisseur distant n'a engagé aucun coût.
Les réponses/usage sont checkpointés après chaque appel retourné. Une requête
sealed trop ancienne expire avant vérification ou inférence ; sa politique doit
déclarer max_request_age_ms. Pas de nouveau paquet sur une entrée inchangée.

La préparation concerne les comptes population actifs, hors réserves, avec
plafond de nouveaux paquets et appels par tick. Fallback aux fiches disponibles
pour les bases de recette sans ordonnanceur population. Commande :
`PYTHONPATH=src .venv/bin/python scripts/population-research-tick.py --db CHEMIN
--policy POLITIQUE --max-jobs 1`. Ajouter --prepare-only pour ne pas appeler de
modèle. Politique locale `config/population-research-policy.json` : première
tranche huit requêtes au total, cooldown par compte 24 h, expiration 1 h,
deux appels maximum de 120 s/job, réservation 1 USD/appel, 5000 tokens sortie.
Ces limites sont des budgets choisis, aucune certification statistique.

Timer dédié tamtam-again-population-research.timer actif, OnUnitInactiveSec=900,
un job par service et arrêt de nouvelles requêtes au plafond global. Ne pas
augmenter automatiquement le plafond ni relancer une entrée échouée identique.
Le timer pilote existant et ses plans restent séparés. Première recette réelle
complète : population-runtime-success-20261007.json ; hypothèse enregistrée et
revue de cohérence, aucune stratégie validée ni session paper créée.

Rollback : `systemctl --user disable --now tamtam-again-population-research.timer`,
puis arrêter son service (appel éventuellement engagé conserve sa réservation et
sera classé interrupted au prochain worker). Revenir au code ciblé, garder
requêtes/réponses/budgets et archives. Présence antérieure des unités consignée
dans data/rollback/population-research-20261007 ; collecteur et autres timers
ne doivent pas être arrêtés pour ce rollback.

Les hypothèses revues sont importées idempotemment dans research_knowledge avec
source population_research et origine/période complètes. Période conservatrice
de zéro jusqu'à la disponibilité du paquet incluse : aucun épisode favorable
ne réduit le périmètre déclaré. Cette large période peut empêcher une réutilisation
si elle recoupe une réserve non libérée ; le contrôle temporel reste obligatoire.
Statut hypothesis, aucune expérience réussie inventée ou certification économique.
Le scheduler reprend aussi les imports manquants sans rappeler un modèle.

Les paquets suivants peuvent inclure des entrées autorisées et déjà disponibles,
entières, par ordre chronologique dans le budget restant. La mémoire seule ne
change pas le fingerprint descriptif déclenchant une nouvelle requête : une
hypothèse auto-produite ne justifie pas une boucle d'auto-réanalyse.

Reste à raccorder :
routage vers famille d'expérience ou mécanisme unsupported, critères et nouvelles
fenêtres prospectives. La préparation IA existante reste liée au pilote ; ne pas
augmenter son budget global pour intégrer ces fiches. Aucun service modifié.

Tests : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p
'test_population_packet.py'`. Retour arrière ciblé du module/script ; conserver
les fiches et toutes les données de collecte.

## Routage des décisions population

Le scheduler enregistre une route immuable par requête terminale, sans nouvel
appel IA. Les observations manquantes donnent needs_data et un réveil exigeant
leur disponibilité ainsi qu'une nouvelle empreinte d'entrée. Ce réveil reste
un contrat descriptif : il n'est pas encore un vérificateur automatique de
complétude ni une commande de collecte. Une hypothèse sans règle structurée
est specification_required ; aucune prose n'est convertie implicitement en
signal du pilote. Un executable_spec éventuel doit conserver marchés et type
et passer le contrat de capacité. Un moteur expérimental sans adaptateur N1/N2
reste unsupported_validation_adapter. Un moteur intégré demande un nouveau
plan prospectif, critères et budget ; la route ne crée aucun plan/variant/paper.

Table additive population_hypothesis_routes : date, diagnostic, preuve, état,
réveil et prochaine action. Les routes rejouées conservent leur décision originale.
Les deux hypothèses réelles ont des besoins de données : preuve
population-routing-control-20261007.json. Certaines demandes (cibles privées,
couverture extérieure, priorité de file) peuvent être inaccessibles ; le travail
suivant doit distinguer ces cas d'une simple attente de collecte. Aucun contrôle
ne prétend qu'accumuler davantage de fills suffira.

Retour arrière : annuler uniquement les changements de routage/scheduler,
conserver la table et les requêtes. Le raccordement automatique à un plan puis
à son évaluation demeure à terminer.

## Observation ciblée des ordres publics

population-collect-orders.py interroge une adresse explicitement choisie et un
à trois DEX : historicalOrders puis frontendOpenOrders par DEX. Aucun nouvel
abonnement utilisateur ni timer activé. Les réserves sont exclues avant requête.
Le client partagé réserve 120 poids pour historicalOrders (borne 2 000 lignes)
et 20 pour chaque inventaire ouvert ; retries et attente passent par la base
commune de télémétrie. Une nouvelle cadence doit entrer dans le budget mesuré.

Réponses complètes archivées, empreinte de contenu, statuts et ordres ouverts
résumés dans population_order_reports. Les snapshots séquentiels n'établissent
pas une trajectoire d'inventaire ou un cycle d'amendements exhaustif. Réception
locale distincte des statusTimestamp ; couverture historique et file inconnues,
ancien passé et cibles privées non reconstitués. Les paquets futurs incluent
uniquement le résumé disponible au cutoff. Un contenu d'ordres nouveau peut
changer l'empreinte de recherche, mais un nouveau timestamp seul ne le peut pas.
Les paquets déjà scellés restent immuables. Les besoins d'une hypothèse ne sont
pas marqués satisfaits simplement parce qu'une réponse existe.

Sources officielles vérifiées le 7 octobre 2026 :
[Info](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
(historique récent borné et inventaire ouvert),
[Subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
(orderUpdates),
[Quotas](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).
Le flux orderUpdates est documenté ; son intégration prospective reste à faire.
Les données publiques ne prouvent pas une couverture sur une plateforme externe
ou l'intention de ciblage du compte.

Commande explicite :
```sh
PYTHONPATH=src python3 scripts/population-collect-orders.py --db data/tamtam.sqlite3 --telemetry-db data/tamtam.telemetry.sqlite3 --address ADRESSE --dex '' --output /tmp/public-orders.json
```
Rollback : annuler le code ciblé, conserver population_order_reports et archives.
Aucun redémarrage collecteur requis pour cette commande indépendante.

La mémoire réutilisée conserve désormais toute l'union de ses périodes sources,
y compris d'autres comptes/marchés. Chaque connaissance héritée reste une preuve
typée, avec date de création et contrôle de disponibilité ; le point générique
save_knowledge refuse aussi de supprimer ces périodes. La disponibilité du
paquet est au moins celle de toute connaissance qu'il inclut. Son empreinte
qui déclenche une nouvelle analyse reste fondée sur les observations, pour
éviter une boucle provoquée par sa propre mémoire. Cette correction ne libère
aucune réserve et ne réécrit pas les imports existants.

## Raccordement explicite à une famille d'expériences

population-register-experiment.py lie une hypothèse revue contenant un
executable_spec, sans required_data non résolu, à un nouveau plan du même
compte/réseau/marché et un profil borné référant cette hypothèse. Le plan porte
ses critères/budgets et ses nouvelles fenêtres ; aucune valeur universelle
n'est copiée implicitement des pilotes. Pour les données réelles, le plan est
créé après revue, la famille est figée avant comparaison et l'exploration couvre
les informations du paquet. Les mécanismes sans adaptateur intégré restent
unsupported ; aucune prose n'est traduite automatiquement en leader_delta.

Le lien est immuable et rejouable. La famille est enregistrée atomiquement par
le composant existant ; si le processus s'arrête après ce commit avant le lien,
la même requête/profil retrouve la même famille. Un autre profil ou une famille
existante différente est refusé. Les anciennes variantes/pilotes restent intactes.
La trace référence la date du lien. Comparaison, sélection unique puis finale
et promotion sont assurées par les gates existants du pipeline, sans appel IA.

```sh
PYTHONPATH=src python3 scripts/population-register-experiment.py --db data/tamtam.sqlite3 --request-id REQUETE --plan-id NOUVEAU_PLAN --profile PROFIL.json --output /tmp/population-experiment.json
```

Recette dédiée : test_population_experiments.py vérifie l'enregistrement, le
rejeu, refus de données manquantes/pilote existant/comparaison passée, reprise
après incident, puis comparaison/finale et paper explicitement synthétique.
Cette capacité ne compile pas encore automatiquement les hypothèses en prose
et ne crée pas leur plan : le parcours automatique population complète reste
à finir. Aucun lien réel enregistré pour obtenir artificiellement une promotion.
Rollback : annuler uniquement le module/script/référence de trace ; préserver
population_experiment_links, familles, variantes et plans. Ne pas restaurer la
base de collecte pour annuler ce raccordement.

## Création des plans population

population-prepare-plan.py crée le plan et sa famille à partir d'une politique
population-plan-v1 et d'un profil explicitement justifiés. Aucun horizon de deux
minutes ni durée de pilote réutilisé par défaut. Champs requis : justification,
max_plans, comparison_delay_ms, comparison_duration_ms, selection_gap_ms,
final_duration_ms, criteria, budget et isolation. Ces valeurs sont des choix
expérimentaux, pas des seuils universels de robustesse. Le profil reste le
contrat existant (axes classés, justifiés, avec preuves et nombre maximal).

L'embargo couvre le maximum horizon/lookback plus latence de toutes les
combinaisons préenregistrées. Exploration inclut disponibilité du paquet et de
sa revue ; comparaison future après embargo ; finale après comparaison et un
délai de sélection au moins égal à l'embargo. Le budget de durée couvre ces
fenêtres et celui d'évaluations couvre toutes les comparaisons plus une finale.
Les informations de la revue doivent déjà être disponibles.

population_plan_drafts conserve une fois l'ancre, critères, origine et fenêtres.
Une interruption ne les décale pas ; une politique/profil modifié est refusé
pour la même requête. max_plans compte globalement ces réservations, y compris
une préparation interrompue. Les liens déjà enregistrés sont rejouables. Si une
préparation réelle manque sa comparaison avant d'avoir terminé, elle est refusée
par les gates prospectifs ; une nouvelle hypothèse/expérience justifiée est
nécessaire, sans rendre vierge une ancienne période. Aucun appel IA ni abonnement
utilisateur n'est lancé par cette commande.

```sh
PYTHONPATH=src python3 scripts/population-prepare-plan.py --db data/tamtam.sqlite3 --request-id REQUETE --policy POLITIQUE.json --profile PROFIL.json --output /tmp/population-plan.json
```

Les hypothèses sans executable_spec ou avec required_data restent dans leur
état explicite et ne créent aucun draft. Le timer n'a pas reçu de politique
universelle : compiler les règles et produire des profils justifiés pour chaque
piste reste à intégrer. Fixtures seules pour cette recette ; aucun nouveau plan
réel ajouté. Rollback ciblé : module/script/appel, conserver drafts, liens et
familles. L'adaptateur réutilise le verrou commun sans le réacquérir en cascade.

## Sortie IA structurée et préparation par scheduler

Le runtime population v2 peut fournir executable_spec et experiment_profile en
plus de l'hypothèse descriptive, uniquement ensemble et avec paramètres justifiés.
Le code vérifie périmètre/type, request_id du profil, preuves des axes présentes
dans le paquet scellé, capacité et budget cartésien des profils exécutables.
La critique reçoit ces objets pour vérifier fidélité et causalité ; elle ne les
réécrit pas. Le contrat décrit les capacités actuelles sans imposer leur choix :
un mécanisme différent reste unsupported, jamais converti pour entrer dans
momentum/leader_delta. Les anciens résultats et paquets restent immuables.

Le scheduler accepte optionnellement --plan-policies FICHIER, dictionnaire
request_id→politique population-plan-v1 fourni séparément du modèle. Seules les
routes prospective_plan_required avec profil justifié sont préparées, au plus
max_jobs par passage ; les liens déjà créés sont ignorés pour ne pas empêcher
la préparation des suivants. Critères/fenêtres/budgets ne sont pas choisis par
le modèle. Aucun fichier de ce type n'est activé dans le timer de production.
Une politique absente ou un mécanisme non intégré laisse une prochaine action
explicite. --prepare-only n'appelle aucun modèle mais peut préparer les plans
explicitement autorisés par ce fichier.

Test intégré synthétique : deux rôles IA simulés→hypothèse structurée→mémoire et
route→absence de plan sans politique→création avec politique→rejeu sans doublon,
sans appel supplémentaire ni paper. Ce test porte sur l'orchestration ; il ne
qualifie aucun mécanisme réel. Les coûts/délais/risques déclarés doivent encore
être attestés par leurs données, une validation de schéma ne prouve pas leur
réalisme. Le parcours complet et les mécanismes multi-instruments restent à
raccorder. Rollback ciblé runtime/scheduler, garder réponses, budgets et plans.
