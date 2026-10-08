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
