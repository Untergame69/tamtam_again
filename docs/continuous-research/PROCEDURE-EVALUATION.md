# Évaluation de décisions enregistrées

`procedure_evaluation.evaluate_procedure` rejoue une trace fournie sans choisir rétrospectivement une version gagnante. Les choix et références de connaissance précèdent chaque fenêtre ; le témoin fixe est déclaré avant le premier choix. Les coûts de tous les essais, y compris échoués, et les coûts de changement sont conservés. Attentes, candidats examinés et versions sélectionnées figurent au ledger. Résultats nets avec frais déjà inclus, provenance et budget de risque commun exigés ; coûts ou résultats absents rendent les agrégats inconnus.

Capacité actuelle : fenêtres sans positions ouvertes aux bornes ; comparaison règle fixe et cash sans coût de recherche. Une procédure témoin ayant sa propre recherche doit déclarer ses coûts dans une trace distincte. Fixtures uniquement : pas encore de trace automatiquement exportée des registres réels, ni de résultat réel d’adaptation. Les attestations des entrées exigent un adaptateur indépendant ; le reducer seul ne vérifie pas leurs preuves. Aucun résultat ou observation réservé consulté.

Recette : `.venv/bin/python -m unittest discover -s tests -p test_procedure_evaluation.py`. Quatre tests couvrent coût d’essai échoué, connaissance/témoin futur, attente/coût inconnu et positions non attribuables.
