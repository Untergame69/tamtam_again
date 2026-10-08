# Reprise après revue indépendante b3c4412

Ordre : R1/R2, qualification réelle R3, raccordement R4. Aucune validation économique n'est acquise par les tests. Collecte conservée active ; budget IA réel inchangé.

## R1 — acquisitions : corrigé pour le collecteur population

Le hash identifie le contenu ; `receipt_id` identifie chaque nouvelle réception du collecteur population, même si contenu, fenêtre et requête sont identiques. Les paramètres de requête participent également à l'identité du stockage. Les consommateurs conservent le format des lignes et leurs références. Le contenu reste compressé dans chaque ligne : ce lot ne revendique pas une mutualisation physique des blobs.

Migration additive de `receipt_id`, remplacement de l'index unique. Les lignes anciennes et leurs horodatages restent inchangés, avec identifiant de réception vide. Les acquisitions auparavant perdues restent perdues : aucune preuve rétroactive n'est fabriquée. Les autres sources conservent leur déduplication de contenu par paramètres ; cette correction porte sur la collecte population examinée par la revue.

Vérification : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_review_receipts.py -q` : deux tests, acquisitions répétées, deux comptes, inventaire partagé, DEX identiques, migration sans réception inventée.

Retour arrière : conserver cette migration et la logique d'identité de réception lors d'un retour du reste du code. Ne pas remettre l'ancien index unique après plusieurs réceptions identiques : il refuserait les données. Aucune suppression des nouvelles preuves pour permettre un rollback. Une restauration intégrale d'une sauvegarde ancienne ferait perdre les collectes intervenues depuis ; elle n'est pas une procédure autorisée ici.

## R2 — pagination : corrigé

Les pages pleines prouvent le préfixe avant le dernier timestamp, jamais la frontière saturée. La page suivante repart inclusivement à cette frontière. Le terminal court ferme l'intervalle ; une frontière de fin encore saturée reste un trou ponctuel. Le collecteur archive `covered_until_ms` avant d'avancer son curseur. Les anciennes pages valides peuvent fournir leur dernier timestamp depuis leur contenu enregistré, sans changer leur provenance ni inférer une page absente.

Vérification : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_population_history.py -q` : douze tests, dont plusieurs pages, reprise après incident, jobs successifs, page manquante, doublons inclusifs et timestamp saturé. Pagination couverte demeure distincte de rétention et de qualification économique.

## R3 — à terminer

Qualification sur cas réels contrastés puis application automatique aux cas admissibles. L'adaptateur actuel ne permet pas encore cette qualification ; attendre davantage n'en termine pas le code.

## R4 — à terminer

Allocation d'expérience par le service, réveil des besoins, worker après diagnostic et nouvelle décision prospective, cycle temporel des réserves. Budget réel épuisé conservé ; démonstration isolée autorisée avec marchés et réponses IA simulés.

## Jalon R3 — parcours public exploitable livré, qualification globale partielle

`population-qualification.py` applique automatiquement la même règle à tous les comptes inventoriés admissibles : dernière paire adjacente de valorisations disponibles. Les périodes sont explicites et ne sont pas alignées pour un classement comparatif. Les exemples contrastés sont choisis sur mode et disponibilité, jamais sur leur PnL.

Le nouveau `public_scope_assessment` mesure le périmètre indépendant du DEX perp validator USDC pour les modes standard (`disabled`, `default`). Il expose capital, flux attribuables, variation nette, rendement Modified Dietz approximatif, composantes observées et résidu. Les transferts `send` à frais explicitement nuls utilisent adresse et DEX source/destination ; un mouvement spot→perp de la même adresse est externe au périmètre perp, interne à l'adresse. Les dépôts/retraits sans attribution de DEX, frais de transfert non nuls et mécanismes inconnus bloquent la mesure corrigée des flux. Les frais déjà inclus dans les fills ne sont pas chargés deux fois.

La réconciliation conditionnelle raccorde les preuves de pagination funding/ledger, leur classement, les bornes de capital et le témoin de rétention des fills. Son périmètre est le contrat public de l'API : aucune garantie indépendante sur une omission fournisseur, aucune consolidation extérieure. Une pagination seule ne valide toujours pas la rétention des fills. Les composantes incomplètes peuvent être comparées au capital mesuré, mais leur résidu reste un diagnostic, jamais un revenu inventé. Les réceptions répétées des mêmes valorisations ne sont plus des conflits financiers ; une valeur différente au même timestamp le reste. Des positions mal formées ne deviennent pas un inventaire vide.

### Contrôle réel

Preuve : `r3-public-scope-control-20261008.json`, cutoff `1791460625900`.

- 69 comptes admissibles examinés, 10 périmètres publics mesurés, zéro portefeuille entier économiquement qualifié, zéro stratégie validée.
- Compte standard `0x87f9…e2cf` : capital +832 647,0000000001 USDC, transferts nets +832 647 USDC, variation corrigée ≈0. Ce résultat ne devient plus une performance positive apparente. Attribution des fills encore incomplète faute de témoin atteignant le début de sa période.
- Compte standard `0xa880…24ee`, intervalle de 425 936 ms : capital net +145,504772 USDC ; composantes +145,561325 ; résidu −0,056553. Rendement de période ≈0,064094 %, uniquement sur ce périmètre. Réconciliation des entrées sous contrat public disponible après un appel `userFills` supplémentaire (2 000 fills, quota partagé). Le résidu n'est ni effacé ni automatiquement accepté. Aucun verdict sur la rentabilité future.
- Cas unified et portfolioMargin : pas d'equity fabriquée depuis les états par DEX. L'état spot archivé ne porte pas de timestamp économique ; l'inventaire séquentiel ne fournit pas de valorisation atomique avec les dérivés et dettes. Obtenir uniquement davantage de fills ne résout pas cette absence. Pour une mesure exacte consolidée, il faut une source de valorisation cohérente et horodatée, ou un modèle explicite d'intervalles/prix et de chevauchement spot/dette. Ces capacités ne sont pas revendiquées livrées.

Les rapports stricts historiques restent disponibles ; le nouveau calcul conditionnel est explicitement distinct. Ni `economic_validation` global ni validation de stratégie ne sont promus. La qualification globale multi-modes reste partielle, avec limites démontrées sur ces sources et modèle d'acquisition annoncé.

