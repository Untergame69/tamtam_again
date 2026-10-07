# Évaluation de décisions enregistrées

`procedure_evaluation.evaluate_procedure` rejoue une trace fournie sans choisir rétrospectivement une version gagnante. Les choix et références de connaissance précèdent chaque fenêtre ; le témoin fixe est déclaré avant le premier choix. Les coûts de tous les essais, y compris échoués, et les coûts de changement sont conservés. Attentes, candidats examinés et versions sélectionnées figurent au ledger. Résultats nets avec frais déjà inclus, provenance et budget de risque commun exigés ; coûts ou résultats absents rendent les agrégats inconnus.

Capacité actuelle : fenêtres sans positions ouvertes aux bornes ; comparaison règle fixe et cash sans coût de recherche. Une procédure témoin ayant sa propre recherche doit déclarer ses coûts dans une trace distincte. Le reducer est vérifié sur fixtures ; une trace metadata-only des registres réels existe, mais pas encore une évaluation complète de la politique avec références contemporaines. Aucun résultat réel d'adaptation établi. Les attestations des entrées exigent un adaptateur indépendant ; le reducer seul ne vérifie pas leurs preuves. Aucun résultat ou observation réservé consulté.

Recette : `.venv/bin/python -m unittest discover -s tests -p test_procedure_evaluation.py`. Quatre tests couvrent coût d’essai échoué, connaissance/témoin futur, attente/coût inconnu et positions non attribuables.

## Trace réelle de registres

`PYTHONPATH=src .venv/bin/python scripts/procedure-trace.py --db data/tamtam.sqlite3 --output /tmp/procedure-trace.json` exporte les créations et derniers états IA, débuts/fins de jobs population, diagnostics, gels de variantes et débuts de paper. Option --as-of-ms : les états mutables plus tardifs sont exclus, jamais rétrodatés. Cette trace ne lit aucun paquet IA, résultat d’évaluation ou observation brute. Elle fournit le journal réel préalable à l’évaluation ; les adaptateurs de sélection de politique et de résultats autorisés restent nécessaires avant de calculer sa performance.

## Adaptateur des résultats paper

`paper_outcome.period_outcome` lit uniquement les instantanés immuables d'une
session et les contrats figés de sa variante. Bornes exactes obligatoires,
disponibles au cutoff, plates et sans ordre pending. Aucune interpolation,
fusion de sessions ou reconstruction depuis leur état actuel. Des diagnostics
pendant la période ou des métriques comptables absentes rendent le résultat
inconnu. Le résultat est la différence des PnL nets cumulés du modèle ; frais
et funding déjà comptés ne sont pas déduits une seconde fois.

Le budget de risque comparé est un fingerprint du capital initial et du contrat
max_exposure. Il n'atteste pas à lui seul que les risques réalisés ou possibilités
d'exécution sont identiques. Les références fixes/témoins doivent posséder leurs
propres preuves contemporaines ; aucune référence historique n'est inventée.

Commande : `PYTHONPATH=src .venv/bin/python scripts/paper-period-outcome.py --db
CHEMIN --session-id SESSION --start-ms DEBUT --end-ms FIN --as-of-ms CUTOFF
--output RAPPORT`. Résultat `model_period_measured` ou `unknown`, provenance
synthétique explicitement conservée. Un outcome inconnu transmet une inconnue
au reducer de procédure. Aucun avantage économique réel ne découle de cet
adaptateur. La complétude des flux et coûts réellement exécutables, le capital
continu et les choix préenregistrés de toute la procédure restent à établir.

La trace inclut aussi les dates originales des cohortes, ordres publics,
connaissances, imports en mémoire, libérations de périodes et routages. Lecture
exclusive de colonnes d'identité/date : aucune synthèse, paquet ou résultat
réservé n'est consulté pour produire ces événements. Les preuves restent
référencées, sans rétrodatation ni qualification économique. Ces événements
complètent la chronologie, mais ne remplacent pas les adaptateurs de sélection
et de performance de toute la procédure.

## Attentes, preuves distinctes et fins d'évaluations

La déduplication pipeline_decisions inclut désormais les preuves. Deux variantes
recevant le même diagnostic/réveil restent deux décisions conservées ; répéter
le même diagnostic et la même preuve n'ajoute pas de ligne. Les décisions
anciennes dont les preuves ont été fusionnées ne sont pas reconstruites après
coup : la limite du journal historique doit rester explicite.

Les nouvelles évaluations enregistrent evaluation_terminal_events avec leur
statut terminal et date après calcul, dans la même transaction que le résultat.
Une erreur de calcul est aussi journalisée ; la période finale reste consommée.
Les relectures ne réécrivent ni date ni statut. Aucun backfill à partir de
created_at n'est effectué : ce champ correspond au début de l'évaluation et
ne prouve pas quand un résultat terminal était disponible.

La trace metadata-only référence décisions et fins d'évaluation à leur date
propre. Elle ne lit ni diagnostic, preuves JSON, statut terminal ni métriques :
les résultats réservés ne deviennent pas une entrée de développement via cet
export. L'évaluation autorisée de la procédure devra résoudre ces références
avec ses contrôles temporels et de réserve. Le journal seul ne prouve toujours
pas la rentabilité de la sélection/adaptation.

Rollback ciblé code ; conserver pipeline_decisions et evaluation_terminal_events.
L'ajout du journal est compatible avec les anciens plans et ne les réécrit pas.
