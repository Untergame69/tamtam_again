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
