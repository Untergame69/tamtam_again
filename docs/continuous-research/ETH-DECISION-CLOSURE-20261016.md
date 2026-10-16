# Décision ETH consommée — 16 octobre 2026

La tâche `501c352c…aece` est **terminée avec rejet d’une interprétation définie** :
le contraste de markout à l’heure source ne démontre pas un avantage exploitable
via les pages REST utilisées. Ce rejet de preuve ne démontre pas l’absence de
tout avantage. La synthèse de cette intervention s’appuie sur les sorties
déterministes existantes ; les réponses IA initiales restent conservées.

- **Association descriptive à l’heure source** : médianes à 60 s de +2,484 bps
  pour les réductions taker et +1,275 pour les ouvertures/inversions réunies.
  Par ordre, les réductions sont à +2,480, les ouvertures à +2,105 et les
  inversions à +0,851 ; par bloc de cinq minutes : +2,274 / +1,849 / +0,411.
  Ces regroupements existants et la sensibilité de fraîcheur suffisent pour
  cette décision limitée. Aucun calcul supplémentaire ni recherche d’une
  méthode favorable n’a été lancé. Les 109 268 paires de fenêtres chevauchantes
  interdisent d’interpréter les fills comme des essais indépendants.
- **Suivi REST utilisé** : après réception, les médianes sont −0,414 et 0 bps.
  Le contraste événementiel ne se transporte pas à ce repère. Ni ces médianes
  ni les moyennes ne sont converties en rendement net.
- **Suivi live** : non mesuré par ces pages, donc ni validé ni rejeté. Signal
  disponible, latences, prix/profondeur exécutables et coûts propres au suiveur
  restent inconnus.
- **Autonomie** : aucune règle disponible avant notre décision n’est définie.
  Les fills ne révèlent pas les placements non exécutés, la file ou la politique
  du trader. Aucune hypothèse exécutable ni évaluation n’est proposée ici.

La décision structurée complète est dans
[ETH-RESOLUTION-ASSESSMENT-20261016.json](ETH-RESOLUTION-ASSESSMENT-20261016.json).
La résolution de référence reste `697a4b00…e65da1`, le bilan final
`60263914…274e9c` ; ils n’ont pas été remplacés par cette synthèse.

## Conséquence réelle

Le scheduler existant a été exécuté sur `data/tamtam.sqlite3`, sous son verrou,
avec `--prepare-only --max-jobs 1` et les politiques existantes. Aucun appel
fournisseur, collecte, paper, ordre ou quota supplémentaire n’a été engagé.

La route passe de `local_archive_analysis_complete` à `completed`. Les demandes
satisfaites sont désormais `resolved_data`, sans `required_data` actif. Le pilote
renvoie `terminal_route` pour ETH ; le rapport final et la ligne de route courante
sont `completed`. Les cinq lignes historiques de route, dont l’ancienne
`waiting_data`, restent consultables. `research_work_queue_current` sélectionne
une seule ligne courante ; le décompte actif ignore les anciennes versions.

L’import initial `e50b4e69…34828b` est intact. Une nouvelle mémoire
`d5b3a31d…675b33` relie question → preuves → conclusion → inconnues → action,
avec référence typée à la résolution vérifiée et périodes sources étendues au
cutoff de réception. Un paquet ultérieur **réellement préparé** sélectionne cette
mémoire et ses références `knowledge:` / `population_resolution:` ; les anciennes
questions résolues ne sont plus exportées comme questions ouvertes. Ce paquet
n’a pas été soumis à l’IA. Le rejeu conserve la même mémoire et ne scelle ni
n’exécute de nouvelle tâche. Un changement d’horodatage seul ne déclenche rien.

Les preuves SQL, identifiants complets, empreintes du paquet, commande et motifs
sont conservés dans
[ETH-RESOLUTION-CONSUMPTION-20261016.json](ETH-RESOLUTION-CONSUMPTION-20261016.json).

## Travail suivant et obstacle

**Aucun autre candidat réel n’a été analysé.** Le pilote v2 renvoie
`no_admissible_candidate` : a880 et be504 restent inchangés, ETH est terminale.
Les 32 évaluations de la voie générale refusent l’admission ; qualification
insuffisante et plafond partagé épuisé sont conservés séparément dans la preuve.
Le test d’une autre tâche qui avance vers `waiting_data` est **simulé** : il
prouve l’absence de blocage par ETH, pas le traitement réel d’un candidat.

**Proposition distincte, non appliquée** : une admission à une étude descriptive
bornée devrait exiger un prescreen documenté, une question précise sur un
périmètre compte/marché/période, des preuves autorisées et observables, une
empreinte sémantique nouvelle et une autorisation de ressources effectivement
applicable. Elle devrait avoir son propre état `descriptive_research_readiness`,
sans exiger ni attribuer `economic_validation=true`, et ne donner aucun accès au
paper ou au capital. Les réserves, plafonds et interdictions de rejeu restent
applicables. La règle manque dans la voie générale ; le pilote ne la fournit que
pour sa sélection et son cutoff explicites. Aucun assouplissement économique ou
réarmement n’a été effectué.

## Vérifications et commits

Code : `b244308`. Contrat générique des commits `fb2703e` / `7ed3949` réutilisé.

80 tests ciblés réussis : `test_population_resolution_memory`,
`test_population_runtime`, `test_research_memory`,
`test_eth_existing_window_resolution`, `test_research_work_queue`,
`test_population_local_archive_resolution`, `test_population_pilot`,
`test_population_packet`, `test_population_research`, `test_population_pipeline`.
Ils couvrent notamment révision après import, première importation après
résolution, cutoff ancien, preuves falsifiées, budget de sélection, horodatage
sans nouveau scellement, transitions, rejeu et progression indépendante.
`git diff --check` passe. Pas de nouvel appel runtime réel ; les appels des tests
sont simulés. Contexte courant consulté dans `TAMTAM_AGAIN-12` sans publication
de message externe.
