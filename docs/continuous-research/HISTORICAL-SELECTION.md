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

Version `historical-curves-v1.2`, cutoff fixe fourni à chaque rapport. États distincts : performance déclarée, qualité des données, activité et statut de décision. Les révisions 1.1/1.2 ajoutent une surveillance de reprise 30/90/180 jours avec des fenêtres fixes et affichent les flux externes observés sur la période récente ; elles ne changent pas les critères de sélection principale.

- Signal `positive_declared` : changements PnL déclarés positifs sur les horizons 90 et 180 jours avec les bornes précédentes ci-dessus.
- Éligibilité pour approfondissement : au moins quatre mois observés avec deux points ou plus sur 180 jours, aucun mois positif observé ne représentant plus de 50 % de la somme des changements positifs observés, et résultat positif déclaré sur 90 et 180 jours. Les mois inconnus n'entrent ni au numérateur ni au dénominateur ; chaque mois n'a pas à être positif.
- Activité fréquente : au moins 20 fills observés sur au moins quatre jours UTC distincts, avec une seule plage continue de requête d'au moins 25 jours, non saturée. Cette règle exclut les comptes dont l'historique est trop court ; elle ne fait pas passer des fills partiels pour une fréquence complète.
- Le groupe `deepen` de l'allocation REST donne la priorité aux statuts qui passent la règle de courbes, ensuite au plus faible taux de concentration, puis au plus grand nombre de mois positifs observés. Les contrôles leaderboard, uniformes et exploration gardent leurs créneaux. Aucun dollar de PnL ne sert de clé de tri.
- Avant une nouvelle IA : une décision historique qualifiante, des données réellement nouvelles incluses dans une coupure ultérieure, et le budget global existant doivent tous passer. Le sceau de recherche conserve en plus l'empreinte de contenu, le cooldown et le plafond partagé ; le plafond n'est pas réarmé.

Les seuils servent à écarter les courbes dominées par un seul mois et les historiques d'activité trop courts. Ils ne sont pas des seuils universels de rentabilité ou de robustesse. Les 90/180 jours servent à comparer plusieurs mois ; l'observation mensuelle exige quatre mois sur les six attendus, et une contribution mensuelle maximale de 50 % empêche qu'un seul épisode fasse la majorité des gains positifs observés. Les critères d'activité demandent une cadence au moins hebdomadaire dans un mois réellement couvert.

## Cas de flux, révisions et lacunes externes

Le cutoff du premier rapport traite explicitement les points dont les mêmes timestamps ont différentes valeurs dans des observations successives : la valeur disponible la plus récente est retenue et le nombre de timestamps révisés est conservé. La documentation Hyperliquid ne précise pas sa politique de révision. Dans l'archive autorisée à ce cutoff, aucune révision de point n'a été observée ; l'absence de révision dans cette archive ne prouve pas qu'il n'en existe pas.

Les événements de funding et de ledger normalisables sont attachés à une adresse et une devise, mais leurs pages restent incomplètes et ne sont pas réconciliées aux courbes. Les transferts internes, retraits avec frais non classés, mouvements de vault, intérêts et événements non pris en charge ne sont pas convertis en PnL.

Un des cinq signaux de reprise illustre cette limite : la fenêtre 30 jours a un PnL déclaré de +15,48 M et un changement d'account value de +77,70 M, tandis que deux transferts externes USDC normalisés totalisent +13,00 M sur les pages actuellement disponibles. Les fenêtres PnL 90/180 jours restent négatives (−20,47 M/−10,99 M). La couverture du ledger est inconnue ; ces montants n'expliquent pas nécessairement tout l'écart, et le compte reste en surveillance seulement.

La mention distincte de la mission concernant une hausse d'environ 4,45 M USDC ne comprend pas d'adresse ou de référence d'archive. La recherche locale des exports documentaires et des événements autorisés au cutoff n'a pas retrouvé cette valeur exacte ; je ne la présente donc pas comme un cas revalidé. Les tickets `TAMTAM_AGAIN-6` et `TAMTAM_AGAIN-12` sont servis par YouTrack local, mais leur API a répondu `401 Unauthorized` sans session utilisateur ; leur contenu courant n'a pas été lu. Le compte rendu propose ci-dessous un texte de mise à jour sans le publier.