Commande réelle reproductible :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-qualification.py --db data/tamtam.sqlite3 --as-of-ms 1791460625900 --output /tmp/r3-qualification.json
```

Retour arrière : retirer le nouveau chemin de rapport et la commande ; conserver les observations nouvelles. Aucun schéma, service, budget ou pilote n'a été modifié par R3. Conserver la migration R1 lors de tout retour de code.

### Complément R2 issu du contrôle réel

`9c7a57e` corrige une sous-fenêtre dont la borne finale est strictement à l'intérieur d'un préfixe parcouru : elle est couverte même sans page terminale à cette borne. Une borne égale au timestamp saturé demeure un trou ponctuel. Test ciblé ajouté ; aucune réception historique changée.

Vérification R3 : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q` : **384 tests OK en 31,158 s**. Tests supplémentaires : flux send inter-adresses/inter-DEX, frais non nuls, mode partagé, valeur manquante, paquet source→adapter→réconciliation, disponibilité au cutoff, application à tous les candidats et réceptions répétées de valorisation. Les fixtures n'ont qualifié aucun compte réel.

## R4 — première transition raccordée : allocation d'expériences par le service

`experiment-allocation-v1` fournit une politique externe à tous les `prospective_plan_required`, dans l'ordre de disponibilité/request_id. La CLI et le service installé utilisent `--experiment-policy config/experiment-allocation-policy.json` ; le dictionnaire manuel par request_id reste un outil explicite facultatif, plus une dépendance du service.

La politique est enregistrée immuablement par `policy_id` et empreinte dans `experiment_allocation_policies`. Le modèle ne fournit aucun critère de promotion ni budget. Profil > cap externe ⇒ attente avec diagnostic, jamais réduction silencieuse du nombre d'essais. Les critères numériques restent fixes ; blocks et fenêtres sont seulement étendus, avant observation, pour couvrir l'empreinte causale déclarée et le nombre de blocks. Le budget de durée reste fixe : un profil trop long ne l'augmente pas. Les drafts conservent toujours leur ancrage, leurs critères et leur plafond global à travers les versions de politique.

Paramètres choisis pour cette première allocation : 8 plans au plus, 4 variantes par profil au plus, comparaison ≥3 jours, finale ≥7 jours, blocks ≥1 heure et ≥empreinte causale, 24 blocks au moins, funding exigé, coûts ×2 en stress. Ce sont des budgets et filtres pilotes explicitement configurables, pas des seuils universels de preuve. L'isolation réelle reste déclarée `unavailable` ; cette allocation ne prétend pas la fournir. Le coût d'évaluation de plan n'est pas une nouvelle tranche d'appels IA.

### Vérification

- **388 tests OK en 36,132 s**, dont scheduler via le même `tick`, proposition/revue simulées, allocation sans mapping de request_id, retry sans nouvelle fenêtre, politique immuable, cap de variantes et budget inchangés.
- Commande réelle `population-research-tick.py --prepare-only ... --experiment-policy ...` : zéro job scellé, zéro modèle, zéro plan créé, huit routes existantes. Sept restent `needs_data`, une `suspended`.
- Véritable service installé exécuté une fois : `Result=success`, `ExecMainStatus=0`, argument d'allocation présent dans `ExecStart`. Les huit essais de la tranche réelle restent huit ; aucune nouvelle session paper. Collecteurs et timer population restent actifs.
- Table additive de politique créée en production ; fichier du seul service recherche population ajusté, `daemon-reload`, aucune cadence changée. Aucun arrêt/restart du collecteur.

Retour arrière du service : retirer seulement l'argument `--experiment-policy config/experiment-allocation-policy.json` de son ExecStart et lancer `systemctl --user daemon-reload`. Une copie préalable existe dans `/tmp/tamtam-again-population-research.before-r4-allocation.service`. Conserver la table de politique et les drafts ; ne pas les supprimer ou déplacer les fenêtres pour réarmer les essais. Les prochains plans n'ont pas encore été créés dans le réel.

### R4 reste partiel

Restent : besoins de collecte/réveil exécutables, protection temporelle des nouvelles adresses avec maintien des pilotes, worker de recherche après diagnostic paper et proposition vers nouvelle décision prospective ; puis recette complète par points d'entrée de production avec interruptions/reprises/budgets/idempotence. Le scellement paper seul ne remplit pas ce parcours. La tranche IA réelle épuisée reste épuisée.

## R4 — cycle temporel des réserves raccordé

Le service population reçoit maintenant `--reserve-policy config/reserve-cycle-policy.json`. La politique `reserve-cycle-v1` est immuable par identité/empreinte. Elle ne traite que les plans liés par `population_experiment_links` et dont l'origine correspond à la demande revue. Les pilotes historiques sans cette origine restent protégés, y compris si un autre plan sur la même adresse est clos.

Après la fin de la finale +1 heure de grâce choisie, les fenêtres évaluées peuvent devenir des données de développement. Une évaluation encore `running` interdit la libération ; ce module n'infère jamais son interruption. Une finale terminée doit conserver sa preuve de consommation sur le périmètre et les bornes exacts. Les résultats et statuts d'origine ne sont ni lus ni modifiés.

À défaut de finale évaluée, la politique choisit une échéance explicite de 24 heures après sa fin : la fenêtre manquée est `abandoned_for_development`. Cette libération ne fabrique aucune évaluation. Un marqueur `development-release:<plan_id>:final` dans `consumed_holdouts` conserve le caractère utilisé de cette période, avec timestamp de libération réel ; le garde de chevauchement existant empêche qu'elle serve ultérieurement de finale vierge. Deux fenêtres/libérations et la consommation sont atomiques et rejouables après incident. Le pipeline ne tente plus de réévaluer un plan dont la finale a été abandonnée pour développement.

