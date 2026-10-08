# Compte rendu pour revue indépendante — 8 octobre 2026

**État : livraison partielle, Goal actif et incomplet.** Ce rapport rassemble
les preuves pour une revue ; il ne constitue ni une approbation indépendante,
ni une certification économique. Code examiné : **1f7f483**. Référence intégrale :
OBJECTIVE.md et pièce jointe utilisateur conservée. Aucun ordre réel, signature,
wallet, abonnement, VPS externe ou reprise POLY.

## 1. État initial et état constaté

| Élément | Initial, 7 octobre | Contrôle du 8 octobre |
| --- | --- | --- |
| Code | fdb1264 | 1f7f483, 86 commits après baseline |
| Candidats découverts | 681 dont dix suivis directs | 3294 candidats enregistrés ; ne signifie pas 3294 qualifiés |
| Inventaire population indépendant | Absent | 69 adresses avec au moins un rapport de périmètre |
| Ordonnanceur REST | Couplage pratique aux comptes suivis | 32 slots scheduled, 37 retirés avec historique conservé |
| Suivis WS utilisateurs | Dix | Dix conservés au contrôle de capacité ; aucune extension revendiquée |
| Découverte | Classement public | Classement + participants publics, provenance multiple conservée |
| Plans / variantes pilotes | Huit / trois | Huit / trois ; onze comparaisons de contrats vraies |
| Session paper | Zéro | Zéro |
| Recherche IA population | Absente | Huit essais, sept hypothèses, une suspension |
| Routage réel des hypothèses | Absent | Sept needs_data, une suspended |
| Qualification économique | Non prouvée | Aucune qualification démontrée |
| Fichier SQLite principal | 7 194 603 520 octets | 12 128 079 872 octets, WAL 63 518 072 au relevé |

Sources : baseline-20261007.json (initial), review-state-20261008.json et
review-registry-20261008.json (actuel). Les timestamps propres restent dans les
preuves. Croissance du fichier = allocation physique, pas volume de payloads
uniques. Les dix abonnements directs ne donnent pas la même latence aux comptes
interrogés en REST. Le collecteur a été vérifié active/running ; les timers
population/discovery/recherche/paper/resources sont présents. Une unité oneshot
inactive hors tick n'indique pas un timer arrêté. Cela ne prouve pas un SLA.

## 2. Audit des quinze exigences

« Partielle » indique un travail d'implémentation ou une preuve manquante.
Une attente de données n'est utilisée que lorsqu'une capacité existe déjà et
qu'une observation précise manque. Les tests synthétiques ne ferment pas une
exigence de résultat réel.

| Nº | État | Capacité et preuve | Reste à faire ou vérifier |
| --- | --- | --- | --- |
| 1 Diagnostic/plan | Livrable présent | EXECUTION-PLAN.md, baseline, état actuel, contrats pilotes comparés | Actualiser ce relevé après toute nouvelle modification substantielle |
| 2 Capacité | Partielle | Télémétrie REST/WS, capacity-sustained-20261008.json, nouveau timer resources | Charge prolongée machine/enfants/IA, récupération incident et calcul complet par cadence |
| 3 Population découplée | Capacité livrée, qualification partielle | population.py, 69 inventaires, 32 slots REST séparés des dix directs | Ne pas assimiler inventaire à performance qualifiée ; continuité après retraits à établir |
| 4 Découverte | Deux voies fonctionnelles, comparaison partielle | discovery.py/runtime, fenêtres/provenances/échantillonnage | Valeur économique comparée des voies sur témoins réellement qualifiés |
| 5 Compte entier | Inventaire livré, valorisation partielle | Mode/DEX/spot/relations/positions ; acquisition explicitement liée | Valoriser collatéral partagé/dettes/spot/vaults sans fusion incertaine des comptes |
| 6 Comptabilité | Partielle | Reducers accounting/consolidation/events/coverage, adapter réel, contrôles contrastés | Source/modèle de capital cohérent, FX, dette/intérêts/spot, historique complet, réconciliation réelle |
| 7 Préétude | Descripteurs livrés, risque partiel | behavior.py, MARKET-MECHANISMS.md, contrôle réel daté | Trajectoire de risque consolidée ; mécanismes dont les données manquent |
| 8 Allocation/témoins | Allocation et matching disponibles, comparaison partielle | Cohortes datées/disjointes, plafond de deepening, deux paires prospectives réelles | Aucun témoin classement apparié ; capital/risque global/coverage économique non prouvés |
| 9 Profils | Contrat et essais bornés disponibles, mesures partielles | experiments.py, compilation, profils horizon/délai/taille, critères gelés | Preuve réelle de délai d'exécution mesuré ; sensibilité de stratégies réelles à établir |
| 10 Multi-instruments | Extension minimale expérimentale démontrée | portfolio_engine.py et recette comptable de référence | Adaptateur réel N1/N2, lots/tier/liquidation/FX/synchronisation non intégrés |
| 11 Adaptation | Partielle | Population→hypothèse/mémoire/routage, diagnostics paper atomiques, recette jusqu'au paper | Relier diagnostic à proposition IA avec nouveau budget borné ; détection comportement/performance et retour arrière autonome |
| 12 Procédure adaptative | Infrastructure/recettes présentes, preuve réelle en attente | Choix prospectifs, sessions préliées, capital transmis, références continues, coûts/échecs/waits | Procédure autonome réelle avec comparateurs qualifiés ; pas uniquement choix/suspensions scriptés |
| 13 Mémoire | Capacité livrée, revue indépendante requise | Provenance/périodes héritées, réserves multi-marchés, libération versionnée | Vérité sémantique des synthèses non certifiée ; aucun holdout réel libéré pour terminer |
| 14 Montée capacité | Décision préparée, dimensionnement partiel | CAPACITY-DECISION.md, REST prolongé, options et coûts datés | Charge totale soutenable, devis/garanties historiques et reprise avant dépense |
| 15 Vérifications/CR | Livraison partielle | Tests, recettes, contrôles réels, ce rapport, Git/YouTrack | Résoudre écarts ci-dessus, nouvelle vérification puis revue indépendante finale |

