# Qualification historique des trois présélections — G2

## Cadre de lecture

Cutoff commun `1791789394195` (`2026-10-12T07:16:34.195Z`). Cette reprise s'appuie sur le rapport immuable [`historical-selection-20261012/report.json`](historical-selection-20261012/report.json) et l'audit reproductible des pages sources [`economic-performance-archive-check-20261012.json`](economic-performance-archive-check-20261012.json), qui consigne les références `raw_observations:*`, comptes de pages et règles de déduplication fills/ledger/funding. Aucune donnée postérieure au cutoff n'est incluse. Les résultats descriptifs de la fiche précédente restent archivés dans [`economic-qualification-cards-20261012.md`](economic-qualification-cards-20261012.md).

La règle six heures/début ±15 min/valorisation finale âgée d'au plus une heure du fichier [`account-qualification-period-policy.json`](../../config/account-qualification-period-policy.json) reste un contrôle de mesure comptable **récente**. Elle n'est pas un préalable à l'analyse historique ci-dessous. Les valeurs de `allTime.pnlHistory` sont des variations nominales déclarées par le fournisseur; elles ne prouvent ni PnL net ni rendement. Les `accountValueHistory` sont affichées séparément avec les mêmes timestamps de courbe et ne sont pas un PnL ajusté. On ne les additionne pas aux séries `perpAllTime`, dont le périmètre peut recouvrir `allTime`.

Pour les comparaisons 30/90/180 j, le rapport retient le dernier point observé au plus tard à la borne visée, sans interpolation. Les durées réellement mesurées sont donc environ 32, 95 et 186 jours; les timestamps exacts sont reproduits ci-dessous. Les baisses sont des baisses entre points échantillonnés, pas des drawdowns intrajournaliers exhaustifs. Aucun rendement n'est calculé : le capital moyen, les apports/retraits complets et l'exposition historique ne sont pas établis.

## `a880…4ee` — `0xa880d6cc607a05ea617307ab3b0d335e8d8424ee`

**Périmètre observé.** Mode déclaré `disabled` dans 67 observations d’archives du mode (`mode_observations_by_value` de l’audit). Les courbes comparées sont `allTime.pnlHistory` et `allTime.accountValueHistory`; leurs bornes proviennent de `raw_observations:25999259`. `perpAllTime.pnlHistory` est identique aux trois deltas affichés, sans prouver que l’equity/expositions soient consolidées. Les pages fills dédupliquées de l’audit listent dix-huit marchés dont HYPE, TRX et ZEC. Les snapshots `raw_observations:26000707`, `26000828`, `26000900`, `26001031`, `26001210`, `26001720`, `26001905` et `26001973` montrent huit DEX avec positions vides à cet instant; l’inventaire spot est `raw_observations:25999196`. Cela ne couvre pas l’historique complet, le spot valorisé, vaults, sous-comptes ou hedges externes.

| Horizon | `allTime.pnlHistory` Δ nominal | bornes observées UTC (début → fin) | `accountValueHistory` Δ | pire baisse échantillonnée PnL / valeur |
|---|---:|---|---:|---:|
| 30 j ciblés | +16 094,867590 | 09-09 22:15:24.992 → 10-11 23:36:20.592 | +109 518,368246 | −5 860,758781 / −13 133,484069 |
| 90 j ciblés | +56 403,542786 | 07-08 23:10:00.038 → 10-11 23:36:20.592 | +118 032,389143 | −5 860,758781 / −64 220,506980 |
| 180 j ciblés | +128 249,465591 | 04-08 23:50:00.014 → 10-11 23:36:20.592 | +101 776,989485 | −5 860,758781 / −109 728,333124 |

Sur les six buckets mensuels de PnL observés, la somme attribuée est +117 685,689722, le résidu non attribué +10 563,775869 (8,24 % du mouvement brut calculé), et le plus grand mois positif représente 32,40 % du delta positif. Aucun bucket mensuel mesuré n'est négatif; des pertes entre observations restent possibles. Le résidu n'est pas assimilé à du PnL.

**Contrôle de source sur archives.** Les bornes de `raw_observations:25999259` révèlent un écart valeur moins PnL de +93 423,500656 sur 30 j, +61 628,846357 sur 90 j et −26 472,476106 sur 180 j. C’est un résidu entre deux séries fournisseur, pas un flux attribué. L’audit liste 121 pages fills dédupliquées, couvrant 3,504 jours contigus avec `page_budget_exhausted`; 178 438 fills, 133 925 identifiants d’ordres inférés et cinq jours UTC actifs. Fees observées : 279,079860 USDC (178 438 lignes fee); cette couverture courte ne permet pas de les soustraire aux deltas historiques. Les 67 pages funding et 2 pages ledger normalisées affichent deux flux externes totalisant −23 000 USDC et 2 141 écritures funding (+1,695495 USDC, scope inconnu). Toutes les références de pages sont énumérées dans l’audit JSON. Elles ne démontrent pas de couverture ledger/funding sur les bornes des courbes.

