# Qualification comptable — contrat de normalisation v1

`accounting.reconcile_period` calcule une période explicite sur un périmètre
prouvé. Ce reducer n'interroge pas la base brute ni les fenêtres réservées.
Il ne constitue pas encore un adaptateur exhaustif des réponses Hyperliquid.

Entrée : start_ms, end_ms, as_of_ms ; scope (id, currency, account_mode) ;
coverage par fills/funding/flows/other_income/valuation_scope avec status et
références de preuves ; valuations (bornes exactes et checkpoints) ; events.
Les événements appartiennent à (start,end], les valuations aux deux bornes.
Chaque donnée porte event_ms et available_ms ; une donnée pas encore disponible
ne fournit pas une comptabilité complète. Les identités conflictuelles bloquent
les métriques et les doublons identiques sont comptés une seule fois.

Les références de couverture doivent venir d'un adaptateur qui a vérifié les
fenêtres/cursors, positions initiales et continuité. La présence d'une réponse
REST, y compris une page courte ou vide, ne suffit pas. Les fixtures ont des
références fixture-only et ne qualifient pas un compte réel.

## Formules et exigences

PnL économique = equity_finale - equity_initiale - flux_externes.
PnL composants = PnL réalisé + variation du latent - frais + funding + autres revenus.
Écart = PnL économique - PnL composants, conservé même lorsqu'il est non nul.
Un écart mesuré n'est jamais automatiquement considéré acceptable.

Les frais négatifs sont des remises. `fee` inclut builderFee : pas de seconde
charge. Une devise différente nécessite une conversion documentée au temps
réel de l'événement, jamais le prix courant. Pas de flux net par défaut pour
un transfert : l'adaptateur doit démontrer s'il traverse la frontière du
périmètre ou reste interne. Les relations de sous-comptes ne sont pas fusionnées
sans périmètre de consolidation prouvé.

Les valeurs de plusieurs dex ne sont jamais additionnées par ce reducer.
Les modes unifiedAccount/portfolioMargin/dexAbstraction exigent un modèle de
collatéral partagé vérifié par l'adaptateur, sinon les métriques restent inconnues.
Pour les autres modes, la preuve de valuation_scope reste obligatoire : le simple
nom du mode ne certifie pas une valorisation globale ou tous les revenus.

Le rendement Modified Dietz est explicitement une estimation, avec capital
pondéré par le moment des flux. Le TWR est calculé uniquement lorsqu'une
valuation existe au timestamp de chaque flux externe. Le drawdown est celui
de cette courbe corrigée des flux, aux checkpoints observés ; le drawdown
intra-checkpoint demeure inconnu. Un capital nul/négatif ne produit pas de
rendement valide par division arbitraire.

## Utilisation et état réel

```sh
PYTHONPATH=src .venv/bin/python scripts/accounting-reconcile.py normalized-period.json --output /tmp/accounting.json
.venv/bin/python -m unittest discover -s tests -q
```

Les premiers inventaires réels de population sont unifiés. Leur collatéral
consolidé, les historiques de flux et la couverture des frais sont à normaliser
et réconcilier avant un verdict de performance. Le code ne prétend pas que la
somme des snapshots standards et HIP-3 donne le capital du compte.

Travail restant : adaptateur Hyperliquid couvrant funding/ledger/autres revenus,
spot et valorisations/conversions nécessaires, bornes comparables et preuves de
complétude. Puis cas réels contrastés et exécution automatique sur la population.
La qualification v1 descriptive reste consultable pour l'historique, sans être
transformée rétroactivement en preuve de validation économique.

## Adaptateur de données réelles et résultat du 7 octobre

`account_adapter.report_account` ne lit que les observations du nouveau collecteur
population REST. Il refuse les adresses des plans réels avant toute requête brute,
filtre la disponibilité et conserve les références d'observation. Les scopes de
perp sont séparés ; devises HIP-3 non vérifiées, spot non valorisé et funding/ledger
non classifiés ne sont jamais considérés connus ou égaux à zéro.

Rapport réel `population-accounting-20261007.json` : sept comptes inventoriés sur
une période commune explicite du 7 octobre, zéro qualification économique.
Les PnL de fills présents sont descriptifs, les métriques de rendement et de
réconciliation restent inconnues quand les preuves manquent. L'outil s'applique
à tous les comptes déjà inventoriés sans relire les données des pilotes.