## 3. Comptabilité : ce qui est réellement établi

- Réconciliation de période pure : variation d'equity moins flux externes,
  composants réalisé/latent/frais/funding/autres revenus, diagnostic de divergence.
  Rendement et drawdown restent inconnus sans preuves nécessaires.
- Catalogues disponibles causalement : devise et token collatéral identifiés,
  sans confondre identification et prix FX ou parité stablecoin garantie.
- Périmètres de capital indépendants uniquement : pools partagés ne sont pas
  additionnés par DEX. Le reducer de consolidation reste distinct de l'adaptateur
  réel ; sa réussite sur fixture ne certifie pas la valorisation d'un compte réel.
- Modes unifiedAccount/portfolioMargin : capital par DEX non utilisable comme
  equity globale. Ratio de maintenance unified sous preuves strictes, distinct
  du rendement/PnL et non appliqué au mode portfolioMargin.
- Vingt snapshots spot dans le contrôle de cinq comptes ne contenaient aucun
  timestamp économique. Acquisition locale n'est pas un timestamp de marché.
- Nouveaux lots liés explicitement par attempt_id et inventaire DEX référencé ;
  appels séquentiels, aucun lot ancien reconstruit par proximité. Leur liaison
  ne prouve pas absence de changement de mode ou simultanéité économique.
- Portfolio : 40 fenêtres sur cinq comptes non protégés, aucune paire de bornes
  exactes pour la période demandée. Courbes rapportées conservées séparément,
  sans interpolation, fusion de fenêtres ou conversion en PnL réconcilié.

**Action manquante concrète :** implémenter une valorisation account-wide dont
les conventions de spot/marge/dette/intérêts/FX et le périmètre sont vérifiés,
avec alignement ou incertitude temporelle justifiée, puis raccorder aux périodes
et flux dont la couverture est démontrable. Plus de fills ne fournit pas à lui
seul le timestamp économique spot ni une preuve d'absence de dette.

Preuves : ACCOUNTING-CONTRACT.md, unified-risk-real-control,
account-acquisition-control et portfolio-evidence-control du 8 octobre.
Sources officielles vérifiées : [modes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes),
[portfolio margin](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-margin),
[courbes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs).

## 4. Capacité et critères retenus

