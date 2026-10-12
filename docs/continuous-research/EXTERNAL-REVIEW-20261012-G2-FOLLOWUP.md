# CR de suivi externe — reprise G2 — 2026-10-12

## Portée et conservation

Ce CR complète la revue historique `tamtam-85fe987` et la fiche G2 initiale; il ne remplace pas les anciens résultats. La fiche G2 corrigée, le rapprochement reproductible a880 et ses données structurées sont conservés dans Git comme nouvel état de revue. Aucun appel IA de recherche, nouvelle collecte fournisseur, augmentation de budget ni ordre réel n'a été effectué.

## Corrections appliquées

- `be504…77b` a trois mois négatifs sur les six mesurés : avril −5 265,687828; juin −18 731,218665; juillet −310 091,600116 USDC. La priorité de travail est désormais troisième, après `a880…4ee` puis `67f7…9ba`. Ce rang mesure le coût de qualification, pas la performance ni l'admissibilité.
- `67f7…9ba` a six jours UTC actifs observés dans les pages fills. La divergence valeur/PnL ne sert pas seule de critère de performance : sans flux complets, elle ne démontre ni échec ni anomalie. La valeur en baisse n'est pas un motif autonome de déclassement.
- L'ordre de travail est `a880` (fermer le rapprochement historique reproductible), `67f7` (PnL récent presque plat/négatif et couverture des flux à compléter), puis `be504` (trajectoire mensuelle heurtée, périmètre portfolio-margin plus coûteux).
- La règle six heures/début ±15 min/valorisation finale d'une heure reste un contrôle comptable récent; elle n'est pas imposée aux séries historiques.

Les motifs et bases de calcul détaillés restent dans [`economic-qualification-cards-20261012-g2.md`](economic-qualification-cards-20261012-g2.md). La première fiche G2 et la fiche historique G1 restent conservées séparément.

## Rapprochement historique a880

Les archives locales ont permis de retenir la plus courte fenêtre avec bornes communes exactes de `allTime.pnlHistory` et `accountValueHistory`, snapshots perp associés et pages d'événements qui chevauchent la période : 8 octobre 2026, 15:24:45.724–16:17:15.515 UTC (52 min 29,791 s).

- PnL déclaré : 552 382,257798 → 556 308,453586, soit **+3 926,195788 USDC**.
- Valeur de compte : 233 473,459731 → 226 559,335426, soit **−6 914,124305 USDC**.
- Un `send` externe à la frontière de cette adresse de **−11 000 USDC** est archivé pendant l'intervalle. Destination et relation à d'autres comptes : inconnues.
- Sous la seule convention arithmétique conditionnelle `ΔPnL = Δvaleur − flux signé` (sortie négative), le pont donne +4 085,875695 USDC et un résidu déclaré moins pont de **−159,679907 USDC**. Le transfert explique la majeure partie de l'écart sous cette convention; ceci n'est pas une attribution finale certifiée.
- Les archives contiennent 6 957 fills dédupliqués et 387,231866 USDC de fees observées, ainsi que 18 événements funding totalisant −0,410559 USDC. Les pages sont marquées incomplètes ou épuisées par budget. Les frais et funding sont présentés séparément et ne sont pas déduits une seconde fois; l'API ne ventile pas leur inclusion point par point dans la courbe. Les snapshots de positions sont limités au DEX perp standard et ne sont pas ajoutés à la valeur/PnL.

La méthode, les références brutes, les changements de positions, les règles de déduplication et la commande de reproduction se trouvent dans [`archive-reconciliation-a880-20261008.md`](archive-reconciliation-a880-20261008.md) et [`archive-reconciliation-a880-20261008.json`](archive-reconciliation-a880-20261008.json). Le script lit SQLite en lecture seule et contrôle l'autorisation de l'historique avant de décoder les charges utiles.

## Preuves, inconnues, action minimale

Les bornes de courbes et les pages retrouvées rendent le pont arithmétique reproductible. Elles ne rendent pas complètes les pages ledger, funding ou fills : chaque page concernée est `complete=0`, la couverture/rétention historique reste inconnue, et le lien économique du destinataire du transfert n'est pas établi. Le périmètre de positions observé ne consolide ni spot évalué, ni vaults, ni autres DEX/comptes. Aucune preuve d'absence de couverture externe n'est requise pour qualifier le seul périmètre public observé; celle-ci demeure simplement inconnue.

L'endpoint fills documente un maximum de 2 000 lignes par réponse et une disponibilité limitée aux 10 000 fills les plus récents; au rythme de cette fenêtre, 10 000 fills correspondraient à environ 75,5 minutes, estimation dépendante du débit et non garantie de rétention. L'intervalle du 8 octobre peut donc être impossible à récupérer complètement aujourd'hui. Une preuve plus forte demanderait uniquement, si elle est jugée utile, une collecte prospective bornée avec deux snapshots `portfolio` et `clearinghouseState`, et les flux fills, funding et ledger en tranches courtes avec curseurs, nombres de pages et statuts de complétude. Aucune collecte n'a été lancée.

La documentation fournisseur indique que la valeur de compte inclut le PnL latent et que sa courbe PnL utilise valeur et flux de dépôts/retraits; elle avertit que les graphes échantillonnés ne sont pas une comptabilité précise. Elle ne résout pas la complétude de ces archives ni l'inclusion événement par événement des coûts. [Graphiques de portefeuille](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs) · [Info endpoint](https://hyperliquid.gitbook.io/Hyperliquid-docs/for-developers/api/info-endpoint).

**Conclusion pour revue externe :** priorité d'investigation corrigée et rapprochement local partiel réalisé. Les preuves soutiennent un mécanisme de flux plausible dans la fenêtre choisie, avec un résidu conditionnel de −159,679907 USDC; elles ne suffisent pas à établir un rendement net historique ou une validation économique des trois comptes. Les actions minimales requises pour une preuve plus forte sont prospective capture complète d'un intervalle commun, et, pour be504, la consolidation explicite des DEX/sous-comptes/devises. Le contrôle récent reste bloqué tant que sa fenêtre ne satisfait pas la politique six heures/une heure.