```sh
PYTHONPATH=src .venv/bin/python scripts/population-accounting-report.py --db data/tamtam.sqlite3 --start-ms START --end-ms END --output /tmp/population-accounting.json
```

Source officielle vérifiée le 7 octobre :
https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes
Pour unifiedAccount et portfolioMargin, les soldes/holds sont dans l'état spot ;
les valeurs des comptes perp individuels ne sont pas significatives. Le ratio de
maintenance unifié nécessite la correspondance dex/collateralToken, les marges
cross/isolated et les soldes spot. Il ne se confond pas avec le ratio brut
exposition/accountValue calculé dans l'ancienne qualification descriptive.
Les anciens rapports demeurent datés, sans qualification rétroactive de leur ratio.
# Normalisation des événements publics — incrément du 7 octobre

`account_events.py` normalise le funding par instrument et les flux selon une
frontière explicite : une seule adresse HyperCore, spot et perp inclus.
Les événements conservent identité transactionnelle, temps, disponibilité et
référence brute. Les différentes devises ne sont pas converties implicitement.

Le funding standard est libellé USDC. Pour HIP-3, le montant rapporté est
conservé dans un scope de devise non vérifiée jusqu'à preuve du collatéral ; ce
montant ne doit pas être présenté comme une valorisation USD consolidée.

Les dépôts sont externes. Un transfert vers une autre adresse est externe à
notre frontière, y compris subAccountTransfer : aucune consolidation de propriété
n'est inférée. AccountClassTransfer est interne entre spot/perp et n'est pas un
revenu. Les flux globaux ne sont jamais recopiés dans chaque scope perp dex.

Les frais de retrait/transfert dont la convention brut/net n'est pas établie,
les mécanismes de vault, récompenses, liquidation et transferts spot restent
inconnus avec diagnostic. Une réponse vide n'établit pas leur absence historique.
Les identités excluent les montants : des événements contradictoires portant la
même identité sont signalés plutôt que fusionnés silencieusement.

Contrôle réel résumé : `account-events-control-20261007.json`. Le rapport complet
est reproductible avec `scripts/population-accounting-report.py` et les bornes
du résumé. Quinze comptes examinés, aucune qualification économique ; les bornes,
la couverture et la valorisation consolidée restent à établir.

Source : [types ledger et funding officiels](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions).

## Disponibilité des conversions de frais

Chaque `fee_conversion` exige `currency`, `rate`, `quote_ms`, `available_ms` et `evidence_ref`. Le taux doit être fini et strictement positif ; les timestamps doivent être des entiers avec `0 <= quote_ms <= event_ms` et `quote_ms <= available_ms <= as_of_ms`. Une cotation historique reçue après le fill peut servir à une analyse rétrospective seulement après sa disponibilité réelle. Une conversion absente, malformée ou indisponible laisse les métriques économiques inconnues. Les rapports déjà conservés restent inchangés ; un nouveau calcul porte un nouveau fingerprint d’entrée.

## Consolidation de pools indépendants

`account_consolidation.consolidate_equity` exige un périmètre attendu documenté et une valorisation de chaque pool à la même date économique. Chaque entrée porte scope_id, capital_pool_id, preuves de pool et de valorisation, devise et disponibilité. Deux scopes partageant le même pool bloquent la somme : un collatéral partagé exige une valorisation autoritative unique de ce pool. Une conversion entre devises exige une cotation contemporaine, positive et disponible au cutoff. Périmètre absent, scope manquant, doublon, date désalignée ou conversion inconnue produisent equity=null avec diagnostics. Les preuves de groupes sont à établir dans les adaptateurs ; attribuer simplement des IDs différents ne démontre pas leur indépendance.

Ce reducer est actuellement vérifié sur fixtures. Il ne produit pas encore une consolidation réelle depuis les inventaires Hyperliquid, ni une preuve de couverture des flux ou de rentabilité.

## Source de capital selon le mode — vérifié le 7 octobre 2026

Référence officielle : https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes . En unifiedAccount et portfolioMargin, les balances et holds sont exposés par spotClearinghouseState ; les états utilisateur perp par DEX ne donnent pas un capital utilisable. L’adaptateur conserve désormais les balances spot brutes avec preuve/disponibilité et bloque les bornes de capital perp pour ces modes, dexAbstraction et les historiques dont le mode change. Les balances ne sont pas encore une equity valorisée : cotations, dettes, positions et alignement temporel restent à établir. Aucune somme des états perp ou des stablecoins à parité implicite.