**Capital et risque.** La valeur de compte progresse nominalement sur les trois horizons, mais les mouvements ne correspondent pas au PnL déclaré et les baisses échantillonnées de valeur sont nettement plus grandes que celles de la courbe PnL. La valeur spot n'est pas consolidée/pricée; ni levier historique, ni capital moyen, ni rendement ajusté des flux ne sont connus.

**Décision : signal historique suffisant pour approfondir le contrôle de source sur ce compte et ce périmètre déclaré.** Cela reste une présélection de données, pas un compte validé ou une autorisation de RE/capital. Action minimale : choisir une fenêtre historique bornée et aligner deux snapshots portfolio avec les fills, fees, funding et ledger complets sur les mêmes timestamps; rapprocher alors l'écart valeur/PnL et les 23 000 USDC. Le contrôle six heures/une heure ne s'applique que si la conclusion porte sur la situation récente.

## `be504…77b` — `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b`

**Périmètre observé.** Mode déclaré `portfolioMargin` dans 61 observations d’archives. L’inventaire de compte `raw_observations:26015179` signale un sous-compte; les pages fills répertoriées dans l’audit montrent des instruments `xyz:` et `para:` (dont `xyz:GOLD`, `xyz:INTC`, `xyz:TLT`, `xyz:XYZ100`). Le snapshot spot est `raw_observations:26015690`; snapshots DEX ponctuels : `26016300`, `26016436`, `26016509`, `26016574`, `26016692`, `26016764`, `26016835`, `26016954`. Les références des courbes sont dans l’audit. Le rapport n’établit pas si les equities par DEX et sous-compte se recouvrent; aucun capital n’est additionné entre entités. `allTime` et `perpAllTime` montrent des deltas distincts et des périmètres possiblement chevauchants.

| Horizon | `allTime.pnlHistory` Δ nominal | bornes observées UTC (début → fin) | `accountValueHistory` Δ | pire baisse échantillonnée PnL / valeur |
|---|---:|---|---:|---:|
| 30 j ciblés | +193 867,762938 | 09-11 23:32:00.003 → 10-11 23:41:34.949 | +197 256,562938 | −62 790,713503 / −355 766,856817 |
| 90 j ciblés | +266 983,235321 | 07-08 22:15:03.873 → 10-11 23:41:34.949 | +425 132,755321 | −228 225,192077 / −355 766,856817 |
| 180 j ciblés | +365 968,587423 | 04-08 22:12:00.000 → 10-11 23:41:34.949 | +862 941,957423 | −331 858,707762 / −355 766,856817 |

Les six buckets mensuels mesurés attribuent +302 966,665881, avec résidu +63 001,921542 (6,09 % du mouvement brut); le mois positif le plus important pèse 39,16 % du delta positif. Aucun bucket mesuré n'est négatif, mais les fortes baisses échantillonnées — jusqu'à −331 858,707762 sur le PnL — imposent de ne pas résumer le compte à son delta positif.

**Contrôle de source sur archives.** Valeur moins PnL donne +3 388,800000 sur 30 j, +158 149,520000 sur 90 j et +496 973,370000 sur 180 j. L'accord récent sur le delta 30 j ne valide pas les horizons plus longs. La série `perpAllTime.pnlHistory` rapporte respectivement +192 588,317205, +227 042,277491 et +170 988,084954; les différences face à `allTime` interdisent de les sommer ou de supposer une couverture identique. La requête fills archivées couvre 4,964 jours contigus (pagination marquée terminée, sans preuve de rétention API) : 891 fills, 115 ordres inférés et cinq jours UTC actifs. Les fees des pages observées sont 320,973957 USDC et 0,00378 UZEC; ces montants ne constituent pas des fees 30/90/180 j. Les écritures classées montrent −55 990 USDC et −2 000 HYPE de flux externe, plus funding −320,204952 en devise DEX non vérifiée (266 événements) et +6,589680 USDC (28). La couverture, l'alignement temporel et les règles de conversion ne sont pas prouvés.

**Capital et risque.** `portfolioMargin`, sous-compte, spot/HIP-3, transferts multi-actifs et possible recouvrement entre périmètres empêchent d'inférer le capital employé ou un rendement. La valeur de compte varie bien plus que le PnL déclaré sur 90/180 j, et les pertes intermédiaires échantillonnées sont du même ordre que les gains nominaux. Le levier historique et les expositions hors compte restent inconnus.

**Décision : signal historique suffisamment fort pour approfondir la réconciliation du périmètre portfolio-margin, avec priorité à la baisse échantillonnée et aux écarts valeur/PnL.** C'est une priorité d'examen des données uniquement. Action minimale : une période historique bornée avec consolidation documentée des DEX/sous-compte, collatéral et transferts, puis rapprochement des deux snapshots et des événements complets dans leurs unités. Pas de rendement ni de statut d'approbation avant cette preuve.