La protection par adresse disparaît pour une expérience population uniquement lorsque ses deux fenêtres sont libérées ; tout nouveau plan réel non libéré sur cette adresse la protège à nouveau. Les autorisations de mémoire restent temporelles. Les exports de comptabilité, périodes observées et paquets population contrôlent aussi le cutoff demandé avant toute requête de payload : une libération actuelle ne donne aucun accès dans un export représentant une décision passée pendant la réserve, frontière incluse. Les paquets conservent les preuves de libération et leur disponibilité ; celle-ci n'est jamais présentée comme une nouvelle réception de marché.

### Preuves et état réel

- Tests isolés : délais/grâce, finale manquée, finale évaluée avec consommation, original échec inchangé, évaluation running, pilote historique sur la même adresse, nouvelle réserve, arrêt transactionnel/reprise, refus de réutilisation via le véritable moteur, cutoff historique prélecture et pipeline de production ne réévaluant plus la finale abandonnée.
- Préflight par la CLI réelle : zéro fenêtre libérée, zéro nouveau plan, zéro modèle ; les 11 checks immuables des 8 plans et 3 variantes concordent avec le checkpoint initial.
- Service réel exécuté : `Result=success`, `ExecMainStatus=0`, argument `--reserve-policy` présent ; collecteur et timer population actifs. Les huit essais réels restent huit. Aucune période pilote ni résultat réservé n'a été ouvert.
- Migrations additives : `reserve_cycle_policies`, `research_window_releases`. Aucun marqueur de développement ajouté aux holdouts de production : aucune expérience population liée n'est encore admissible à cette libération.

Les heures de grâce/abandon sont des choix opérationnels configurables ; elles ne constituent pas des seuils statistiques de maturité. Le budget IA réel reste épuisé.

Retour arrière : retirer l'argument `--reserve-policy config/reserve-cycle-policy.json` du seul service recherche population, puis `systemctl --user daemon-reload` (copie préalable `/tmp/tamtam-again-population-research.before-reserve-cycle.service`). Conserver toutes les libérations et consommations : une donnée exposée ne redevient pas réservée vierge. Le retour de code à une protection conservatrice de toute l'adresse reste possible sans supprimer ces registres.

R4 reste partiel : worker paper et nouvelle proposition/décision prospective, besoins de collecte exécutables/réveil et démonstration du parcours complet par entrées de production. Aucun parcours réel jusqu'au paper n'est revendiqué ici.

Vérification fraîche de ce lot : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q` : **397 tests OK en 37,957 s** (neuf tests nouveaux du cycle de réserves). Les tests d'abandon n'injectent aucune réussite économique : ils exercent le garde de consommation et la reprise avec des preuves synthétiques explicitement temporaires.

## R4 — worker paper raccordé, checkpoint pour revue

Le scheduler de production accepte `--paper-policy config/paper-research-policy.json`. Il scelle les diagnostics disponibles, exécute proposition et revue dans le même runtime isolé que la recherche population, conserve une mémoire typée, puis applique l'allocation externe pour créer une nouvelle expérience prospective. L'origine paper et la session/variante parente sont conservées. La session précédente, ses positions et ses résultats ne sont pas réinitialisés.

Les deux origines partagent le plafond existant de **8 essais**, tous statuts compris. Aucun budget supplémentaire, aucune remise à zéro. Une interruption consomme l'essai et ne relance pas automatiquement le modèle. Les paquets sont revérifiés avant exécution, avec autorisation temporelle inclusive et disponibilité des preuves de libération. Une file bornée de diagnostics évite qu'un premier paquet invalide monopolise l'inspection.

### Vérifications

- Suite complète fraîche : **403 tests OK en 39,514 s**. Commande : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q`.
- Six tests d'intégration paper : proposition/revue simulées → mémoire → nouveau plan prospectif ; idempotence ; budget partagé épuisé ; expiration/interruption ; paquet modifié ; garde des réserves avant lecture et inspection bornée. Le diagnostic initial est une fixture : ces tests ne prouvent pas encore le parcours entier depuis une décision paper produite automatiquement.
- Préflight CLI réel avec `--paper-policy` et `--prepare-only` : zéro job paper, zéro modèle, zéro plan et zéro réserve libérée. Production : huit jobs population, zéro job paper, zéro session paper. L'absence de table de liens d'expériences confirme qu'aucune nouvelle expérience liée n'a été créée.
- Collecteur principal actif/running. L'installation du seul service recherche a été ajustée sans redémarrer le collecteur. Une première exécution a échoué sur `database is locked` dans l'enregistrement de la politique d'allocation ; le job de découverte présente aussi ce conflit. Ne pas confondre timers actifs et exécutions réussies. Cet incident d'écriture concurrente reste à diagnostiquer si le retry ne réussit pas.

### État et suite

R1/R2 corrigés avec tests de non-régression. R3 fournit des mesures économiques publiques conditionnelles sur des cas réels ; aucune qualification globale ou stratégie rentable n'est certifiée. R4 **partiel** : allocation, cycle des réserves et worker paper raccordés. Restent les besoins de collecte/réveil exécutables et la recette complète par entrées de production, sans injection manuelle des décisions essentielles. Aucune extension de supervision ou VPS dans ce lot.

Retour arrière : retirer `--paper-policy config/paper-research-policy.json` du service puis `systemctl --user daemon-reload` ; copie préalable `/tmp/tamtam-again-population-research.before-paper-worker.service`. Conserver les tables additives, essais, coûts, preuves, fenêtres et mémoires ; ne jamais restaurer un budget en supprimant les jobs.

Le second lancement du service recherche a réussi : `Result=success`, `ExecMainStatus=0`. Le collecteur demeure actif. Cette reprise réussie ne résout pas la cause des conflits SQLite ni les échecs du job de découverte.

## R4 — suppression du contournement de surveillance dans les fixtures

Le tick réel et le tick synthétique utilisent maintenant la même fonction transactionnelle de surveillance, suspension, snapshot et diagnostic. La recette peut produire une demande après perte ou interruption à partir des seuls événements ; elle n'a plus besoin d'insérer cette décision. L'horloge synthétique est explicite et ne peut précéder les événements disponibles. La recette élémentaire démarre désormais sa session à son horloge simulée, sans snapshot rétrospectif.