## Ratio de maintenance unifiedAccount

unified_risk.unified_ratio reprend la structure de la formule officielle vérifiée
le 8 octobre : exigences cross agrégées par token de collatéral, solde spot total
unique, allocations isolées soustraites avant division. hold n'est pas ajouté au
total. Portfolio margin et les modes historiques ne sont pas traités comme unified.
Un collatéral disponible non positif avec besoin de maintenance est un diagnostic,
jamais un zéro de risque. Résultat dimensionnel en collatéral natif, pas equity/PnL.

account_adapter conserve maintenant les composantes de marge de tous les états
perp et produit unified_maintenance_ratio_observations. Timestamp économique spot,
états DEX alignés, catalogue antérieur et périmètre entier exigés. Une réception
locale ne remplace pas le timestamp économique absent. Périmètre, token, montant,
mode, timestamp ou disponibilité manquants rendent le ratio inconnu.

Source : https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes
Tests de collatéral partagé/hold, allocations isolées, solde insuffisant, mode
incorrect, DEX absent, catalogue futur et timestamps désalignés. Cela complète
la lecture du risque ; consolidation equity/spot/dettes/FX et complétude des
flux restent à implémenter/vérifier. Pas de qualification économique réelle.
Rollback code seulement ; rapports anciens conservés, aucun changement de collecte.

### Contrôle réel des entrées du ratio — 8 octobre

unified-risk-real-control-20261008.json : cinq derniers comptes inventoriés
non protégés, choix daté et déterministe hors performance. Modes observés :
2 unifiedAccount, 1 portfolioMargin, 1 default, 1 disabled. Vingt snapshots spot
sur leurs historiques, zéro timestamp économique présent. Tous les ratios
ponctuels restent inconnus. Contrôle lecture seule, pas de fournisseur appelé,
pilotes exclus avant requête brute et aucune qualification économique.

Le diagnostic distingue maintenant mode non applicable, mode changeant,
timestamp spot absent et catalogue/périmètre antérieur absent. Chaque blocage
porte son action. Accumuler des fills ne donne pas le timestamp spot manquant ;
il faut une source de valorisation cohérente horodatée ou un modèle explicitement
fondé sur des intervalles d'observation. Receipt_time n'est pas une equity à un
instant économique prouvé. Cette lacune structurelle est distincte d'une panne
de collecte ou d'un échantillon de trades trop court.

## Fenêtres locales d'acquisition

Les snapshots spot et composantes de marge exposent maintenant acquisition_window
(requested_ms, available_ms, duration_ms). observation_windows vérifie présence,
timezone et ordre des horloges. Il expose aussi acquisition_span pour examiner
une collection de fenêtres, avec requests_overlap sans prétendre une simultanéité
économique. L'adaptateur conserve les composantes de marge même quand le capital
per-DEX est interdit dans un mode partagé.

Ces temps mesurent la requête locale et l'insertion de réponse dans l'archive.
Cache/retard du serveur peuvent placer l'état économique hors de cette fenêtre :
aucun timestamp économique n'est déduit, aucun holdout ni historique réécrit.
Les métriques comptables exactes restent inconnues sans preuves supplémentaires.
Contrôle réel acquisition-window-control-20261008.json, cinq mêmes comptes hors
pilotes et colonnes temporelles uniquement. Pas de nouvel appel API ni collecte.

Prochaine intégration : regrouper explicitement les observations par acquisition
de compte et valoriser spot/dettes/pools avec incertitude temporelle documentée.
Ne pas traiter la proximité des requêtes comme la preuve d'un snapshot atomique.
Rollback code seulement, aucun changement de schema/raw historique.

Au relevé, les 20 fenêtres sont ordonnées, durées de 1314 à 5728 ms. Le début
est enregistré avant post_info : attente du quota et archivage peuvent être
inclus, donc ce n'est pas une mesure de latence réseau ou d'exécution.

## Acquisitions explicitement liées

Les nouveaux passages population annotent les requêtes archivées avec
`acquisition_id=population_attempts.attempt_id`. Les états de marge portent
la liste attendue des DEX issue du même passage et la référence de l'observation
perpDexs. Les requêtes réseau ne changent pas : les annotations sont locales.
Une liste DEX malformée ou dupliquée est refusée. Le rapport de périmètre conserve
cet identifiant et la référence ; le rapport comptable exporte account_acquisitions.

