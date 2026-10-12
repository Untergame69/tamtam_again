# Fiches de qualification économique — présélections TAMTAM

Cutoff commun : `1791789394195` ms (`2026-10-12T07:16:34.195Z`). Les fiches exploitent le classement archivé du 12 octobre et les observations disponibles au cutoff. Les montants de courbe sont des changements `allTime.pnlHistory` déclarés par le fournisseur, en unités nominales ; ils ne sont pas des rendements nets validés.

La règle de période comptable déjà adoptée reste celle du fichier [`account-qualification-period-policy.json`](../../config/account-qualification-period-policy.json) : période cible de six heures, frontière de début à ±15 minutes, valorisation finale âgée d’au plus une heure, sans interpolation. Les contrôles sur archives arrêtent les trois dossiers avant le calcul économique : dernière valorisation perp à plus d’une heure du cutoff. Aucune donnée postérieure au cutoff n’est utilisée.

La concentration mensuelle reprend le seuil de complétude historique : le résidu net non attribué peut peser jusqu’à 10 % du mouvement brut mesuré (variations attribuées en valeur absolue plus résidu absolu). Ce seuil facilite une synthèse descriptive; il ne prouve pas la couverture temporelle exhaustive. Les résidus sont donc affichés pour chaque compte.

## a880…4ee — `0xa880d6cc607a05ea617307ab3b0d335e8d8424ee`

**Décision : présélection descriptive; qualification économique en attente.** Mode déclaré `disabled`.

| Indicateur archivé au cutoff | Preuve |
|---|---:|
| Fills observés / jours UTC actifs, 30 j | 178 438 / 5 |
| Ordres distincts issus des fills (borne inférieure) | 133 925 |
| Marchés / couverture de requête fills | 18 / 3,504 jours; `page_budget_exhausted` et `pagination_exhausted` |
| PnL déclaré 30 / 90 / 180 j | +16 094,867590 / +56 403,542786 / +128 249,465591 |
| Cohérence mensuelle sur 180 j | 6/6 buckets mesurés; somme attribuée +117 685,689722; résidu +10 563,775869; part brute 8,24 %; plus grand mois positif 32,40 % |
| Flux externes classés observés sur 30 j | −23 000 USDC (2 événements); couverture incomplète |
| Funding observé, scope inconnu | +1,695495 USDC (2 141 événements) |
| Dernière valorisation perp exploitable | `1791761787533`, preuve `raw_observations:25999670`; retard au cutoff : 7 h 40 min 06 s |

**Lacunes précises.** Le volume élevé est un nombre de fills, et les 133 925 identifiants d’ordres dérivés des fills ne mesurent ni les ordres annulés ni les décisions indépendantes. La requête fills ne couvre que 3,504 jours contigus dans les archives sélectionnées; l’activité observée sur cinq jours UTC est une borne inférieure, pas une couverture continue de 30 jours. Il manque une valorisation finale fraîche et une frontière de début dans la tolérance de six heures, une couverture ledger/funding démontrée, la conversion et l’attribution complète des coûts, les soldes spot évalués, et l’inventaire réconcilié des onze DEX observés. Les couvertures de sous-comptes et de hedges externes restent inconnues. Le dossier du 9 octobre (`ACCOUNTING-TRANCHE-RESULT-20261009.json`) indiquait déjà `awaiting_recent_valuation`, aucune période choisie, zéro scope rapproché et `economic_validation=false`.

## be504…77b — `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b`

**Décision : présélection descriptive; qualification économique en attente.** Mode déclaré `portfolioMargin`; un sous-compte est observé dans l’inventaire archivé.

| Indicateur archivé au cutoff | Preuve |
|---|---:|
| Fills observés / jours UTC actifs, 30 j | 891 / 5 |
| Ordres distincts issus des fills (borne inférieure) | 115 |
| Marchés / couverture de requête fills | 9 / 4,964 jours; pagination marquée terminée sur les pages retenues, sans preuve de rétention API |
| PnL déclaré 30 / 90 / 180 j | +193 867,762938 / +266 983,235321 / +365 968,587423 |
| Cohérence mensuelle sur 180 j | 6/6 buckets mesurés; somme attribuée +302 966,665881; résidu +63 001,921542; part brute 6,09 %; plus grand mois positif 39,16 % |
| Flux externes classés observés sur 30 j | −2 000 HYPE et −55 990 USDC (5 événements); la couverture des flux demeure inconnue |
| Funding observé | −320,204952 en devise DEX non vérifiée (266 événements); +6,589680 USDC (28 événements) |
| Dernière valorisation perp exploitable | `1791762100410`, preuve `raw_observations:26016086`; retard au cutoff : 7 h 34 min 53 s |

