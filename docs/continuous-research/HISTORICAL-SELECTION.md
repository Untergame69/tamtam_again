# Sélection historique par courbes de portefeuille

## Contrat des données

`POST info {"type":"portfolio","user":...}` renvoie des fenêtres `day`, `week`, `month`, `allTime`, `perpDay`, `perpWeek`, `perpMonth` et `perpAllTime`. Chaque fenêtre expose `accountValueHistory`, `pnlHistory` (paires timestamp/valeur) et `vlm`. La documentation API n'établit pas l'unité ni la construction de `vlm`, ni le périmètre économique complet de chaque fenêtre. [Info endpoint — Query a user's portfolio](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#query-a-users-portfolio)

Hyperliquid décrit les courbes comme échantillonnées aux dépôts/retraits et toutes les quinze minutes, et déconseille de les employer pour une comptabilité précise. `account value` inclut le PnL latent des positions cross et isolated ainsi que les soldes de vault. La même page donne `pnl = account value + deposits - withdrawals`. Ce signe paraît incohérent avec une correction usuelle du capital externe ; il est conservé ici comme formule publiée, sans lui attribuer une interprétation nette non vérifiée. Les courbes elles-mêmes ne prouvent ni la complétude des dépôts/retraits ni l'absence de révision des points. [Portfolio graphs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs)

Les modes `unifiedAccount` et `portfolioMargin` partagent des soldes spot et perp ; en mode partagé, les soldes par DEX ne sont pas une equity séparée. Portfolio margin inclut les DEX HIP-3 et peut prêter les actifs éligibles. La documentation des courbes ne spécifie pas assez le traitement de chaque mode, dette, intérêt, rendement, actifs spot ou vault pour valider une performance consolidée par adresse. Les frais, paiements de funding, positions ouvertes, sous-comptes, vaults externes et couvertures sur d'autres plateformes restent des risques ou des périmètres inconnus tant qu'ils n'ont pas leurs propres preuves. [Account abstraction modes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes), [Portfolio margin](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-margin)

Contrat appliqué :

- `allTime.pnlHistory` est la courbe primaire de présélection. `perpAllTime`, `accountValueHistory`, les autres fenêtres et `vlm` sont affichés séparément ; aucune série n'est additionnée ou substituée à une autre.
- Les changements restent des changements déclarés par le fournisseur. Les valeurs d'`accountValueHistory` ne sont ni un bénéfice ni un rendement corrigé des flux.
- Les bornes roulantes sont prises avant la cible et sans interpolation. Fraîcheur finale maximale : trois jours. Tolérance de retard de la borne initiale : 3, 7, 15 et 30 jours pour 30, 90, 180 et 365 jours. La date et la durée réellement observées sont exportées par compte.
- Le drawdown est nommé « baisse maximale échantillonnée du PnL depuis un sommet », en unités nominales de la courbe. Il n'est jamais divisé par le capital. Une mesure distincte peut être calculée sur `accountValueHistory`, sans la présenter comme un rendement.
- Une valeur absente, une borne hors tolérance, un point futur ou une série incomplète produit `unknown`, pas une perte.
- `vlm` reste un volume déclaré, pas un compteur de transactions. Les fills, ordres associés aux fills et `historicalOrders` sont rapportés avec leur fenêtre de requête, leur pagination et leur troncature possible. Les fills ne sont pas des décisions indépendantes.
- Hyperliquid borne `userFillsByTime` à 2 000 fills par réponse et aux 10 000 fills les plus récents ; `historicalOrders` conserve au plus 2 000 ordres récents. Un compte peut donc présenter beaucoup de fills observés sans que leur fréquence réelle sur un mois soit connue. [Info endpoint — fills and orders](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- Les marchés viennent des instruments explicitement vus dans les fills. Les positions et inventaires spot sont des snapshots courants horodatés ; ils ne reconstruisent pas le risque historique.

## Règles et classement

La politique courante est `historical-curves-v2.0`; le rapport v1.2 du 9 octobre reste un résultat archivé et inchangé. États distincts : PnL déclaré, qualité des données, activité observée et disponibilité économique pour une RE.

- Signal `positive_declared` : changements PnL déclarés positifs sur les horizons 90 et 180 jours avec les bornes précédentes ci-dessus.
- La comparaison hebdomadaire et mensuelle utilise des bornes UTC communes échantillonnées et partagées entre intervalles. Chaque variation mesurée est attribuée une seule fois. Les limites tolèrent au plus 7 jours de retard ; les gaps maximums sont de 10 jours par semaine et 15 par mois. Les intervalles sans bornes, échantillons internes suffisants ou gaps tolérés restent inconnus. Le delta d'horizon est réconcilié à la somme attribuée plus un résidu non attribuable ; la concentration est inconnue si la couverture n'est pas complète.
- Activité positivement observée : les fills dédupliqués constituent une borne inférieure. Au moins 20 fills sur 4 jours UTC donne `frequent_activity_observed_lower_bound`; 20 fills regroupés sur moins de 4 jours restent `clustered`; les nombres inférieurs gardent un statut distinct. La couverture demandée et les états de pagination sont rapportés séparément. Pagination terminée ne prouve pas la rétention complète.
- `credible_deep_dive_candidate` signifie seulement que les courbes et l'activité satisfont cette présélection descriptive : PnL déclaré positif à 90/180 jours, au moins quatre mois mesurés avec deux échantillons ou plus et concentration positive mensuelle au plus 50 %. Ce statut n'autorise ni recherche IA ni RE. Le scheduler exige en plus `economic_validation=true`, `economic_research_readiness.status=approved_for_re`, l'éligibilité explicite et des références de preuve ; les rapports v2 restent bloqués jusqu'à une approbation économique distincte.
- Le groupe `deepen` de l'allocation REST donne la priorité aux statuts qui passent la règle de courbes, ensuite au plus faible taux de concentration, puis au plus grand nombre de mois positifs observés. Les contrôles leaderboard, uniformes et exploration gardent leurs créneaux. Aucun dollar de PnL ne sert de clé de tri.
- Avant une nouvelle IA : une décision historique qualifiante, des données réellement nouvelles incluses dans une coupure ultérieure, et le budget global existant doivent tous passer. Le sceau de recherche conserve en plus l'empreinte de contenu, le cooldown et le plafond partagé ; le plafond n'est pas réarmé.

Ces seuils écartent certaines courbes dominées par un seul mois et décrivent les fills observés. Ils ne mesurent pas la robustesse, la rentabilité nette ou la stabilité mensuelle de l'activité.

## Cas de flux, révisions et lacunes externes

Le cutoff du premier rapport traite explicitement les points dont les mêmes timestamps ont différentes valeurs dans des observations successives : la valeur disponible la plus récente est retenue et le nombre de timestamps révisés est conservé. La documentation Hyperliquid ne précise pas sa politique de révision. Dans l'archive autorisée à ce cutoff, aucune révision de point n'a été observée ; l'absence de révision dans cette archive ne prouve pas qu'il n'en existe pas.

Les événements de funding et de ledger normalisables sont attachés à une adresse et une devise, mais leurs pages restent incomplètes et ne sont pas réconciliées aux courbes. Les transferts internes, retraits avec frais non classés, mouvements de vault, intérêts et événements non pris en charge ne sont pas convertis en PnL.

Un des cinq signaux de reprise illustre cette limite : la fenêtre 30 jours a un PnL déclaré de +15,48 M et un changement d'account value de +77,70 M, tandis que deux transferts externes USDC normalisés totalisent +13,00 M sur les pages actuellement disponibles. Les fenêtres PnL 90/180 jours restent négatives (−20,47 M/−10,99 M). La couverture du ledger est inconnue ; ces montants n'expliquent pas nécessairement tout l'écart, et le compte reste en surveillance seulement.

Le cas de flux `0x87f9cd15f5050a9283b8896300f7c8cf69ece2cf` est maintenant documenté dans [la revue externe du 12 octobre](EXTERNAL-REVIEW-20261012.md). À ses bornes, les observations natives `allTime.pnlHistory`, `allTime.accountValueHistory`, `perpAllTime.pnlHistory` et `perpAllTime.accountValueHistory` diffèrent nettement. Les événements ledger disponibles n'en réconcilient pas les valeurs ; le compte ne reçoit donc pas d'approbation économique. Les tickets YouTrack -6 et -12 sont lisibles avec le client local authentifié et seront mis à jour avec les résultats de cette reprise.

## Rapport réel et preuve d'exécution

Premier cutoff figé avant extraction des résultats : `1791539739000` ms (`2026-10-09T09:55:39Z`). Inventaire par `account_scope_reports`, autorisation historique au cutoff via `authorized_account_history`, exclusions protégées avant lecture des payloads. Le rapport analyse tous les comptes permis, y compris ceux en état `retired` ; source de courbe et d'activité : observations `hyperliquid-population-rest-v1` disponibles à ce cutoff.

Voir [rapport Markdown](historical-selection-20261009/report.md), [table CSV](historical-selection-20261009/accounts.csv) et les courbes SVG liées dans le rapport. Le JSON complet conserve les sources par endpoint, les points, frontières, révisions, fills/ordres, flux observés, expositions et motifs.

Le classement courant v2.0 est publié dans [le rapport du 12 octobre](historical-selection-20261012/report.md), avec [CSV](historical-selection-20261012/accounts.csv) et JSON complet. Son cutoff est `1791789394195` ms (`2026-10-12T07:16:34Z`). Il conserve les résultats et décisions précédents et n'effectue aucune requête fournisseur.

Commande reproductible :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-historical-screen.py \
  --db data/tamtam.sqlite3 --as-of-ms 1791539739000 \
  --output-dir docs/continuous-research/historical-selection-20261009
```

La commande n'interroge aucun fournisseur et ne lance aucun modèle. Les décisions sont ajoutées à `population_historical_decisions` avec date, cutoff, sources, version, fingerprint et motifs ; la contrainte unique empêche le doublon sur une relance identique. Les unités installées sont versionnées dans `systemd/user/tamtam-again-historical-screen.service` et `.timer`. Le timer relit chaque jour les archives au cutoff UTC 10:10, cinq minutes avant le déclenchement à 10:15. Il ne consomme pas les créneaux REST et ne plafonne pas le catalogue aux 32 slots actifs.

Le timer historique quotidien existant reste actif. La file légère séparée `tamtam-again-historical-queue.timer` a été activée au 12 octobre, avec un maximum de quatre `portfolio` par passage et 15 minutes entre passages. Le passage manuel et le premier passage timer ont chacun réussi avec quatre appels, zéro échec et zéro appel IA. Les huit observations alimentent une file initiale de 8 504 candidates et le limiteur REST partagé ; les nouvelles adresses sont autorisées après vérification de protection et de libération historique. Mesure au relevé : 849 poids/min sur 60 min, zéro HTTP 429 ; le débit moyen réservé par cette file est 5,333 poids/min. Le plafond de recherche existant reste inchangé ; aucun dispatch RE n'a été effectué.

## Retour arrière

Désactiver seulement `tamtam-again-historical-screen.timer`, arrêter son service oneshot si nécessaire et conserver `population_historical_decisions` ainsi que les rapports. Retirer le filtre historique de `population_scheduler` rétablit l'ancien routage IA ; les tables et budgets restent conservés. Aucun ordre réel ni appel fournisseur n'est effectué par ce screening.

Les commentaires YouTrack du 12 octobre sur `TAMTAM_AGAIN-6` et `TAMTAM_AGAIN-12` consignent la politique v2.0, les chiffres du nouveau classement, la file périodique et les résultats de test. Ils n'effectuent aucune transition de statut.
