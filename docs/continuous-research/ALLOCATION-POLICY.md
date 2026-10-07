# Cohortes prospectives de collecte

La politique allocation-v1 répartit 32 slots REST : 12 exploration, 12
approfondissement, 4 témoins uniformes et 4 témoins du classement public day/PnL.
Ce sont des budgets pilotes choisis, pas des seuils de rentabilité. Une époque
dure 24 h UTC pour borner la rotation de ressources, sans déterminer la maturité
économique d'un compte. Deux époques consécutives au maximum en approfondissement
empêchent une bonne couverture de garantir une priorité permanente.

## Décisions et causalité

Le registre population_cohorts conserve le snapshot, sa politique, date, graine,
sources et décision pour chaque candidat connu à cette date. L'entrée de registre,
le rapport de périmètre disponible et le snapshot de classement sont référencés.
Un cohort déjà créé ne change pas avec les nouvelles observations de son époque.
Les insertions concurrentes relisent le snapshot gagnant avant application.

Chaque décision sépare performance, observabilité, reproductibilité, blocages
de collecte, blocages d'évaluation, inconnues et résultats défavorables. Dans
l'état réel actuel, performance reste inconnue et reproductibilité non prouvée.
Un inventaire disponible justifie une question comptable à approfondir, aucune
promotion de stratégie. Aucun score de PnL ou nombre de fills n'a été utilisé
pour classer cet approfondissement. Le classement public sert seulement de
témoin prescrit et ne constitue pas une comptabilité qualifiée.

Les groupes sont disjoints : classement d'abord, témoin uniforme sur les
candidats restants, approfondissement des scopes observés, puis exploration.
L'échantillonnage uniforme porte sur la population **découverte**, avec ses biais
de couverture ; il ne représente pas tous les utilisateurs de la plateforme.
Les groupes suivent la même politique REST et les mêmes dates de cohorte, mais
leur activité/cadence effective et leur historique disponible peuvent différer.
Une comparaison économique devra apparier/stratifier ces différences : le simple
label témoin ne prouve pas encore la comparabilité des résultats.

## Application et retraits

Le worker applique la cohorte à l'ordonnanceur REST. Les dix suivis directs et
les adresses réservées sont exclus. Le budget total d'adresses actives inclut
les jobs déjà running : ils conservent leur bail et terminent normalement ;
des admissions attendent si nécessaire. Aucun retrait ne supprime candidat,
observations, curseurs, essais ou rapports. Un compte peut être réadmis plus tard.

Un retrait peut créer une interruption de couverture ou dépasser la rétention.
Reprendre son ancien curseur n'est pas une preuve de continuité. Les pages et
diagnostics doivent rester unknown lorsque le rattrapage ne peut être démontré.
Le job conserve son cohort_id et groupe dans les nouveaux rapports pour l'audit
du processus de sélection.

## Preuve réelle et capacité

allocation-control-20261007.json : quatre budgets remplis, décisions de 970
adresses conservées, 32 comptes REST actifs et 20 retirés, dix directs préservés.
La mesure avant activation sur 30 minutes donne environ 847 poids réservés/min
sur budget local 900, sans HTTP 429. Cela mesure cette fenêtre, pas un budget
serveur facturé exact ni une capacité soutenable complète. La rotation introduit
du rattrapage même à nombre de slots constant ; il faut surveiller ses délais.

175 tests passent : groupes disjoints/déterministes, états distincts, priorité
non permanente, slots indisponibles, rotation/baux et conservation d'archive.
Aucune qualification économique ou nouvelle stratégie réelle activée.

```sh
PYTHONPATH=src .venv/bin/python scripts/population-tick.py --db data/tamtam.sqlite3 \
  --policy config/population-policy.json --enroll-only --output /tmp/allocation.json
.venv/bin/python -m unittest discover -s tests -q
```

Attention : enroll-only applique la politique, ce n'est pas un dry-run.
Rollback : arrêter timer/service population, retirer allocation de la politique
avant annulation ciblée du code, conserver tables/rapports. La cohorte active
peut alors rester fixe sous l'ancien ordonnanceur. Les comptes retirés ne sont
pas réactivés implicitement ; une restauration de membership doit être explicite
et rester dans le budget. Aucun besoin de restaurer la base entière.

La qualification économique, les cohortes d'analyse IA et la comparaison
prospective de la sélection restent à terminer. Cette politique livre
l'allocation de collecte et sa traçabilité, pas une sélection de comptes rentables.