Le reducer exige une observation du mode, une du spot, des états de marge uniques
couvrant le périmètre déclaré, sa provenance et une chronologie locale lisible.
Il distingue inventaire lié complet et inventaire lié incomplet, conserve les
preuves non liées et ne regroupe jamais l'ancien historique par proximité de temps.
Un rapprochement explicite d'appels n'est pas un snapshot atomique : les fenêtres
locales ne certifient ni absence de changement de mode ni prix économiques communs.
La présence de timestamps économiques identiques sur les composantes est déclarée
séparément ; aucun capital ou PnL n'est calculé sur cette seule condition.
La référence d'inventaire déclarée doit encore être vérifiée au stade de valorisation.

La collecte est séquentielle et le spot sans time reste inconnu. Cette amélioration
fournit le regroupement nécessaire au futur modèle de valorisation, pas une
consolidation réelle terminée. Aucun endpoint supplémentaire, cadence, coût ou
budget augmenté. L'ancien historique reste exploitable selon ses propres preuves,
sans annotations rétrospectives. Les reprises obtiennent le nouvel attempt_id et
ne complètent pas artificiellement une acquisition interrompue.

Tests : batches distincts, état manquant/dupliqué, inventaire conflictuel, legacy
non regroupé, simultanéité absente/future, equity toujours inconnue. Contrôle daté
account-acquisition-control-20261008.json lit seulement les metadata de requêtes ;
une absence de nouvelle annotation au moment du contrôle reste un rollout non
encore démontré sur données réelles.

Retour arrière : retirer annotations et reducer/appel de rapport. Les champs
supplémentaires request_json restent compatibles avec l'ancien code. Aucune table
ni migration destructive, aucun recalcul d'ancienne expérience ni restauration
complète de base requis. Les workers oneshot suivants chargent le nouveau code ;
aucun redémarrage du collecteur pilote nécessaire.

## Courbes portfolio : contrôle distinct

Vérification officielle du 8 octobre :
[Portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs)
indique des valeurs échantillonnées aux dépôts/retraits et toutes les quinze
minutes, déconseillées pour une comptabilité précise. Account value comprend
notamment latent cross/isolated et vault balances. Le document ne certifie pas
explicitement chaque périmètre spot/HIP-3/emprunt sous tous les modes. La formule
textuelle de PnL/flux n'est pas traitée comme une réconciliation indépendante.
[Modes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes)
confirme le caractère non significatif des capitaux par DEX en mode partagé.
[Portfolio margin](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-margin)
décrit également emprunts/intérêts et sous-comptes séparés ; sommer les seules
positions ou balances ne prouve pas une equity consolidée complète.

L'adaptateur exporte désormais reported_portfolio_observations à part des
valorisations reconstruites. Les fenêtres day/week/month/allTime et perp*
ne sont jamais additionnées, fusionnées ou substituées à un capital prouvé.
Le reducer valide timestamps économiques <= réception <= cutoff, montants finis,
doublons conflictuels et champs attendus. Un changement de valeur rapportée
n'est calculé qu'aux deux bornes exactes présentes, sans interpolation, et
n'est jamais présenté comme un rendement corrigé des flux. Changement de PnL
rapporté reste une mesure fournisseur dont la convention n'est pas réconciliée.
Aucun drawdown continu ou qualification économique n'est inféré.

Preuve portfolio-evidence-control-20261008.json : cinq derniers comptes inventoriés
hors pilotes, sélection sur metadata uniquement puis dernière réponse portfolio
population ; période explicite et diagnostics. Zéro appel fournisseur. Les
réponses déjà collectées ajoutent un contrôle exploitable, mais ne comblent pas
le défaut d'horodatage économique spot, ni les lacunes de couverture des flux.
Retour arrière : retirer module et champ rapport ; aucune migration ou service
à rétablir, observations originales conservées.

## Composants comptables à la frontière de l'adresse

`whole_account_observed_components` est calculé automatiquement par report_account
sur la même période que les rapports perp. Il rassemble fills/funding et flux
normalisés de l'adresse, en conservant leurs scopes d'origine et leurs devises.
Le ledger n'est pas affecté à chaque DEX : un dépôt de 100 observé une fois reste
100 à la frontière du compte, même si plusieurs DEX partagent son collatéral.
Les doublons identiques sont dédupliqués ; divergences financières restent unknown.