| Mesure | Avant / premiers relevés | Mesure ultérieure | Interprétation |
| --- | --- | --- | --- |
| REST réservé | Environ 847–851/min sur courte fenêtre | 23,002 h, 22 heures complètes, moyenne 850,57, p95 empirique 858,05, max 858,65 | Budget local 900 ; réserve choisie 20 % → opérationnel 720 ; toutes les heures au-dessus |
| Population | Pas de suivi indépendant | 688 passages complets et un running dans cette fenêtre ; max job 130,249 s | Plusieurs cycles horaires observés, pas une preuve de reprise/coverage complète |
| WS | Dix users, un flux | 2739 fenêtres, pic file 2595 messages, max flush 12,392 s | Maxima à diagnostiquer ; aucune promesse de latence de trading |
| CPU initial | 0,072 cœur sur 59,34 s du processus principal | Nouveau suivi par cgroup/invocation chaque ~minute | Les nouveaux samples initiaux ne donnent pas encore un dimensionnement prolongé |
| Mémoire | Mesures anciennes non directement comparables | Premier cgroup collecteur : ~555 Mo anon / ~4,87 Go cache fichier | MemoryCurrent n'est pas RSS ; descendants/cache inclus |
| Stockage | 7,19 Go fichier au baseline | 12,13 Go au contrôle actuel | Croissance constatée ; pas projection mensuelle ni estimation de données uniques |

Paramètres choisis, versionnés : 32 slots (12 exploration/12 approfondissement/
4 uniformes/4 classement), époque 24 h UTC, deux époques consécutives maximum
en deepening. Matching : rapport <=2 h, activité >=300 s, ratio fenêtres <=2,
strates 0,001/0,01/0,1 fill/s, huit paires maximum, mode/DEX/spot/cadence/couverture
identiques et marché commun. Deux paires disponibles ZEC/NEAR ; absence de paire
non corrigée par assouplissement après observation.

Ces valeurs bornent un pilote, pas sa validité statistique. Les profils
expérimentaux séparent règles marché, hypothèse, budget risque et capacités
mesurées. Les critères figés des anciens plans sont inchangés. Le futur délai
mesuré exige une preuve scellée execution_delay_reference ; un délai simulé ne
change pas de catégorie parce qu'il paraît réaliste.

**Décision :** pas d'expansion chiffrée justifiée dans la marge de reprise choisie.
REST moins fréquent/flux mutualisés à étudier avant achat. Deux IP : scénario de
1800 poids locaux/min agrégés, pas capacité démontrée en comptes. Fournisseur :
Quicknode tarif consulté le 7 octobre 49 USD/mois ou 34 annualisé, charge/dépassements
non chiffrés. VPS 10–20 EUR/mois/unité et nœud 150–400 EUR/mois sont hypothèses de
planification, pas devis. Aucun achat/déploiement externe.

## 5. Adaptation, réserves et coûts

Le parcours population synthétique utilise deux réponses IA simulées, importe
une hypothèse revue en mémoire, route/compile sous contrat et évalue une stratégie
figée en comparaison/finale avant paper fixture. Il ne valide aucune rentabilité
réelle. En production, les huit demandes population sont consommées ; sept
needs_data et une suspended, aucun budget automatiquement augmenté.

La suspension paper réel garde atomiquement état, diagnostics, snapshot et
demande de travail. Perte+collecte défaillante → correction de collecte, pas
attribution automatique à un avantage disparu. Un diagnostic autorise zéro
appel IA, zéro reprise et zéro promotion. Recovery borné et position ancienne
conservée. Nouvelle proposition autonome après ce diagnostic manque encore.

La recette comparative couvre attente, essai raté et coût, référence fixe
continue, cash, remplacement à borne exacte avec capital plat transmis et
ancienne version conservée, réouverture SQLite/replay. Choix et suspension sont
scriptés. Les outcomes réels utilisent seulement sessions préliées/snapshots
paper ; pas sélection rétrospective de la meilleure session. Une période
consommée/libérée garde son résultat original et ne redevient pas vierge.

Budget première tranche IA : huit requêtes, jusqu'à deux rôles, réservation
1 USD/appel, soit enveloppe théorique 16 USD, timeout 120 s/rôle, max 5000 tokens
sortie. Réservations et montant inclus/estimé par le runtime ne sont pas des
factures. Essais partiels/anciens jobs suspendus peuvent avoir coût inconnu :
**coût total réel non établi**, pas présenté comme zéro. Infrastructure, temps
CPU/token hors registre et abonnement déjà détenu ne sont pas réconciliés.
Fixtures de procédure : coûts connus par conception (recherche 2, changement 1),
aucune dépense réelle. Aucun abonnement ou dépense fournisseur nouveau engagé.

