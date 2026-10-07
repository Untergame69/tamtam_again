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

## Coûts des registres de recherche

`procedure_costs.provider_cost_ledger` et `scripts/procedure-provider-costs.py`
exportent uniquement les métadonnées des deux registres IA, en lecture seule,
sans migrations, paquets ni résultats réservés. Réseau, fenêtre semi-ouverte
start/end et cutoff obligatoires ; adresse facultative. Tous les essais inscrits
pendant la fenêtre comptent, y compris rejetés et interrompus. Leur inscription
et la disponibilité du coût sont deux dates distinctes : une facture disponible
après la décision peut être comptabilisée au cutoff sans devenir une information
utilisable lors de cette décision. Les derniers états postérieurs au cutoff sont
masqués ; les états intermédiaires non journalisés ne sont pas reconstitués.

Une réservation n'est jamais un coût réalisé. État inconnu/en cours ou montant
manquant : total inconnu, somme des montants connus conservée séparément.
Les anciens jobs isolés suspendus peuvent contenir seulement le coût des appels
terminés avant une panne : leur montant est donc conservativement inconnu.
Les montants fournis par le runtime peuvent être estimés ou inclus dans un
abonnement, sans constituer une facture. Zéro fournisseur ne signifie ni zéro
token ni zéro calcul. Le périmètre exclut dépenses externes et infrastructure.

Commande : `PYTHONPATH=src python3 scripts/procedure-provider-costs.py --db
 data/tamtam.sqlite3 --network hyperliquid-mainnet --start-ms DEBUT --end-ms FIN
 --as-of-ms CUTOFF --output RAPPORT`. Une fenêtre vide ne prouve aucunement
l'absence de dépenses hors de ces registres. Aucune modification du runtime ou
des plans ; rollback code uniquement, conserver les historiques.

## Continuité du capital fournie par les observations

Le reducer accepte `capital_contract` explicite : initial_capital positif,
currency USDC, external_flows none, preuve et date disponible avant la première
décision. Chaque résultat doit fournir opening_capital/closing_capital, même
devise et absence de flux. La différence doit égaler le PnL net et l'ouverture
suivre la clôture précédente, pour l'adaptatif et sa référence séparément.
Les périodes sont contiguës ; attente cash sans intérêt/flux explicite.
Une réinitialisation de session ne passe pas silencieusement : capital initial
identique à l'ancien contrat ne signifie pas continuité après gains/pertes.
Bornes manquantes rendent l'agrégat inconnu. Les traces anciennes restent
compatibles mais signalent capital_continuity_status unverified.

paper_outcome expose les bornes du modèle : capital initial immuable plus PnL
cumulé aux instantanés exacts plats. Ce calcul n'est pas une valorisation réelle.
Le capital de trading et la richesse de procédure après dépenses externes de
recherche/changement restent séparés : aucun financement des sessions n'est
simulé par cette déduction. Les dépenses exprimées en USD sont ici comparées
nominalement à USDC, sans modélisation de dépeg ou conversion exécutée. Le
transfert réel de capital aux remplacements et les références contemporaines
restent à implémenter ; cette vérification ne les invente pas. Pas de rendement
composé ou drawdown prétendu à partir des seules bornes.