**Lacunes précises.** Le mode `portfolioMargin` et le sous-compte interdisent d’additionner les equities par DEX comme s’il s’agissait de capital indépendant. Il faut une valorisation consolidée du collatéral et des sous-comptes, une valorisation finale fraîche et une frontière de début conforme à la règle six heures. Les marchés spot/HIP-3, unités de funding et transferts doivent être rapprochés au périmètre consolidé; le HYPE observé ne peut être additionné à l’USDC sans preuve de conversion. Les coûts, la complétude du ledger, les couvertures de rétention des fills et les positions/hedges externes restent non établis. Le dossier du 9 octobre avait `awaiting_recent_valuation`, aucune période choisie, zéro scope rapproché et `economic_validation=false`.

## 67f7…9ba — `0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba`

**Décision : présélection descriptive; qualification économique en attente.** Mode déclaré `disabled`; marchés observés `ETH` et `xyz:DRAM`.

| Indicateur archivé au cutoff | Preuve |
|---|---:|
| Fills observés / jours UTC actifs, 30 j | 25 601 / 6 |
| Ordres distincts issus des fills (borne inférieure) | 14 918 |
| Couverture de requête fills | 4,661 jours; `page_budget_exhausted` et `pagination_exhausted` |
| PnL déclaré 30 / 90 / 180 j | −79,747273 / +9 210,549437 / +36 304,350065 |
| Cohérence mensuelle sur 180 j | 6/6 buckets mesurés; somme attribuée +37 557,750310; résidu −1 253,400245; part brute 3,23 %; plus grand mois positif 42,51 % |
| Flux externes classés observés sur 30 j | −1 000 USDC (3 événements); couverture incomplète |
| Funding observé, scope inconnu | −0,426683 en devise DEX non vérifiée (18 événements); +1,110173 USDC (134 événements) |
| Dernière valorisation perp exploitable | `1791761368449`, preuve `raw_observations:25977286`; retard au cutoff : 7 h 47 min 05 s |

**Lacunes précises.** La baisse déclarée récente de 30 jours doit rester visible face aux horizons 90/180 jours positifs; les flux et le funding observés ne suffisent pas à l’expliquer. La requête fills ne couvre que 4,661 jours, avec pagination budgétée et rétention non établie. Il manque une période comptable fraîche de six heures, les valorisations de tous les DEX concernés, la couverture et classification complète des flux/frais, l’évaluation des actifs spot, et la preuve de complétude du ledger. Le dossier du 9 octobre avait `awaiting_recent_valuation`, aucune période choisie, zéro scope rapproché et `economic_validation=false`.

## Sources, règle de lecture et décision

- Le classement source figé reste [`historical-selection-20261012`](historical-selection-20261012/report.md); la reconstruction corrigée et le même classement sont dans [`historical-selection-20261012-f1-f4`](historical-selection-20261012-f1-f4/report.md). Les trois lignes gardent le statut `credible_deep_dive_candidate`.
- Le dossier comptable précédent est conservé dans [`ACCOUNTING-TRANCHE-RESULT-20261009.json`](ACCOUNTING-TRANCHE-RESULT-20261009.json); son cutoff est `1791527290652` ms. L’inspection des valorisations archivées au nouveau cutoff réapplique la politique existante et n’en assouplit pas les seuils.
- Les événements de flux listés sont les événements classés présents dans les observations disponibles au cutoff. Les lacunes de couverture restent ouvertes; aucune absence d’événement n’est assimilée à zéro économique.
- `economic_validation=false` pour les trois comptes; aucun statut n’autorise une recherche IA, une RE ou une allocation de capital. Les nombres de fills, courbes positives et seuils de concentration ne remplacent pas les preuves manquantes.
