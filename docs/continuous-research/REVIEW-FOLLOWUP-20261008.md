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
