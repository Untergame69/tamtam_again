# Familles d'expériences bornées

Le profil schema v1 déclare hypothèse, justification, axes, catégories, preuves,
budget maximal et règle de sélection. Trois axes configurables : horizon, délai
et scale de taille. Le contrat sépare hypothèse, capacité système et risque
choisi. Les règles de marché restent dans les specs, jamais remplacées par un
axe exploratoire. Aucun horizon universel n'est introduit.

Le produit des axes est borné avant génération. Les paramètres de capital,
exposition, frais, risque et critères de promotion restent ceux du plan et de
la base. Chaque combinaison est enregistrée : gelée, spécification invalide,
ou mécanisme non supporté. Un échec de syntaxe ne disparaît pas du registre.
Une erreur inattendue annule toute la transaction de famille.

Les tables additives experiment_families, experiment_attempts et
experiment_selections conservent profiles/specs/diagnostics/décisions. Même entrée
renvoie la famille existante. Une famille nouvelle exige un plan sans variante
préexistante ; les pilotes sont donc préservés. Le budget du plan doit permettre
toutes les comparaisons et une finale. Les évaluations exploratoires éventuelles
consomment elles aussi son budget existant : prévoir la marge avant création.

## Sélection protégée

La v1 classe les variantes dont la comparaison a passé les critères selon PnL
net en scénario dégradé décroissant, puis variant_id pour départager. Toutes
les comparaisons des variantes gelées doivent être terminales. La sélection
est enregistrée avant ouverture de la finale réelle, sans lire ses résultats.
Si aucune comparaison passe, no_candidate est conservé et aucune finale promue.

Le moteur refuse la finale de toute variante non sélectionnée avant consommation
de la réserve. Le pipeline applique cette garde avant de lire les événements
finaux. Le pipeline tente automatiquement la sélection ; les comparaisons
incomplètes ou la fenêtre de sélection manquée produisent une attente explicite.
Une sélection manquée exige un nouveau plan prospectif. L'intervalle entre fin
de comparaison et début de finale doit laisser le temps au scheduler et aux
calculs mesurés ; ce délai n'est pas garanti par une simple étiquette.

## Délais et preuves

measurement_status distingue simulated et measured_reference. Une référence
mesurée doit déjà être disponible et comporter des preuves ; elle sert à
justifier un axe de latence. Les retards testés restent des scénarios : ils ne
deviennent pas des latences effectivement observées de N2. Le contrat ne prouve
pas à lui seul l'authenticité d'une référence externe ; la revue doit inspecter
son artefact. La calibration depuis télémétrie réelle reste à compléter.

## Commandes

```sh
PYTHONPATH=src .venv/bin/python scripts/experiment-family.py --db data/tamtam.sqlite3 \
  --plan-id NOUVEAU_PLAN --profile profil.json --base-spec strategie.json
PYTHONPATH=src .venv/bin/python scripts/experiment-family.py --db data/tamtam.sqlite3 \
  --select-family FAMILLE_ID
.venv/bin/python -m unittest discover -s tests -q
```

Ne pas utiliser ces exemples sur les plans pilotes existants. Le fichier
config/experiment-profile-example.json est exclusivement synthétique. La recette
experiment-recipe-20261007.json utilise une base temporaire, huit comparaisons et
une finale ; real_strategy_validated=false. Aucun plan réel ajouté ou promu.

147 tests passent : budget, conservation des échecs, idempotence, atomicité,
sélection sur comparaison et refus de finale d'un perdant. Retour arrière :
arrêter les workers recherche/pipeline avant annulation ciblée du commit,
conserver les nouvelles tables ; ne pas réactiver les familles enregistrées
sur un ancien moteur dépourvu de leur garde de finale. Le collecteur peut rester
actif. Les pilotes sans famille utilisent leur parcours antérieur.

Allocation prospective des candidats, calibration réelle, mémoire et extension
multi-instruments restent à livrer ; cette fonctionnalité ne termine pas le Goal.
