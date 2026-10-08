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