Chaque devise garde un rapport distinct. Pas de somme USDH+USDC ni parité
supposée pour les frais. Événement non dénommé conservé unassigned, disponibilité
au cutoff et appartenance (start,end] requises. Les composants réalisés/frais/
funding/flux sont des sommes **observées**, avec la couverture unknown du reducer.
Zéro observé n'est jamais absence de coûts/principal véritable. Ni solde spot ni
capitaux par DEX ne sont additionnés pour fabriquer une equity ; capital,
PnL économique, rendement et drawdown restent inconnus en l'absence de
valorisation complète et réconciliation. Spot cost basis, dette/intérêts, autres
revenus et couvertures extérieures restent des lacunes explicites.

account-cashflows-control-20261008.json : contrôle readonly de cinq derniers
comptes inventoriés hors pilotes, quatre rapports de devise sur période explicite,
zéro appel fournisseur et zéro qualification. Ce contrôle applique l'adaptateur
réel, sans fixture financière, mais ne transforme pas composants incomplets en
performance qualifiée. Tests : dépôt unique malgré plusieurs DEX, pages répétées,
conflits, devises distinctes, frais étrangers non convertis et événements futurs.

Retour arrière : retirer le module et le champ supplémentaire de report_account.
Aucune migration/service/cadence, observations et anciens rapports préservés.
Le modèle de valorisation account-wide et preuves de couverture restent à fournir.

## Rapport population sur une période commune

`PYTHONPATH=src .venv/bin/python scripts/population-accounting-report.py --db data/tamtam.sqlite3 --start-ms START --end-ms END --as-of-ms CUTOFF --output /tmp/population-accounting.json`

La commande ouvre SQLite en lecture seule, sans migration Store. Le registre est
filtré par réseau et disponibilité au cutoff ; les adresses sont dédupliquées.
Les comptes réservés sont exclus avant l'appel à l'adaptateur et restent visibles
comme exclusions. Une erreur de forme d'une preuve produit un échec explicite par
compte, sans interrompre les autres ni devenir une qualification. Les erreurs SQL
restent fatales. Le compteur de validations suit les verdicts booléens de
l'adaptateur ; il ne remplace aucun critère comptable. Une période commune ne
prouve pas que chaque compte possède ses bornes ou une couverture complète.

Le champ `whole_account_observed_components` regroupe les événements observés
par adresse et devise, conservant leurs scopes d'origine. Un dépôt n'est pas
répliqué par DEX ; aucune conversion implicite ni equity consolidée n'est déduite.

Retour arrière : restaurer uniquement le script précédent et retirer
`account_batch.py`. Aucun schéma, service ou historique n'est modifié.

## Témoin indépendant de rétention des fills

`PYTHONPATH=src .venv/bin/python scripts/population-fill-retention.py --db data/tamtam.sqlite3 --telemetry-db data/tamtam.telemetry.sqlite3 --address ADDRESS`

Un appel public ciblé `userFills`, non agrégé, est archivé dans la source
population. Les pilotes sont refusés avant appel. Aucun timer/cadence ni budget
IA n'est modifié ; réservation REST conservatrice 120 poids via quota partagé.
L'endpoint retourne au plus les 2000 fills les plus récents. Un témoin non vide,
sans doublon ni timestamp futur, demandé après la fin de période et disponible
au cutoff, peut prouver que sa borne ancienne est encore accessible lorsque son
plus vieux fill est antérieur ou égal au début de période. Une réponse courte ou
vide seule n'est pas cette preuve. Les requêtes filtrées/agrégées sont refusées.

L'adaptateur combine ce témoin avec l'union de pages de période épuisées. Il
peut alors établir la couverture des fills publics de cette adresse. Cela ne
prouve ni historique à vie, ni absence de défaut du fournisseur, ni funding,
ledger, autres revenus ou equity. Les pages sans témoin gardent unknown ; un
témoin ne ferme pas un trou de pagination. Une période récente peut donc devenir
exploitable sans déclarer tout l'ancien historique complet.

Contrat officiel : https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
Poids officiels : https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
Sources consultées le 8 octobre 2026. Garantie conditionnelle au contrat de
l'endpoint ; elle ne constitue pas une certification indépendante du fournisseur.

Rollback : restaurer le calcul de couverture et retirer le script ciblé ; garder
les observations déjà archivées. Aucun effacement/migration requise. Les
valorisations restent soumises à leurs preuves ; ce témoin ne les remplace pas.