## `67f7…9ba` — `0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba`

**Périmètre observé.** Mode déclaré `disabled` dans 48 observations d’archives du mode. Les 55 pages fills dédupliquées listent `ETH` et `xyz:DRAM`. `allTime` et `perpAllTime` ont les mêmes deltas, sans démontrer que tous les actifs/dettes/flux sont couverts. Le snapshot spot `raw_observations:25977033` liste USDC mais ne price ni ne consolide les actifs; snapshots DEX ponctuels : `25977291`, `25977351`, `25977352`, `25977353`, `25977407`, `25977408`, `25977409`, `25977410`.

| Horizon | `allTime.pnlHistory` Δ nominal | bornes observées UTC (début → fin) | `accountValueHistory` Δ | pire baisse échantillonnée PnL / valeur |
|---|---:|---|---:|---:|
| 30 j ciblés | −79,747273 | 09-09 23:48:00.037 → 10-11 23:29:25.775 | +2 031,641996 | −1 545,253138 / −15 127,938909 |
| 90 j ciblés | +9 210,549437 | 07-08 23:28:00.016 → 10-11 23:29:25.775 | −6 790,155782 | −6 055,683927 / −15 127,938909 |
| 180 j ciblés | +36 304,350065 | 04-08 22:28:00.022 → 10-11 23:29:25.775 | −7 165,305398 | −6 845,327618 / −51 830,138231 |

Les six buckets mensuels mesurés attribuent +37 557,750310; le résidu net est −1 253,400245 (3,23 % du mouvement brut) et le plus grand mois positif pèse 42,51 % du delta positif. La courbe déclarée se retourne légèrement négative sur 30 j. Les cinq/seize jours d'activité fréquente ne sont pas une couverture continue.

**Contrôle de source sur archives.** Les séries PnL/valeur sont référencées par `raw_observations:25977098`; valeur moins PnL vaut +2 111,389269 sur 30 j, −16 000,705219 sur 90 j et −43 469,655463 sur 180 j. La direction diverge sur 90/180 j; la série de valeur ne confirme pas les gains déclarés. Les 55 pages fills dédupliquées couvrent 4,661 jours contigus avec `page_budget_exhausted` : 25 601 fills, 14 918 ordres inférés et six jours actifs. Fees : 500,041022 USDC (25 601 lignes), couverture insuffisante pour imputer aux horizons. Les pages ledger/funding de l’audit comprennent −1 000 USDC de flux externe, funding −0,426683 en devise DEX non vérifiée (18 événements) et +1,110173 USDC (134 événements). Ces sommes ne prouvent pas la complétude ni n’expliquent les écarts.

**Capital et risque.** Pas de capital moyen, de rendement corrigé des flux, d'exposition historique ni de périmètre externe consolidé. La valeur déclarée baisse sur 90/180 j malgré PnL positif. Le ratio apparent gain/capital ne peut donc pas être estimé proprement depuis l'état actuel.

**Décision : conserver la présélection comme signal historique à vérifier, sans priorité pour une investigation coûteuse tant que les séries PnL et valeur divergent.** Ce n'est pas un rejet de la performance; la série PnL seule est légèrement négative sur 30 j et positive sur 90/180 j, tandis que l'autre série s'oriente à la baisse. Action minimale : d'abord rapprocher une fenêtre historique commune issue des archives (ou un seul intervalle borné ultérieur si les pages sont insuffisantes); ne prolonger l'analyse que si le résidu est expliqué.

## Limites communes et contrôles récents

- Les requêtes fills couvrent respectivement 3,504 j, 4,964 j et 4,661 j sur une cible de 30 j; ni les montants de fees ni les nombres de fills ne sont extrapolés aux horizons plus longs. Les identifiants d'ordres associés aux fills sont une borne inférieure, pas des décisions de trading indépendantes.
- Les flux et fundings rapportés sont les événements classés présents dans les pages archivées. Les pages ne prouvent ni couverture exhaustive des fenêtres des courbes, ni classification de tous les coûts, frais, FX, transferts ou intérêts. Des écritures absentes des pages ne sont pas assimilées à zéro.
- Les huit snapshots DEX et inventaires spot ponctuels décrivent l'état observé, pas l'exposition historique. La relation à des sous-comptes, vaults, collatéral ou hedges externes demeure inconnue et ne peut pas être déclarée inexistante.
- Le contrôle récent conserve sa décision d'origine : les trois dernières valorisations perp archivées étaient âgées d'environ 7 h 34 à 7 h 47 au cutoff, au-delà de l'heure admise, et le dossier comptable du 9 octobre n'avait sélectionné aucune période/scope. Cela bloque une attestation comptable **récente**, sans annuler les courbes historiques décrites ici.
- Pour aucun compte les archives ne permettent un rendement net fiable ou une validation économique globale. Aucun statut de ce document ne déclenche une recherche IA, une collecte fournisseur, une RE ou une allocation de capital.