## 6. Fichiers, migrations, services et commits

`review-registry-20261008.json` contient la liste Git des **226 fichiers modifiés**
et des **86 commits** entre fdb1264 et 1f7f483. Ce rapport et ses preuves seront
un commit documentaire supplémentaire. Cette liste est la référence détaillée,
plutôt qu'une liste reconstruite depuis la conversation.

Principaux ensembles : population/discovery/telemetry/capacity/resources ;
accounting/account_events/account_coverage/account_periods/account_adapter/
account_consolidation/unified_risk/account_acquisitions/portfolio_evidence ;
behavior/market_rules/collateral ; allocation/cohort_matching ; experiments/
portfolio_engine/harness_extensions ; population_packet/research/runtime/
compilation/planning/experiments/memory/routing ; paper_monitor/adaptation/
evidence/handover/outcome ; procedure_registry/references/report/costs/trace ;
research_memory. Configurations, scripts, tests et docs associés dans la liste Git.

Tables additives principales : population_accounts/attempts/state_corrections,
account_scope_reports, population_history_cursors, discovery_windows/provenance,
collateral_catalogs, population_cohorts, matched_collection_cohorts,
adaptation_events, experiment_families/attempts/selections,
population_research_jobs/hypothesis_routes/research_memory/order_reports/
plan_drafts/experiment_links, research_knowledge/period_releases,
paper_snapshots/session_policy/retirements/handovers/suspensions/adaptation_requests/
reference_sessions, procedure_contracts/choices/session_bindings,
evaluation_terminal_events. Télémétrie séparée : quota_clock,
collection_attempts, collector_measurements. Certaines tables sont créées à la
première utilisation ; la présence d'une table ne prouve pas un workflow actif.
Aucun effacement/restauration générale de la base accumulée.

Unités projet ajoutées : population, discovery, population-research, resources
(services/timers). Collectors/research/paper existants sont maintenus ; leurs
fichiers versionnés et la différence baseline dans Git donnent les changements
exacts. Aucun service partagé/infra/POLY modifié dans ce périmètre. Ressources
ajouté et activé au dernier changement ; aucun redémarrage pilote alors requis.

Derniers commits substantiels :

| Commit | Changement |
| --- | --- |
| 3ff868b | Capacité prolongée par buckets complets |
| cb1d604 | Témoins prospectifs appariés immuables |
| fcbb9a2 | Diagnostic paper atomique/récupérable |
| 8c3a867 | Acquisition liée au périmètre DEX |
| 5c70617 | Courbes portfolio distinctes de comptabilité |
| 1f7f483 | Prélèvements périodiques cgroup/stockage |
| dc91131 / a3067cc / 7c736ab | Ratio unified, diagnostics réels et fenêtres locales |
| 872d8c8 / 07db0b6 | Recettes de comparaison et transmission de capital |
| fd101eb / 99b00d3 | Références continues et outcomes/coûts de procédure |
| cece289 / c9b7d6a | Cash transmis et continuité de capital vérifiée |

## 7. Tests et revue reproductible

Dernière suite : **332 tests OK, 29,482 s** sur le code 1f7f483 ; les tests ne
prouvent pas les exigences réelles absentes. Couverture : comptabilité/flux/
FX/modes/pools, causalité, mémoire/réserves/héritage, pagination/retries/quotas,
matching, multicompte/multi-instruments de référence, promotion/risk suspension/
rollback injecté/changement version/capital/restart/coûts inconnus.

Recettes réexécutées sur code livré, bases temporaires exclusivement :
review-population-recipe-20261008.json et review-procedure-recipe-20261008.json.
Zéro appel IA/fournisseur réel, original_database_touched=false. La recette
population simule l'isolation ; elle ne remplace pas son contrôle réel séparé.
Contrôles sur données réelles listés plus haut n'ont pas qualifié une stratégie.
La revue indépendante n'a pas encore eu lieu.

```sh
cd /home/Untergame/tamtam_again
.venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=src .venv/bin/python scripts/population-validation-recipe.py \
  --output /tmp/review-population
PYTHONPATH=src .venv/bin/python scripts/procedure-comparative-recipe.py \
  --output /tmp/review-procedure
python3 scripts/research-baseline.py --db data/tamtam.sqlite3 \
  --output /tmp/review-state.json
PYTHONPATH=src .venv/bin/python scripts/sustained-capacity.py \
  --telemetry data/tamtam.telemetry.sqlite3 --db data/tamtam.sqlite3 \
  --hours 24 --output /tmp/review-capacity.json
git diff --stat fdb1264 1f7f483
git log --oneline fdb1264..1f7f483
systemctl --user list-timers --all --no-pager
```

