# Boucle autonome de recherche — pilote borné

La preuve structurée jointe est [`RESEARCH-LOOP-PILOT-20261013.json`](RESEARCH-LOOP-PILOT-20261013.json); le registre SQLite garde les réponses fournisseur complètes et les métadonnées d’appel.

## Politique et admission

La politique exécutable est [`research-loop-pilot-v1.json`](../../config/research-loop-pilot-v1.json). Elle limite l’admission à la présélection G2 du 12 octobre et à `a880`, `67f7`, `be504`. La priorité de recherche et l’observabilité sont des champs distincts de la compatibilité avec le moteur paper. Le pilote est l’autorisation explicite, non renouvelable, d’effectuer une analyse descriptive IA malgré `economic_validation=false`; il ne modifie pas le gate commun, n’autorise ni stratégie, ni paper, ni ordre réel.

Le cutoff d’archive est `1791789394195` (`2026-10-12T07:16:34.195Z`). Le paquet a880 est adapté par `population-descriptive-pilot-adapter-v1` : il lit le rapport de scope disponible avant ce cutoff et le rapport déterministe HYPE versionné, sans lire les pages brutes, la mémoire, les réveils ou les fenêtres prospectives de v5. La protection de v5 demeure intacte; aucune clôture ni donnée de v5 n’a été recherchée.

La sélection a retenu `a880/HYPE` en premier : l’attribution déterministe disponible permet d’étudier les frais signés et le caractère crossed; l’absence d’ordres non exécutés et de priorité de file limite toutefois l’identification. `67f7/ETH` reste deuxième et `be504` troisième en raison de son périmètre multi-compte, de portefeuille et de devises. Aucun deuxième candidat n’a été activé après que la première analyse a identifié une tâche prospective précise.

Les plafonds du pilote sont trois tâches, six appels, 480 000 tokens d’entrée, 30 000 de sortie et 720 secondes. Par appel, le plafond de runtime reste 80 000 tokens d’entrée, 5 000 de sortie et 120 secondes; par tâche, deux appels, 160 000 / 10 000 tokens et 240 secondes. Le registre réserve ces maxima avant l’appel et conserve toute tentative engagée ou interrompue. Aucun USD fictif, retry, réarmement historique ou renouvellement n’est utilisé.

## Parcours réel

- Tâche : `b11881eee7db616f972569ef89ab0dcf6ef5b59e1f8a7d6d3db36262b20aea31`.
- Empreinte du paquet : `c2e92dc88d35641c80d85972928ad05e3ae6502d59127a4d69ee7c2d6d3c6f5a`.
- Rapport HYPE inclus : SHA-256 `88a04ac81e68b1cfaeaf4d5c87f4016c42e8afa158e8f6e5b01168e450896529`.
- La proposition IA réelle a consommé 65 770 tokens d’entrée, 2 344 de sortie et 84 648 ms; coût déclaré `included`, 0 USD. Sa réponse brute et son diagnostic `required_data_invalid` sont conservés.
- Le défaut était structurel et non ambigu : `hypothesis.required_data` était une liste d’objets `{index, observation, source, decision_use}` alors que le validateur attend une liste de textes. L’adaptateur `required-data-object-projection-v1` extrait uniquement `observation`, conserve les objets intacts en contexte et revalide hors ligne. La réponse fournisseur et le diagnostic initial restent inchangés et consultables.
- La critique IA prévue a consommé 67 258 tokens d’entrée, 546 de sortie et 22 082 ms; coût déclaré `included`, 0 USD. Aucun troisième appel ou nouvelle proposition n’a été tenté.

L’analyse distingue les observations de l’hypothèse : dans les épisodes sélectionnés, le flux de prix est proche de zéro tandis que les frais signés observés fournissent une contribution positive importante. Cela établit une contribution comptable descriptive dans cet échantillon incomplet, pas que les rétrocessions ont causé les décisions de cotation, ni un rendement du compte. Les comparaisons maker/non-crossed conditionnent sur les fills réalisés. Les pages incomplètes, les inventaires censurés, les ruptures de chaîne et la sélection sur exécution limitent l’attribution rétrospective.

La critique a décidé `needs_data`. Les liens décision→ordre, ordres non exécutés, horloges de réception, barèmes et règlements de frais, inventaire/ledger continu et protocole d’attribution ne figurent pas dans le paquet; ils ne peuvent pas être reconstruits à partir de ces épisodes. Elle précise que l’effet causal d’une rétrocession sur les choix de trading requiert une preuve de politique et, pour un effet d’incitation, une intervention ou variation exogène justifiée.

La résolution locale a vérifié le rapport de scope au cutoff et le rapport d’économie HYPE; aucun ne contient ces observations prospectives. L’enregistrement `population-pilot-local-resolution-v1` conclut `not_locally_resolvable`, sans demander de backfill historique ni attendre v5. Le routage persistant, version `prospective-execution-routing-v4`, crée `technical_task_required` : instrumenter les ordres, cotations, horloges, barèmes, règlements, inventaire et limites de capture, puis décider séparément si un adaptateur passif est nécessaire. Le moteur IOC actuel ne peut pas tester le mécanisme passif tel quel; cette incompatibilité n’est pas un rejet économique.

La reprise automatique est conditionnée à des observations prospectives autorisées et à un fingerprint d’entrée différent. Une présentation identique retourne la route existante sans appel. La tâche technique n’autorise ni paper, ni ordre, ni promotion.

## Consommation et services

Le registre dédié contient une tâche, deux appels réservés et rapporte 133 028 tokens d’entrée, 2 890 de sortie et 106 730 ms au total. Les réservations de pire cas correspondantes sont 160 000 / 10 000 tokens et 240 000 ms. Il reste au maximum deux tâches et quatre appels; ces plafonds ne sont pas transférés aux jobs ordinaires. Les huit essais historiques et les jobs du quota partagé restent inchangés.

Le timer existant `tamtam-again-population-research.timer` reste actif et enabled; son service charge maintenant cette politique. Au prochain réveil, l’entrée a880 inchangée est routée sans nouvel appel. Le timer paper, les collecteurs et les autres timers n’ont pas été modifiés. Aucun nouveau service ou timer n’a été créé.

## Vérification

Tests ciblés exécutés :

```sh
.venv/bin/python -m unittest tests.test_population_pilot tests.test_population_runtime tests.test_population_research -v
```

28 tests passent. Ils couvrent attente et données manquantes sans appel, réponse d’erreur consommée, interruption reprise sans nouvel appel, rejeu sans nouvel appel, épuisement des plafonds, adaptation structurelle et revalidation, critique simulée, route technique idempotente, séparation entre allowance pilote et quota partagé, migration du registre sans perte des tâches existantes, et nouveau paquet seulement après changement de fingerprint.

La commande reproductible d’un tick borné est :

```sh
.venv/bin/python scripts/population-research-tick.py --db data/tamtam.sqlite3 \
  --policy config/population-research-policy.json --max-jobs 1 \
  --experiment-policy config/experiment-allocation-policy.json \
  --reserve-policy config/reserve-cycle-policy.json \
  --paper-policy config/paper-research-policy.json \
  --pilot-policy config/research-loop-pilot-v1.json
```

Le tick n’infère pas à nouveau une entrée inchangée et ne crée pas une expérience paper.