Quatre tests ciblés vérifient : interruption produisant le diagnostic, événements de perte produisant une demande de recherche, rollback atomique sur incident pendant le diagnostic puis reprise, refus d'une horloge précédant les événements. La fixture comparative existante a été corrigée pour fournir connexion, quote et heartbeats pendant les périodes d'attente : elle était auparavant tolérée sans surveillance. Ses décisions restent scriptées et ne prouvent pas le parcours autonome intégral.

Aucun service, budget ni donnée de production modifié dans ce lot. Le collecteur principal reste actif. Retour arrière : revenir au commit précédent pour ces fonctions et fixtures ; conserver tous les diagnostics et snapshots déjà produits. R4 reste partiel jusqu'à la recette complète et au réveil des besoins exécutables.

Vérification fraîche : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q` : **407 tests OK en 36,633 s**. Aucune stratégie réelle qualifiée par ces fixtures.

## R4 — recette chronologique de reprise jusqu'à une nouvelle décision

Commande reproductible sans DB de production :

```sh
PYTHONPATH=src .venv/bin/python scripts/adaptation-recipe.py --output /tmp/tamtam-adaptation-recipe
```

La recette utilise le `population_scheduler.tick` réellement appelé par le service, sa politique externe d'allocation, et le pipeline partagé avec un mode synthétique chronologique respectant les échéances N1. Aucun mapping de politique par request_id, statut de promotion, sélection finale, suspension ou diagnostic n'est injecté en SQL. Les seules entrées simulées sont un rapport de périmètre initial, les événements de marché et les réponses proposition/revue. L'isolation du fournisseur est mockée ; ses vérifications réelles restent séparées.

Parcours vérifié : rapport disponible → proposition/revue → plan alloué → comparaison → sélection déterministe → finale → paper → événements causant le risque → suspension/diagnostic atomiques → fermeture/réouverture de base → proposition/revue paper → nouvelle expérience à fenêtres futures. Quatre appels de rôle simulés, un job population, un job paper, deux plans, une session et un diagnostic. La finale n'est pas évaluée avant sa fin ; la session parente et ses positions sont conservées ; le retry ne crée aucun plan ni appel.

Ce parcours a révélé une tentative de paquet d'historique protégé avant dispatch paper : le scheduler vérifie désormais l'autorisation d'historique avant ce scellement et poursuit les autres transitions autorisées. Le contrôle du paquet demeure également présent.

Limites : qualification économique initiale fournie en fixture, pas démontrée par cette recette ; profitabilité scriptée pour N1 ; pas de remplacement effectif par la nouvelle version ni évaluation de ses fenêtres futures. Les tests d'interruption du worker et d'épuisement du budget restent des tests complémentaires. Aucun modèle/fournisseur réel, aucune donnée de production ou service modifié par la recette. Collecte conservée.

R4 reste partiel pour les besoins de collecte/réveil exécutables et l'incident SQLite. Ce jalon prouve une nouvelle décision prospective après diagnostic, sans prouver la valeur économique de l'adaptation entière. Retour arrière : retirer la recette et revenir aux fonctions scheduler/pipeline du précédent commit ; conserver les registres, essais et fenêtres de production.

Suite complète fraîche : **408 tests OK en 38,324 s**, commande habituelle `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q`. Recette CLI exécutée séparément avec succès.

## Incident bloquant la découverte : contention SQLite

Deux essais contrôlés du service ont échoué, dont le dernier fournit le code moteur exact : `SQLITE_BUSY` (5), et non `SQLITE_BUSY_SNAPSHOT`. Échec après environ dix secondes dans l'écriture de la provenance du classement, avant toute connexion de découverte pour cet essai. Le collecteur principal reste actif. Une observation des verrous WAL a identifié son PID comme détenteur intermittent du verrou d'écriture ; cela ne prouve pas à lui seul toute la cause des contentions.

Correction ciblée : une fenêtre/provenance identique déjà complète retourne désormais son identité sans demander un verrou d'écriture. Une provenance incomplète reste réparable. Un test maintient un écrivain concurrent et vérifie que le rejeu identique réussit avec un busy_timeout d'une milliseconde, puis que la suppression d'un lien est réparée. Le job affiche maintenant uniquement le code/nom d'erreur SQLite lors d'un échec, sans payload ni paramètres SQL.

Ce lot ne prétend pas éliminer les conflits lors des nouvelles écritures. Il supprime la contention inutile du rejeu du classement. Aucun collecteur principal redémarré, aucune cadence, quota, stratégie ni budget changé. Les besoins de collecte/réveil exécutables restent à raccorder. Retour arrière : revenir aux fonctions de découverte et au script du précédent commit ; conserver les fenêtres et provenances.

Contrôle après correction : le service franchit le rejeu du classement, collecte la session bornée, puis échoue sur `SQLITE_BUSY` dans `save_observation` à l'enregistrement de nouveaux événements (15:06:09 locale). Le service de découverte n'est donc pas rétabli. Suite complète : **409 tests OK en 39,425 s**. Le prochain correctif doit traiter la conservation/reprise de cette écriture, sans répétition de la connexion pour remplacer les événements perdus.

## Conservation et reprise des réceptions de découverte

Avant toute insertion SQLite, une session terminée est sérialisée avec empreinte dans `data/discovery-pending/<session>.json`, via fichier temporaire, fsync et renommage atomique. Réceptions, session, marchés, bornes et diagnostic de transport sont conservés. Une erreur d'ingestion laisse le fichier en place ; le prochain job reprend les fichiers avant toute nouvelle connexion. Une reprise partielle déduplique les observations, conserve leurs timestamps et reconstruit les mêmes provenances. La disponibilité d'ingestion est ancrée séparément après acquisition du verrou d'écriture ; elle n'est pas antidatée à la réception WebSocket.

Le rapport complet est conservé dans la table existante `discovery_sessions` avant retrait du spool ; le rapport de sortie est actualisé lors d'une reprise. La table additive `discovery_ingestion_receipts` conserve les disponibilités par session/marché. Une table `discovery_ingestions` a été créée pendant le premier contrôle réel de cette tranche : ses lignes sont conservées, mais le chemin final utilise `discovery_sessions`. Aucun historique supprimé. Les compteurs de nouveaux candidats pendant une reprise sont explicitement des bornes inférieures si des inscriptions partielles ont précédé le rapport.

La reprise est bornée à deux sessions par job, huit au plus par appel explicite ; elle ne consomme aucun abonnement supplémentaire. Un fichier modifié/incomplet reste conservé et bloque la connexion suivante jusqu'à traitement explicite. Les fichiers temporaires complets peuvent également être repris. La garantie porte sur les sessions ayant atteint l'écriture durable ; elle ne prétend pas récupérer des événements encore seulement en mémoire au moment d'un arrêt brutal.

Tests ciblés : stockage indisponible → spool conservé → reprise sans connexion ; interruption après commit raw → pas de doublon ni retiming ; empreinte modifiée refusée et fichier conservé ; script de production reprenant avant toute connexion et actualisant le rapport. Premier contrôle réel : service discovery réussi, zéro fichier en attente, collecteur principal actif. Cela prouve une ingestion réussie, pas l'absence de toute contention future.

Aucune cadence ou politique IA changée. Les besoins de collecte/réveil des hypothèses restent à raccorder. Retour arrière : arrêter uniquement les nouveaux jobs de découverte avant retour du code, conserver et reprendre tous les fichiers en attente avec cette version ; ne pas les supprimer. Conserver les tables, identités et observations. Le collecteur principal peut rester actif.

Suite finale fraîche : **413 tests OK en 40,603 s**. Le dernier essai réel a rencontré à nouveau une contention et laissé **un fichier durable en attente**, aucun temporaire ; les événements sont donc conservés pour reprise. Un nouveau lancement du même service traite exclusivement cette reprise, sans ouvrir une session supplémentaire.

Preuve réelle de reprise : lancement suivant terminé `Result=success`, `ExecMainStatus=0`, rapport `recovery_only=true`, une session reprise, zéro pending. Aucun nouveau WebSocket dans ce lancement. Les événements de la session ayant échoué ont été ingérés ; collecteur principal actif. La cause générale de la contention reste ouverte, mais la conservation/reprise de ce cas est démontrée en réel.

## R4 — contrat explicite des observations manquantes

Une proposition peut fournir `observation_requests`, exactement une demande par indice de `required_data`, avec source, endpoint, bornes, preuve attendue et décision permise. Aucun budget ou critère de réussite accepté dans ce contrat IA. Les schedulers population/paper conservent ces demandes dans `research_observation_plans`, séparément des routes/hypothèses immuables.

Capacité déclarée : historique REST public via userFillsByTime, userFunding et userNonFundingLedgerUpdates ; preuve de pagination uniquement. Une autre source ou preuve produit une incapacité d'acquisition/preuve explicite, sans rejet économique ni invention de complétude. Fenêtre future : attente de sa borne ; période réservée : refus avant lecture de payload. Ces états sont des diagnostics à la date d'enregistrement ; le futur dispatcher devra les réévaluer, pas réutiliser une ancienne autorisation.

Les demandes descriptives historiques restent intactes et deviennent `structured_request_required`, pas « données satisfaites » ni « source impossible ». Préflight réel de la CLI avec politiques existantes et `--prepare-only` : **7 demandes structurées requises**, zéro scellement, modèle ou plan nouveau. Le budget réel de huit essais reste épuisé. Ce résultat montre pourquoi attendre davantage ne constitue pas à lui seul un réveil de ces sept hypothèses.

Tests : contrats complets et sans doublons, refus de mapping partiel/budget IA, source/preuve non supportée, legacy conservé, fenêtre future et réserve contrôlée sans lecture raw, idempotence du registre. L'exécuteur de collecte et la vérification des conditions de réveil restent à implémenter sous politique externe : `dispatch_authorized=false` est explicite. R4 reste partiel.

Migration additive : `research_observation_plans`. Aucun service ni cadence modifié, collecteur principal actif. Retour arrière : retirer ce raccordement metadata et revenir au précédent runtime/scheduler ; conserver le registre, les propositions et essais.

Suite complète finale : **416 tests OK en 37,627 s**. Les fixtures de demandes ne qualifient aucune stratégie réelle.

## R4 — acquisitions bornées et réveil vers le paquet population

Le service population reçoit `--needs-policy config/research-need-collection-policy.json`. La politique immuable `history-needs-pilot-v1` alloue une demande par job existant, une page par tentative, six tentatives au plus par demande. Ces valeurs sont des budgets choisis, pas des critères de preuve économique. Le client et le bail sont ceux du collecteur population ; le quota REST/IP partagé demeure inchangé. Aucun abonnement utilisateur ou tranche IA ajouté. Les comptes hors ordonnanceur n'obtiennent pas de nouveau slot par ce module.

Les demandes utilisent des curseurs `need:<empreinte>:<endpoint>` séparés des curseurs ordinaires. Le dernier timestamp est repris inclusivement ; les pages brutes sont conservées avant avancement du curseur. Source/proof non supportée, fenêtre future, réserve active, budget épuisé et timestamp saturé ont des attentes explicites. Un timestamp saturé non résolu n'est pas interrogé indéfiniment. Aucun payload réservé lu. Le garde existe aussi dans le collecteur scoped, avant appel fournisseur.

Chaque tentative est conservée dans `research_need_collection_attempts`, y compris erreurs et bail révoqué. Un ancien worker ne publie pas le réveil après reprise de son bail. Les états courants et plafonds conservés ne réarment aucun essai. La politique, les états et les réveils ont des tables additives (`research_need_collection_policies`, `research_need_collection_states`, `research_observation_wakes`).

Le réveil exige la preuve de toutes les demandes. Pour les trois endpoints actuellement raccordés, seule la couverture de pagination est prouvée ; rétention, inventaire et complétude économique restent distincts. [Documentation officielle Info, vérifiée le 8 octobre](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) : reprise au dernier timestamp ; userFillsByTime limité aux 10 000 derniers fills, 2 000 au plus par réponse. Aucun relâchement de ces limites.

Le paquet population exporte les pages promises après nouvelle vérification des périodes, identités, bornes et disponibilités. L'empreinte du réveil modifie l'entrée de recherche ; un nouveau scellement reste soumis au plafond commun, à l'intervalle minimal et à la déduplication. Un réveil ne promeut jamais une stratégie. Le paquet est refusé s'il dépasse le budget plutôt que tronqué silencieusement. Ce raccordement de réanalyse porte sur le paquet population ; une réanalyse spécifique paper enrichie de données externes demeure à vérifier séparément.

### Preuves

- Sept tests dédiés : totalité des contrats avant réveil, idempotence, pagination inclusive/reprise et curseur ordinaire inchangé, erreur consommant le budget, réserve avant accès raw/appel, reprise de bail avec essais conservés, preuve modifiant le paquet et un seul nouveau scellement sous budget existant, cutoff antérieur et nouvelle réserve refusant l'export avant payload.
- Suite complète fraîche : **423 tests OK en 43,039 s**. Aucun modèle/fournisseur réel dans ces tests.
- Service réel : premier lancement échoué sur la contention SQLite de l'allocation existante ; cycle suivant réussi (`Result=success`, `ExecMainStatus=0`), avec `observation_acquisitions` dans le rapport et zéro acquisition/réveil pour ce compte. Collecteur principal actif. La cause générale SQLite reste ouverte.
- Préflight recherche réel : zéro scellement, appel ou plan nouveau ; huit jobs population, zéro job paper, zéro réveil et zéro état d'acquisition. Les sept contrats legacy restent `structured_request_required`, sans interprétation implicite ni dépense pour les reformuler.

Retour arrière service : retirer seulement `--needs-policy /home/Untergame/tamtam_again/config/research-need-collection-policy.json`, puis daemon-reload ; sauvegarde `/tmp/tamtam-again-population.before-research-needs.service`. Conserver tables, essais, preuves et curseurs scoped. Les curseurs ordinaires et les réserves pilotes sont inchangés par cette extension. R4 reste partiel : besoins legacy à structurer sous autorisation de recherche, sources/proofs supplémentaires non prises en charge et parcours enrichi paper à vérifier. Ne pas confondre capacités synthétiques et observations prospectives réelles.


## Contrôle de complétude lors de l’export des réveils

L’export revérifie l’ensemble exact des contrats : aucun contrat manquant,
dupliqué ou supplémentaire n’est admis, même avec une empreinte recalculée.
Les indicateurs interdisant promotion et affirmation de complétude économique
sont également exigés. Ce contrôle précède la lecture des pages archivées.
Régression synthétique : preuves vides, partielles et dupliquées refusées sans
lecture de payload. Les huit tests ciblés et la suite complète (424 tests, 43,612 s) passent. Le raccordement de la
réanalyse paper enrichie reste à réaliser ; aucun budget IA réel n’est réarmé.
Retour arrière : revert du commit de ce contrôle, sans migration ni modification
de service. La collecte demeure active.


## Réanalyse paper sur observations acquises

Le scheduler paper consomme un wake de sa propre origine pour créer un job enfant
immuable. Il conserve le diagnostic, le paquet, le résultat, la route, les
positions et les performances précédentes. Une seule reprise est admise par
parent ; chaque enfant compte dans le même plafond global population + paper.
Une chaîne demande des observations nouvelles, avec filiation acyclique,
intervalle minimal existant et limite technique de 64 ancêtres ; ce plafond
technique ne constitue pas une allocation IA. Le pilote réel reste à 8 essais,
déjà consommés.

Le paquet enfant reconstitue et vérifie chaque paquet parent à son heure de
scellement, réautorise les périodes avant lecture, puis reçoit les pages
archivées prouvant exactement ses contrats. La mémoire conserve l’union des
périodes et les plans futurs conservent les parents recherche/session/version.
Les wakes paper ne rouvrent pas les paquets population. Une réserve nouvelle,
un parent modifié, une preuve d’une autre origine ou un budget épuisé bloquent
la reprise. La preuve de pagination ne certifie toujours pas la rentabilité ni
la complétude économique.

Migration : ajout nullable parent_request_id ; remplacement transactionnel de
l’unicité globale du diagnostic par deux index partiels (un initial/diagnostic,
un enfant/parent). Toutes les colonnes, lignes, index explicites et triggers
existants sont conservés. Une référence FK inconnue bloque la migration avant
suppression de table. Tests legacy : conservation des valeurs, idempotence,
unicité initiale et refus d’une FK avec conservation des lignes.

Recette reproductible supplémentaire :

```sh
PYTHONPATH=src .venv/bin/python scripts/adaptation-recipe.py \
  --output /tmp/tamtam-paper-observation-followup --observation-followup