Le baseline/rapport capacité sont metadata-only/read-only. Les recettes n'acceptent
pas une base production fournie. Éviter les commandes enroll-only/plan-register/
cohort-match comme simples diagnostics : elles écrivent des décisions. La revue
ne doit pas ouvrir les payloads/résultats réservés pour développer de nouvelles
règles. Pour inspecter le coût en readonly, voir PROCEDURE-EVALUATION.md.

Priorités de revue : signes/flux/funding/fees et double comptage ; définition
sémantique de l'equity unified/PM ; disponibilité temporelle et héritage de
preuves ; gardes de sélection avant finale ; coût unknown au lieu de zéro ;
continuité de capital et attribution des positions ; séparation des sources
REST/WS ; absence d'usage des réserves dans mémoire/runtime ; vraie portée des
mesures capacity/matching et parcours réellement encore scriptés.

## 8. Retour arrière praticable

1. Relever Git, unités actives, plans/versions et sessions. Conserver DB, WAL,
   télémétrie et registres : ne jamais remplacer la base par le baseline ancien.
2. Pour annuler uniquement les ressources : disable --now resources.timer,
   stop resources.service, retirer ses deux unités et daemon-reload. Collecte
   conservée ; samples anciens gardés.
3. Avant rollback ordonnanceur/recherche : arrêter uniquement leurs timers et
   laisser finir ou traiter explicitement les baux running. Conserver essais,
   curseurs, cohorte, provenance et suspensions. Réadmission de comptes explicite
   et dans le budget ; ancien curseur ne prouve pas continuité après retrait.
4. Revenir par commits ciblés après examen des dépendances et du worktree utilisateur.
   Les nouvelles tables sont laissées pour audit ; champs JSON inconnus compatibles.
5. Ne pas supprimer la distinction paper_reference_sessions avec des références
   en cours. Ne pas enlever session_starting_capital_usdc d'une session issue de
   carry_flat_cash, ni réinterpréter son PnL avec le capital initial de sa spec.
6. Ne jamais relancer implicitement une session suspendue/retirée ni réarmer
   les huit demandes IA. Nouvelle stratégie = identité/plan/historique distincts.
7. Refaire contrôle metadata pilotes, tests et observation services après retour.
   Pour les composants précis, appliquer les procédures ACCOUNTING-CONTRACT,
   PAPER-HANDOVER, PAPER-MONITORING, ALLOCATION-POLICY et CAPACITY-DECISION.

## 9. Travail restant et conditions de réveil

| Travail | Nature du manque | Condition concrète |
| --- | --- | --- |
| Valorisation account-wide | Implémentation + données/conventions | Modèle vérifié, cotations/temps/flux/dette/périmètre reliés et réconciliation sur cas réels contrastés |
| Proposition après suspension | Implémentation | Worker diagnostic→runtime isolé sous budget explicite→nouveau plan prospectif, puis gates existantes |
| Détection de changement | Implémentation/statistique | Descripteurs/tests et règle préétablie avec dépendance/conditions/incertitude, pas quelques pertes bruitées |
| Capacité machine prolongée | Accumulation + rapport à compléter | Série resources complète avec intervalles/reset/gaps déclarés et cycle de reprise observé |
| Comparaison des témoins | Observations futures + qualification | Fin de période déclarée, continuité prouvée, accounting/risque comparables ; interruption → unknown |
| Latence exécution réelle | Mesure manquante | Preuve scellée distincte des délais simulés ; aucune transaction réelle autorisée |
| Multi-instruments réel | Adaptateur manquant | N1/N2 vérifiés si une hypothèse en a besoin ; sinon état unsupported_validation_adapter maintenu |
| Fin du Goal | Travail + revue | Exigences manquantes résolues, preuves actuelles, audit complet et remise du CR final |

Les sept hypothèses needs_data doivent être réveillées sur leurs observations
requises et une empreinte réellement nouvelle, avec budget disponible ; relever
le nombre de cycles seul ne résout pas leurs diagnostics. Les données futures
ne sont pas une justification pour qualifier d'implémenté un adaptateur absent.
