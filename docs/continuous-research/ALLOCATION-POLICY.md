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

## Témoins appariés prospectifs

`cohort_matching.py` complète les groupes de collecte par un registre immuable
`matched_collection_cohorts`. La commande explicite `scripts/cohort-match.py`
exige une cohorte connue et une période future. L'horloge réelle fixe la date
d'inscription ; un replay du même contrat retrouve le snapshot initial, y
compris après la période, sans refaire les choix sur des résultats ultérieurs.
Les adresses protégées sont exclues avant lecture des rapports de périmètre.
Aucun PnL, résultat de stratégie ou archive réservée n'entre dans le matching.

La politique pilote `config/cohort-matching-policy.json` exige : mode de compte,
liste DEX inventoriée, observation spot, cadence REST, diagnostic de couverture
et strate d'activité identiques ; au moins un marché commun ; rapport disponible
depuis au plus 2 h ; fenêtre d'activité d'au moins 300 s ; rapport entre durées
au plus 2. Les strates observées utilisent les coupures 0,001 / 0,01 / 0,1
fill/s. Maximum huit paires disjointes. Ces paramètres sont des choix exploratoires
versionnés, pas des seuils statistiques universels. Aucun assouplissement implicite
n'intervient si les candidats ne correspondent pas.

Un algorithme de chemins augmentants cherche le maximum de paires compatibles,
puis applique le budget. Ordres et marché commun choisi sont déterministes par
graine. Un témoin ne sert qu'une fois. Les snapshots incluent les caractéristiques,
preuves et dates propres, exclusions et comptes non appariés. Cela permet une
comparaison ultérieure sur le marché déclaré ; cela ne rend pas équivalents les
capitaux, leviers, couvertures extérieures ou risques de portefeuille complet.
Une couverture inconnue appariée à une autre couverture inconnue demeure inconnue.
L'activité issue des pages publiques peut sous-estimer l'activité réelle.

### Premier contrôle réel du 8 octobre

`cohort-matching-control-20261008.json` et registre
`972b4ce1f912c8e4597aa1ed87b4503900ea303bd73c810ddad3f85e4e8792ce` :
2 paires exploration/témoin uniforme (ZEC, NEAR), 6 exclus, 17 sélectionnés
sans paire. Aucun témoin classement apparié. Période future fixe
[1791449721459, 1791467721459), soit cinq heures, début une heure après inscription.
Cette durée sert à un premier contrôle de collecte, pas à prouver une rentabilité.
Les changements de cohorte continuent normalement ; un retrait ou une interruption
peut rendre cette période inexploitable. Aucun nouveau slot/cadence/appel IA,
plan de stratégie, budget, service ou qualification économique créé.

La commande enregistre uniquement des témoins ; la comparaison de performance
nécessite encore des périodes comptables et risques comparables prouvés et/ou
un contrat de procédure avec références exécutables. Elle ne démarre pas de paper
et n'importe pas automatiquement ses paires dans un contrat de stratégie.
Aucune boucle de re-matching automatique ni recherche supplémentaire activée.

```sh
PYTHONPATH=src .venv/bin/python scripts/cohort-match.py --db data/tamtam.sqlite3 \
  --policy config/cohort-matching-policy.json --cohort-id COHORT_ID \
  --start-ms FUTURE_START --end-ms FUTURE_END --output /tmp/cohort-match.json
```

La commande requiert une base existante (SQLite mode=rw) et n'exécute pas les
migrations générales de Store. Migration additive : nouvelle table seulement,
aucune modification d'ancienne cohorte/observation. Retour arrière : retirer
la commande et le module ; conserver la table pour l'audit. Ni restauration
complète de base ni relance de collecte nécessaire.