## Rapport réel et preuve d'exécution

Premier cutoff figé avant extraction des résultats : `1791539739000` ms (`2026-10-09T09:55:39Z`). Inventaire par `account_scope_reports`, autorisation historique au cutoff via `authorized_account_history`, exclusions protégées avant lecture des payloads. Le rapport analyse tous les comptes permis, y compris ceux en état `retired` ; source de courbe et d'activité : observations `hyperliquid-population-rest-v1` disponibles à ce cutoff.

Voir [rapport Markdown](historical-selection-20261009/report.md), [table CSV](historical-selection-20261009/accounts.csv) et les courbes SVG liées dans le rapport. Le JSON complet conserve les sources par endpoint, les points, frontières, révisions, fills/ordres, flux observés, expositions et motifs.

Commande reproductible :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-historical-screen.py \
  --db data/tamtam.sqlite3 --as-of-ms 1791539739000 \
  --output-dir docs/continuous-research/historical-selection-20261009
```

La commande n'interroge aucun fournisseur et ne lance aucun modèle. Les décisions sont ajoutées à `population_historical_decisions` avec date, cutoff, sources, version, fingerprint et motifs ; la contrainte unique empêche le doublon sur une relance identique. Les unités installées sont versionnées dans `systemd/user/tamtam-again-historical-screen.service` et `.timer`. Le timer relit chaque jour les archives au cutoff UTC 10:10, cinq minutes avant le déclenchement à 10:15. Il ne consomme pas les créneaux REST et ne plafonne pas le catalogue aux 32 slots actifs.

Preuve de service datée `historical-screen-timer-control-20261009.json` : timer utilisateur actif et activé, dernier déclenchement automatique à 10:15 UTC, prochain prévu le 10 octobre à 10:15 UTC. Le lancement automatique a réussi ; un lancement de contrôle de la même unité a aussi réussi de 10:16:41 à 10:16:45 UTC. Ce dernier a lu 24 734 payloads autorisés, analysé 87 comptes, ajouté 87 décisions, effectué zéro requête fournisseur et zéro appel IA. La boucle de recherche existante conserve son plafond global de huit requêtes ; il est déjà utilisé à 8/8. Le filtre intégré à son scheduler a bloqué les 87 comptes sur la qualification insuffisante ; aucune requête ou RE n'a été lancée par cette mission.

## Retour arrière

Désactiver seulement `tamtam-again-historical-screen.timer`, arrêter son service oneshot si nécessaire et conserver `population_historical_decisions` ainsi que les rapports. Retirer le filtre historique de `population_scheduler` rétablit l'ancien routage IA ; les tables et budgets restent conservés. Aucun ordre réel ni appel fournisseur n'est effectué par ce screening.

## Texte proposé pour YouTrack

**TAMTAM_AGAIN-6 — qualification historique**

> Rapport `docs/continuous-research/historical-selection-20261009/` au cutoff fixe du 9 octobre 2026 09:55:39 UTC : 87 comptes autorisés analysés, 20 PnL déclarés positifs sur 90 et 180 jours, 37 négatifs sur au moins un horizon mesuré, 30 inconnus. Neuf positifs passent les contrôles de concentration mensuelle et attendent une meilleure couverture d'activité ; aucun ne satisfait l'activité fréquente, car aucun historique de fills ne couvre 25 jours continus. Aucun résultat ne valide une performance nette. Voir le contrat HISTORICAL-SELECTION.md. La référence locale du cas d'entrée de fonds de 4,45 M USDC n'a pas été retrouvée ; elle reste à confirmer avec la source d'archive.

**TAMTAM_AGAIN-12 — screening périodique**

> Le timer `tamtam-again-historical-screen.timer` est activé quotidiennement à 10:15 UTC, cutoff stable 10:10 UTC. Premier passage réussi le 9 octobre : 87 comptes, 24 734 payloads lus, zéro appel réseau/IA ; prochaine exécution le 10 octobre. Les décisions immuables alimentent le groupe d'allocation `deepen` sans toucher aux groupes contrôle/exploration. Le filtre IA demande qualification historique, données nouvelles incluses au cutoff et budget partagé disponible. Plafond existant conservé à 8/8 ; aucun appel ni nouvelle RE lancé ici.