```

Base temporaire uniquement : comparaison → finale → paper → limite de risque →
diagnostic → demande de funding historique → acquisition via bail population →
nouvelle connexion → réanalyse → nouveau plan prospectif. Six rôles simulés,
un job population, deux jobs paper, deux plans, une session paper préservée.
Zéro appel fournisseur ou modèle réel. Un second tick ne recrée pas le plan.
Les choix économiques des modèles et marchés sont des fixtures ; ceci prouve
le raccordement logiciel, pas un avantage réel ou le remplacement évalué de la
stratégie.

Contrôle réel prepare-only : migration appliquée, 8 jobs population conservés,
0 job paper, 0 session paper, 0 wake, 0 acquisition structurée et aucun nouvel
appel IA. Collecteur principal actif. Aucun service ni critère pilote modifié.
Les sept demandes legacy restent structured_request_required ; les limitations
des autres sources/preuves et de la qualification économique globale restent
ouvertes. R4 n’est pas déclaré entièrement terminé sur cette recette.

Retour arrière : suspendre uniquement le timer de recherche du projet pendant
le revert ; laisser les collecteurs actifs. Conserver la colonne, les index et
les jobs enfants, ne pas rétablir l’ancienne unicité du diagnostic. Si des
enfants sealed existent, conserver leur paquet et suspendre leur exécution
avec diagnostic avant de revenir à un runtime qui ne sait pas les vérifier.
Le contrôle réel présent n’en contient aucun. Ne pas restaurer une ancienne
base au détriment des données de collecte récentes.

Vérification finale de ce lot : suite complète **432 tests OK en 42,988 s** ;
recette CLI avec --observation-followup réussie, artefact local
/tmp/tamtam-paper-observation-followup/adaptation-recipe-result.json.


## Qualification sur une durée choisie avant résultat

population-qualification.py accepte --period-policy. Le sélecteur prend la
dernière valorisation exploitable, puis la borne exacte la plus proche du
début cible ; égalité → borne ancienne. Il ne regarde ni PnL ni complétude pour
déplacer la période. Conflits et observations futures sont exclus ; réception
et temps économique restent séparés. Aucune interpolation. Disponibilité réelle
des bornes conservée. Absence de borne ou fin trop ancienne → attente, sans
retour au dernier poll. Le mode adjacent précédent reste disponible sans policy.

Politique descriptive pilote : six heures, tolérance initiale quinze minutes,
âge maximal final une heure. La durée dépasse le dernier poll et les tolérances
accommodent la cadence REST. Paramètres justifiés et hachés ; aucun seuil de
maturité universel, aucune preuve statistique, aucun classement inter-comptes.

```sh
PYTHONPATH=src .venv/bin/python scripts/population-qualification.py \
  --db data/tamtam.sqlite3 --as-of-ms 1791480414394 \
  --period-policy config/account-qualification-period-policy.json \
  --output /tmp/tamtam-six-hour-qualification.json
