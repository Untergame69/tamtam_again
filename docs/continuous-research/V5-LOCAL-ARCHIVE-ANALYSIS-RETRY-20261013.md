# Analyse locale v5 — conservation de réponse et tentative liée — 2026-10-13

Ce rapport complète sans les remplacer le [rectificatif paquet v2](V5-LOCAL-ARCHIVE-RESOLUTION-RECTIFICATIF-20261013.md) et le [bilan de la première activation](V5-LOCAL-ARCHIVE-ANALYSIS-ACTIVATION-20261013.md). L’ancien enfant suspendu et son fingerprint restent immuables.

## Récupération de la tentative antérieure

Enfant suspendu `9dda3827e578bd17992a67dafd9849596a4a9b3119c8f3756d3468bd665f804a`, paquet `466cd04d8d5a33f5593fbfba455d23492db648cc83cf9655e92441b1899777d9`. Les traces applicatives conservées contiennent seulement `error_type=ValueError`, `usage_json=[]`, `actual_cost_usd=NULL` et une autorisation terminée avec `calls_started=1`. Aucun `raw_proposal`, corps fournisseur, détail d’usage ou événement d’appel n’existe pour cet enfant. La table d’essais de scellement ne contient pas de ligne qui complète ces données. La réponse antérieure ne peut donc pas être récupérée et son étape exacte d’échec reste inconnue. On ne peut ni affirmer qu’aucune réponse n’était arrivée ni reconstituer son coût. L’enfant reste suspendu et n’a pas été réarmé.

## Corrections et vérifications

Le runtime persiste désormais un artefact par créneau d’appel avant de valider sa réponse. Il distingue `reserved_ms`, `engaged_ms`, `response_received_ms`, `response_validated_ms` (contrat d’usage) et `result_validated_ms` (contrat de réponse). Le corps fournisseur et ses métadonnées sont stockés séparément du diagnostic; aucune clé, configuration d’authentification ou prompt n’y est copiée. Un rejet de forme reste dans l’artefact avec `state=rejected` et n’est pas exposé comme proposition validée. Les erreurs de contrat inscrivent étape, code, champ, valeur observée et limite. Une interruption sans réponse conserve l’état `interrupted`; le job terminal n’est pas rejoué.

Une fonction déterministe a compacté les statistiques d’occasions, motifs, fraîcheur, cardinalité des cotations, champs absents, borne censurée et manifestes d’archives, en conservant le lien au paquet complet. Le nouveau paquet d’analyse `paper-local-evidence-analysis-v1` est lié à l’échec antérieur, sans modifier son paquet v2. Le prompt mesure 58 808 caractères sur la limite existante de 260 000; le paquet mesure 55 587 caractères sur 225 000. Ces mesures de caractères ne sont pas des estimations de tokens. Le runtime continue de vérifier séparément les plafonds de tokens réels retournés par le fournisseur.

Les tests ciblés couvrent usage inclus conforme, tokens absents, plafond par appel dépassé, JSON malformé et interruption; ils vérifient capture avant validation, diagnostic structuré, réouverture SQLite et absence de nouvel appel au rejeu. Un test de parcours couvre également la préparation compacte liée à l’échec, son activation simulée et sa décision persistée. Commande :

```sh
python -m unittest tests.test_paper_local_resolution tests.test_paper_followup tests.test_paper_research tests.test_paper_runtime tests.test_population_runtime -q
```

Résultat : **56 tests réussis**.

## Unique nouvelle tentative autorisée

Enfant lié à l’échec : `3104a45166193c26e56e33a55011b7de6c553807373f764dea5acb73d303533f`; résolution `d04ace0a3c712d019977831c86e0520aa906b24c63f4e8d8a764fcdda88416d4`; fingerprint du paquet compact `bcbabc788ff95ae9f61c29461401e34b096961203de61cd49d18e70c933f7e24`. Le paquet source complet et son empreinte `466cd04d8d5a33f5593fbfba455d23492db648cc83cf9655e92441b1899777d9` sont référencés sans modification.

Autorisation dédiée : abonnement, deux appels au maximum, 80 000 tokens d’entrée par appel et 160 000 cumulés, 5 000 tokens de sortie par appel et 10 000 cumulés, 120 s par appel et 240 s cumulées. Aucune réservation USD, aucun plafond partagé augmenté et aucun ancien enfant activé. Un seul appel a été engagé : modèle `gpt-6.1-sol`, 25 270 tokens d’entrée, 2 927 de sortie, 90 590 ms, `cost_status=included`, coût déclaré `0,00 USD`. Pas d’appel critique.

La réponse fournisseur de 12 040 caractères et ses métadonnées ont été conservées avant validation; SHA-256 de la réponse : `a4bc436f121726cf38f0da0ea0238c5a59b91cd67ddc5dce2f16d234b09329d5`. Le runtime a validé l’usage (25 270/80 000 tokens d’entrée; 2 927/5 000 de sortie; 90,59/120 secondes), mais rejeté la réponse au contrôle du résultat :

```json
{"stage":"result_validation","code":"hypothesis_fields_missing","field":"hypothesis","observed":[],"limit":["entry","evidence_refs","execution_constraints","exit","horizon_justification","markets","mechanism","rejection_criteria","required_data","risk","signal","sizing","type"]}
```

La réponse brute indiquait `decision=hypothesis` mais plaçait un résumé narratif sous `diagnostic.hypothesis`; elle n’incluait pas l’objet `hypothesis` complet requis à la racine. Aucun résultat validé n’a donc été promu, aucun critique n’a été lancé et aucun retry supplémentaire n’est autorisé par cette tranche. Le prompt est corrigé pour les tâches futures afin de distinguer un diagnostic `needs_data` d’une proposition exigeant cet objet, sans relancer le modèle.

L’enfant est terminal `suspended`; la décision persistante est routée `suspended` avec le diagnostic structuré et `automatic_retry=false`. Nouvelle connexion : le runtime retourne `unchanged_no_inference`, la route est identique au rejeu et `calls_started` reste à 1. L’enfant antérieur conserve son propre état suspendu; une seule ligne de retry le référence.

## Décision sur les preuves v5

Le fournisseur n’a produit aucune réponse **validée**; son artefact rejeté demeure consultable dans la base sous l’enfant ci-dessus et ne constitue pas une conclusion acceptée. Le paquet continue de démontrer descriptivement 521 occasions (492 manquées, 25 exécutées, 4 partielles), 434 classifications indisponible/périmée, et les discordances entre disponibilité d’archive et horodatage de décision. Ces étiquettes ne démontrent pas la causalité ni la rentabilité contrefactuelle. Les liens historiques exacts restent irrécupérables. L’endpoint v5 reste censuré avec `-0.61 HYPE` et une réduction en attente; aucune collecte ne clôturera cette session suspendue.

Aucune expérience paper, collecte additionnelle, clôture ou ordre réel n’a été lancé. La route exige une correction manuelle du contrat avant tout autre travail explicitement autorisé. Il n’y a pas de nouvelle demande de liens historiques perdus, ni d’attente de fermeture de v5.
