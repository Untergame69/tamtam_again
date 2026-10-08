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