```

Contrôle réel readonly : 69 comptes, 14 périodes sélectionnées, 31 fins trop
anciennes, 12 débuts absents, 12 sans deux valorisations. Zéro périmètre mesuré
sur cette durée ; aucun appel API/IA. Cas default : variation brute
+4447749,9999999998 USDC, net inconnu (trou de pagination ledger). Cas disabled :
variation brute +2064852,0979270041 USDC, net inconnu (ledger non classifié).
Ces variations de capital ne sont pas des gains. Unified/PM restent limités
par leur collatéral partagé. Aucun meilleur intervalle n’a été substitué.

Preuve r3-six-hour-public-scope-20261008.json : cutoff, politique, bornes,
diagnostics et SHA256 du rapport détaillé local. Les incertitudes sur la durée
longue empêchent d’extrapoler les mesures R3 de courts intervalles.

Vérification : **437 tests OK, 43,887 s**. Tests ciblés : égalité de distance,
absence de fallback, fraîcheur finale, paramètres invalides, conflits, cutoff,
disponibilité réelle et aucune comptabilité lancée sans la durée requise.
Retour arrière par revert ; aucune migration ou modification de service,
cohorte, cadence ou critère pilote. Collecteur principal vérifié actif.
Qualification globale et lacunes ledger restent ouvertes.


## Cadrage de la tranche fermée après e13ac29

Référence utilisateur : reviews/tamtam-b3c4412/CADRAGE-LUNA-e13ac29.md.
Priorité à la contention SQLite avant nouvelle extension. Lot de périodes livré
par d2b2e83/9a6a938 (437 tests, contrôle réel et attentes explicites). Matrice des
sept hypothèses et prochain budget réel à préparer après la mesure de collecte ;
aucune activation d’une tranche IA implicite.

Fenêtre baseline déclarée avant résultat : 30 minutes, pas d’une seconde,
manifest SQLITE-BASELINE-WINDOW-20261008.json. Sonde temporaire
/tmp/tamtam-lock-window.py, observations /tmp/tamtam-sqlite-baseline-20261008.jsonl.
Détenteurs des verrous du SHM, positions de verrou, wchan des threads,
taille WAL et nombre de JSON pending. Aucun payload ni secret lu. Aucun service
arrêté/rechargé, aucun timeout/retry ajouté. La fenêtre couvre les cadences
15 minutes de discovery/research et 60 secondes après fin de population.

Au lancement : collecteur PID447350 actif, WAL environ8,1Go, file pending vide.
Échecs OperationalError population observés à19:18 et19:27 local ; leur étape
exacte et la cause restent à établir. Le WAL seul n’est pas une cause démontrée.
Aucune stabilité revendiquée. Réveil à l’end_ms du manifest, puis contrôle du
handle vivant et analyse des samples/journaux sur exactement cette fenêtre.
En cas de timeout d’observation, ne pas relancer la sonde avant vérification.
La correction minimale et son observation après restent à réaliser.


### Résultat de la baseline SQLite annoncée

1800 samples, écart maximal1001ms. Population :10 complete,9 failed. Discovery
SQLITE_BUSY enregistré. File pending maximum1. WAL8691271872→8710714152 octets.
PID447350 tient le verrou WALwrite120 sur643 samples, séries continues jusqu’à
21 samples espacés d’une seconde (ce n’est pas une durée exacte de transaction).
Preuve compacte SQLITE-BASELINE-RESULT-20261008.json ; source temporaire hachée.

Cause concrète identifiée : collecteur démarré avant dd05fb0 du8oct13:46CEST,
encore chargé avec ancien SCHEMA CREATE UNIQUE INDEX uq_raw_observation.
Les nouveaux Store suppriment cet index ; l’ancien tente de le reconstruire
sur les réceptions distinctes autorisées par R1. Ses journaux répètent
IntegrityError: UNIQUE constraint failed: index 'uq_raw_observation', associés
à des erreurs de stockage/reconnexion WebSocket. Le vieux code ne disparaît
pas quand Git change. Reproduction locale sur base temporaire : deux réceptions
population identiques conservées, CREATE de l’ancien index échoue avec
SQLITE_CONSTRAINT_UNIQUE ; aucune suppression de données nécessaire.

Correction minimale suivante : remplacer proprement le processus collecteur
ancien par le code courant, avec préparation de reprise et retour arrière.
Ne pas restaurer l’index legacy : il détruirait la compatibilité R1. Pas de
nouveau timeout/retry comme substitut. L’attribution exhaustive des autres
échecs, reproduction concurrente et observation après restent à livrer.
Aucun redémarrage engagé dans ce checkpoint, collecteur encore actif. La tranche
n’est pas close et aucune stabilité n’est affirmée.


### Correction et observation après — checkpoint db8088c

Le 8 octobre à20:05:09 CEST, remplacement gracieux SIGINT du processus ancien
par le collecteur courant PID920368. Collecte active ; unité comparée à sa
sauvegarde, inchangée. Cadences, quotas et pilotes conservés. La reconnexion
reste une interruption réelle ; aucune absence de perte n’est présumée.

Test concurrent tests/test_stale_collector_schema.py : l’ancien CREATE INDEX
bloque l’écriture d’une seconde connexion (SQLITE_BUSY), puis échoue sur les
réceptions distinctes autorisées par R1. Après abandon, l’écriture reprend ;
le Store courant conserve les101 réceptions sans recréer l’index legacy.
Ce test prouve le mécanisme, pas la durée réelle ni tous les échecs observés.
Test ciblé1 OK ; **suite complète438 tests OK en48,621s**.

Fenêtre après préannoncée : SQLITE-AFTER-WINDOW-20261008.json,30min à1sample/s.
Réveil exact : **8octobre2026 à20:35:35,143 CEST**. Sonde session36970 ; source
/tmp/tamtam-sqlite-after-20261008.jsonl. Résultats non lus avant échéance.
À la fin : vérifier la terminaison, comparer verrous, tâches réussies/échouées,
retards et pending sur cette fenêtre, dont les chevauchements des trois jobs.
Stabilité non déclarée ; matrice des sept hypothèses et bilan décisionnel final
restent à livrer ensuite. Aucun nouveau budget IA activé.

Retour arrière : revert des tests/docs sans modification de données ; unité
non modifiée. Ne pas restaurer l’ancien index ou le processus pré-R1 sur cette
base. Toute reprise doit conserver la compatibilité avec les réceptions R1.


### Résultat après correction — fenêtre préannoncée terminée

Sonde session36970 terminée exit0 à l’échéance.1800 samples, gap maximal1001ms.
Population :13 complete,0 failed observé, contre10/9 sur baseline.
Deux invocations discovery terminées (~45,37s chacune), deux vérifications
research terminées (~0,06s chacune, budget épuisé/idempotence, aucun nouvel IA).
Aucune erreur database locked/SQLITE_BUSY/IntegrityError/storage_error dans les
journaux des quatre unités sur la fenêtre exacte. Pending0 au début/fin/pic ;
aucune reprise pending n’a donc été exercée dans cette fenêtre après.

Verrou write120 du collecteur courant :181 samples, série maximale2, contre
643 samples et série21 avant. Échantillonnage1s, pas durée de transaction exacte.
WAL8712341552 octets aux deux bornes : taille physique seule ne mesure pas
l’activité ni une absence d’écriture, les pages WAL peuvent être réutilisées.
Durées population42,06–134,29s ; intervalle après fin voisin60s, les tâches
longues décalent naturellement le prochain départ (timer after-completion).
Discovery et population se chevauchent sur les deux cycles ; research est
présent deux fois mais aucun triple chevauchement simultané n’est établi.

Preuve : SQLITE-AFTER-RESULT-20261008.json avec horodatages des départs/fins,
durées et hash de la source temporaire. Correction du processus ancien
confirmée sur cette fenêtre ; stabilité durable et charge de nouvelle inférence
non démontrées. Collecte conservée active. Aucun critère, budget ou réserve
modifié. Prochaine action : matrice documentaire des sept hypothèses et plan
réel proposé sans activation, puis checkpoint décisionnel de la tranche.


## Checkpoint décisionnel de la tranche CADRAGE-LUNA-e13ac29

| Livrable | État et preuve | Limites / prochaine décision |
| --- | --- | --- |
| Cause SQLite minimale | Ancien processus pré-R1 reconstruisait index supprimé ; reproduction concurrente, reload gracieux,438 tests ; f52d5dd/db8088c/032071a | Pas de nouvelle couche retry/timeout ; interruption de reconnexion conservée |
| Observation avant/après | d4c2056 :1800 samples chaque fenêtre ; population10/9→13/0, discovery2 terminés après, pending0 ; aucun storage_error après |30min seulement, pas triple chevauchement ni nouvelle inférence ; reprise pending pas réexercée après |
| Qualification de durée | d2b2e83/9a6a938 :6h fixées avant lecture,69admissibles,14périodes,31fins anciennes,12débuts absents,12sans deux bornes |0périmètre mesuré sur6h ; trous ledger/non-classification et collateral partagé ; qualification économique globale non accomplie |
| Tri des sept dossiers |8c38983/6770ba9 : source immuable hachée, sept questions minimales, données/capacités/privé/coûts/décisions séparés | Questions réduites proposées comme nouveaux enfants, aucune modification des anciens résultats |
| Prochaine expérience | D1/HYPE et D3/POL : structure d’ordres partiels,4requêtes logiques max,24tentatives max avec retries existants,30min max,0appel IA | Proposition non activée ; protection et archive à vérifier avant lecture, réutiliser rapport D1 si pertinent |
| Qualification→allocation | Écart documenté et proposition deepen par question comptable résoluble, rotation/exploration/témoins conservés | Aucune nouvelle politique générale implémentée, pas classement par capital brut |

Tests438 OK48,621s exécutés avant les seules additions documentaires suivantes.
Ce dernier lot documentaire n’a déclenché aucun test ou appel de modèle/API de
collecte ; navigation officielle seulement pour vérifier API/coûts réservés.
Zéro ordre réel, achat, VPS ou budget IA supplémentaire ; huit essais restent
consommés, sept hypothèses et un essai suspendu, aucun paper réel validé.
Collecteur PID920368 actif au contrôle final. Worktree propre avant ce CR.

La tranche fournit un checkpoint pour revue, pas une preuve que tous les quinze
objectifs initiaux sont terminés. La qualification économique exploitable sur
durée demeure incomplète ; prochaine décision après revue : résoudre les
lacunes comptables précises et/ou autoriser le sous-test descriptif proposé.
Les hypothèses passives complètes restent non identifiées ; ajouter tous leurs
adaptateurs sans discrimination préalable n’est pas autorisé par ce cadrage.
Retour arrière docs/tests par revert ; unité inchangée, données conservées ;
ne pas restaurer la base ou le processus/index pré-R1.

Revue : comparer manifests/results SQLite, test_stale_collector_schema.py,
rapport de durée r3-six-hour-public-scope-20261008.json et matrice
SEVEN-HYPOTHESES-TRIAGE-20261008.md. Sources temporaires des deux mesures
hachées dans les preuves ; données réservées non nécessaires à cette revue.
