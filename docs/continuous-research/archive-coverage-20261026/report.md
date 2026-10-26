# Couverture d’archives — inventaire borné — 2026-10-26

Fenêtre d’observation : **[2026-10-15T15:00:00.000+00:00, 2026-10-26T13:30:21.970+00:00)**. Les dates sont en UTC; l’instant de disponibilité locale est `raw_observations.observed_at`.

## Périmètre et preuve

Rapport de présélection : `/home/Untergame/tamtam_again/data/historical-selection/current/report.md` (SHA-256 `f39b852be6a9d271d5e1e087a3c7b8acb6250956509f1c88e8f28622f55f137d`). Base lue en mode SQLite read-only : `/home/Untergame/tamtam_again/data/tamtam.sqlite3`.
Le rapport source contenait 14 comptes présélectionnés. Le registre compte 10 comptes `tracked`; 424 comptes ont un curseur d’historique REST. Détail de cette mission : 23 comptes après exclusion de 1 compte(s) protégé(s).
Plafonds : 300 pages fills par compte; 25000 pages au total (7450 lues), 250000 fills décodés par compte, 20000 observations globales récentes par canal de carnet.
La fenêtre commence exactement à la fin événementielle du bilan précédent, 2026-10-15T15:00:00Z; elle ne recouvre pas sa fenêtre 67f7/ETH déjà utilisée.
Les études descriptives déjà utilisées sur a880, 67f7 et be504 (6–11 octobre) ainsi que la résolution bornée 67f7/ETH du 14–15 octobre sont explicitement conservées comme preuves historiques dans `global_period_policy.historical_studies`; aucune n’est requalifiée vierge.
Les comptes protégés sont listés uniquement par leur référence d’adresse, sans lecture de leurs charges utiles. Le carnet n’a pas d’index dont la première clé est le marché : la période de carnet est donc un échantillon global récent et plafonné, pas un inventaire exhaustif de la fenêtre.

## Résumé des éléments décodés

492,165 fills uniques (482,963 REST, 9,202 WebSocket) sur 271 couples avec activité. Champ de frais présent sur 492,165/492,165 fills; 11,005 lignes de funding observées sur 115 couples. Déduplication des seules identités de fills : 264,558 répétitions exactes, 0 identités conflictuelles; enveloppes `events[]` : 0.
Plafond pages atteint pour 8 comptes; plafond événements atteint pour 0; budget global épuisé : 0. Un hit de plafond classe les portions non projetées `present_not_exported`; sans preuve locale admissible, zéro décodé reste `absent` dans ce scan seulement.
Le contrôle de bornes d’état donne 145 correspondances arithmétiques, 83 écarts ou intervalles incomplets, 196 couples sans deux snapshots. Cela ne prouve aucune position cohérente complète.
Dans l’échantillon de carnets, des snapshots strictement antérieurs et déjà disponibles dans les 30 s du reçu fill correspondent à 944 fills WebSocket pour BBO et 1012 pour L2; les deux canaux sont nécessaires à un rejeu avec carnet.

Santé des flux : 74 sessions reliées à des frames de fills WebSocket, 34,842 événements santé décodés, 0 intervalles heartbeat >65 s et 73 déconnexions explicites dans la fenêtre; plafond global atteint : False. Cette association prouve une activité de flux pour ces sessions, sans preuve d’ACK d’abonnement par compte.

### Meilleures pistes descriptives observées

- `0xbb160cb61e694570f9d570f9fcde7c61dd2143ad` / `BTC` : 107887 fills; événements [1792076404981, 1792969023003], disponibilité locale [1792079440133, 1792969292161].
- `0x706bb519b05b7dc01d048af9a5e29d1ef5d6d9e3` / `xyz:SKHX` : 44816 fills; événements [1792241755872, 1792947585222], disponibilité locale [1792282723796, 1792947694353].
- `0xa62b923a112d50d03e1e096bbd53422490dac104` / `BTC` : 37985 fills; événements [1792197295824, 1792965404866], disponibilité locale [1792283549583, 1792969048714].
- `0x223537ac9a856c31f4043e86ced86bb29f06653e` / `kPEPE` : 29178 fills; événements [1792413784130, 1793020549975], disponibilité locale [1792454993303, 1793020626253].
- `0x223537ac9a856c31f4043e86ced86bb29f06653e` / `WLD` : 29062 fills; événements [1792413671432, 1793020591492], disponibilité locale [1792454993303, 1793020626253].

### Meilleures pistes de rejeu follower observées

- `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` / `@107` : 375 fills; événements [1793021189462, 1793021418115], disponibilité locale [1793021189805, 1793021420444].
- `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` / `HYPE` : 292 fills; événements [1793021188634, 1793021414961], disponibilité locale [1793021189023, 1793021417445].
- `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` / `SUI` : 96 fills; événements [1793021194349, 1793021412366], disponibilité locale [1793021194841, 1793021414674].
- `0x7fdafde5cfb5465924316eced2d3715494c517d1` / `XMR` : 181 fills; événements [1793020667627, 1793021354060], disponibilité locale [1793020668094, 1793021355034].
- `0x7fdafde5cfb5465924316eced2d3715494c517d1` / `ZEC` : 66 fills; événements [1793020666633, 1793021409136], disponibilité locale [1793020666960, 1793021411399].
Ces listes classent la quantité observée et le recouvrement technique. Elles ne mesurent ni performance ni complétude; les bornes par couple figurent dans le manifeste.

## Inventaire de collecte

| Mesure | Valeur | Ce que cela prouve |
|---|---:|---|
| Comptes avec curseur REST | 424 | Au moins un curseur archivé, pas continuité ni complétude de marché |
| Cibles de recherche compte/marché | 302 | Registre de cibles, pas preuve de fills |
| Plans réels / périodes libérées / holdouts consommés / évaluations | 12 / 0 / 0 / 0 | Compteurs aux tables opérationnelles, ne libèrent aucun intervalle |

### Curseurs d’historique observés

| Endpoint | Statut | Comptes |
|---|---|---:|
| `userFillsByTime` | `pagination_exhausted` | 423 |
| `userFillsByTime` | `saturated_timestamp_unresolvable` | 1 |
| `userFunding` | `pagination_exhausted` | 424 |
| `userNonFundingLedgerUpdates` | `pagination_exhausted` | 424 |

## Couples détaillés

| Compte | Marché | Fills uniques observés | Provenance | Carnet | Position |
|---|---|---:|---|---|---|
| `0x020ca66c30bec2c4fe3861a94e4db4a498a35872` | `BTC` | 0 | aucun fill décodé | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x020ca66c30bec2c4fe3861a94e4db4a498a35872` | `ENA` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x020ca66c30bec2c4fe3861a94e4db4a498a35872` | `ETH` | 1382 | websocket:1382 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x020ca66c30bec2c4fe3861a94e4db4a498a35872` | `HYPE` | 0 | aucun fill décodé | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0x020ca66c30bec2c4fe3861a94e4db4a498a35872` | `PUMP` | 0 | aucun fill décodé | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `@151` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `@699` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `INJ` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `NEAR` | 0 | aucun fill décodé | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `PONS` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `xyz:AVGO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `xyz:CBRS` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `xyz:DRAM` | 3321 | websocket:3321 | BBO échantillonné [1793021176059, 1793021421964] | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `xyz:INTC` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x30afce2f6842bf183c7e3fe7162e279ff0b6393e` | `xyz:MU` | 0 | aucun fill décodé | BBO échantillonné [1793021176307, 1793021421954] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `@107` | 375 | websocket:375 | BBO échantillonné [1793021176819, 1793021421970] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `@162` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `BNB` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `BTC` | 0 | aucun fill décodé | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `DOGE` | 51 | websocket:51 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `ETH` | 0 | aucun fill décodé | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `FARTCOIN` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `HYPE` | 292 | websocket:292 | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `INJ` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `LINK` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `LIT` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `PUMP` | 0 | aucun fill décodé | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `SOL` | 0 | aucun fill décodé | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `SUI` | 96 | websocket:96 | BBO échantillonné [1793021176820, 1793021421939] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `WLD` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `XRP` | 16 | websocket:16 | BBO échantillonné [1793021176800, 1793021421941] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `ZEC` | 0 | aucun fill décodé | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `xyz:GOLD` | 0 | aucun fill décodé | BBO échantillonné [1793021182558, 1793021420937] | unknown |
| `0x5b5d51203a0f9079f8aeb098a6523a13f298c060` | `xyz:SILVER` | 0 | aucun fill décodé | BBO échantillonné [1793021176068, 1793021421957] | unknown |
| `0x77ddcc4b6440b3a32b7802f053105c2fad3ae0e9` | `ETH` | 689 | websocket:689 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `BTC` | 0 | aucun fill décodé | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `DOGE` | 6 | websocket:6 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `ETH` | 12 | websocket:12 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `FARTCOIN` | 1 | websocket:1 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `GRAM` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `HYPE` | 10 | websocket:10 | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `NEAR` | 0 | aucun fill décodé | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `SOL` | 1 | websocket:1 | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `XMR` | 181 | websocket:181 | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `XRP` | 1 | websocket:1 | BBO échantillonné [1793021176800, 1793021421941] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `ZEC` | 66 | websocket:66 | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `kPEPE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:BRENTOIL` | 0 | aucun fill décodé | BBO échantillonné [1793021176327, 1793021421960] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:CL` | 0 | aucun fill décodé | BBO échantillonné [1793021176069, 1793021421958] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:CRCL` | 8 | websocket:8 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:GOLD` | 23 | websocket:23 | BBO échantillonné [1793021182558, 1793021420937] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:GOOGL` | 1 | websocket:1 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:MU` | 0 | aucun fill décodé | BBO échantillonné [1793021176307, 1793021421954] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:NVDA` | 0 | aucun fill décodé | BBO échantillonné [1793021176305, 1793021421950] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:SILVER` | 0 | aucun fill décodé | BBO échantillonné [1793021176068, 1793021421957] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:SKHX` | 154 | websocket:154 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:SKHY` | 0 | aucun fill décodé | BBO échantillonné [1793021176060, 1793021421966] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:SNDK` | 0 | aucun fill décodé | BBO échantillonné [1793021176067, 1793021421955] | unknown |
| `0x7fdafde5cfb5465924316eced2d3715494c517d1` | `xyz:SPCX` | 1 | websocket:1 | BBO échantillonné [1793021176328, 1793021421965] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `@107` | 0 | aucun fill décodé | BBO échantillonné [1793021176819, 1793021421970] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `@142` | 0 | aucun fill décodé | BBO échantillonné [1793021176329, 1793021421968] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `BTC` | 0 | aucun fill décodé | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `ETH` | 132 | websocket:132 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `FARTCOIN` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `HYPE` | 0 | aucun fill décodé | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `MON` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `PUMP` | 0 | aucun fill décodé | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `VVV` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `XMR` | 329 | websocket:329 | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `ZEC` | 0 | aucun fill décodé | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `ZRO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:BE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:CRCL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:GOOGL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:INTC` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:META` | 0 | aucun fill décodé | BBO échantillonné [1793021176065, 1793021421952] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:MSFT` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:MSTR` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:MU` | 0 | aucun fill décodé | BBO échantillonné [1793021176307, 1793021421954] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:NBIS` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:NVDA` | 0 | aucun fill décodé | BBO échantillonné [1793021176305, 1793021421950] | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:RKLB` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x880ac484a1743862989a441d6d867238c7aa311c` | `xyz:TSLA` | 0 | aucun fill décodé | BBO échantillonné [1793021176322, 1793021421949] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `@306` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `AAVE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `AERO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `ASTER` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `BTC` | 33 | websocket:33 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `CASHCAT` | 68 | websocket:68 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `CC` | 4 | websocket:4 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `EIGEN` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `ENA` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `ETH` | 54 | websocket:54 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `FARTCOIN` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `GRAM` | 40 | websocket:40 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `GRASS` | 264 | websocket:264 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `HYPE` | 0 | aucun fill décodé | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `JTO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `KAITO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `LINK` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `LIT` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `MON` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `NEAR` | 0 | aucun fill décodé | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `NIL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `ONDO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `PONS` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `PUMP` | 0 | aucun fill décodé | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `SKR` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `SOL` | 0 | aucun fill décodé | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `SUI` | 0 | aucun fill décodé | BBO échantillonné [1793021176820, 1793021421939] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `TAO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `UNI` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `USELESS` | 64 | websocket:64 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `VVV` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `W` | 16 | websocket:16 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `WLD` | 2 | websocket:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `XMR` | 9 | websocket:9 | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `XPL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `XRP` | 0 | aucun fill décodé | BBO échantillonné [1793021176800, 1793021421941] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `ZEC` | 0 | aucun fill décodé | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `ZRO` | 46 | websocket:46 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x936cf4fb95c30ce83f658b5bbb247e4bb381bb0f` | `xyz:CL` | 0 | aucun fill décodé | BBO échantillonné [1793021176069, 1793021421958] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `@107` | 326 | websocket:326 | BBO échantillonné [1793021176819, 1793021421970] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `AERO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `APE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `ASTER` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `AVAX` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `BTC` | 0 | aucun fill décodé | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `DOGE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `ENA` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `ETH` | 0 | aucun fill décodé | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `FARTCOIN` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `GRAM` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `HYPE` | 249 | websocket:249 | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `INJ` | 22 | websocket:22 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `LINK` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `LIT` | 73 | websocket:73 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `MON` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `NEAR` | 27 | websocket:27 | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `ONDO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `PUMP` | 0 | aucun fill décodé | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `PURR` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `SOL` | 0 | aucun fill décodé | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `SUI` | 0 | aucun fill décodé | BBO échantillonné [1793021176820, 1793021421939] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `TAO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `UNI` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `VVV` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `WLD` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `XPL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `XRP` | 0 | aucun fill décodé | BBO échantillonné [1793021176800, 1793021421941] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `ZEC` | 0 | aucun fill décodé | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `ZRO` | 1 | websocket:1 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `xyz:GOLD` | 0 | aucun fill décodé | BBO échantillonné [1793021182558, 1793021420937] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `xyz:SILVER` | 0 | aucun fill décodé | BBO échantillonné [1793021176068, 1793021421957] | unknown |
| `0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36` | `xyz:STRC` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `2Z` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `@260` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `@272` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `@334` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `@700` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `CASHCAT` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `ENA` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `ETH` | 0 | aucun fill décodé | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `FARTCOIN` | 327 | websocket:327 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `FIL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `HYPE` | 0 | aucun fill décodé | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `JTO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `LIT` | 58 | websocket:58 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `MON` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `NEAR` | 0 | aucun fill décodé | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `PONS` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `PURR` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `SOL` | 0 | aucun fill décodé | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `TAO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `UNI` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `VVV` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `WLD` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `XMR` | 0 | aucun fill décodé | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `XPL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `ZEC` | 0 | aucun fill décodé | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `kPEPE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:AVGO` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:BE` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:DELL` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:EWZ` | 69 | websocket:69 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:GOOGL` | 30 | websocket:30 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:INTC` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:JPY` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:MINIMAX` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:MRNA` | 18 | websocket:18 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:NET` | 68 | websocket:68 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:NFLX` | 66 | websocket:66 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:SHAZ` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:SILVER` | 0 | aucun fill décodé | BBO échantillonné [1793021176068, 1793021421957] | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:SKHX` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xe928927c0a4086909a753a6a85a5f9296d9826e8` | `xyz:ZHIPU` | 120 | websocket:120 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `@260` | 81 | rest:81 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `AERO` | 12 | rest:12 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `CRV` | 4 | rest:4 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `ICP` | 81 | rest:81 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `NIL` | 89 | rest:89 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `PUMP` | 176 | rest:176 | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `PURR` | 61 | rest:61 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `STBL` | 2 | rest:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `XMR` | 507 | rest:507 | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `XPL` | 75 | rest:75 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `kPEPE` | 24 | rest:24 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `para:PAPER` | 43 | rest:43 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `xyz:EWZ` | 138 | rest:138 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `xyz:NFLX` | 20 | rest:20 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa8b9b8c770d11c20b50aa228755c658a188f6098` | `xyz:NVDA` | 4 | rest:4 | BBO échantillonné [1793021176305, 1793021421950] | unknown |
| `0x706bb519b05b7dc01d048af9a5e29d1ef5d6d9e3` | `BTC` | 14627 | rest:14627 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x706bb519b05b7dc01d048af9a5e29d1ef5d6d9e3` | `xyz:SKHX` | 44816 | rest:44816 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa62b923a112d50d03e1e096bbd53422490dac104` | `BTC` | 37985 | rest:37985 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0xa62b923a112d50d03e1e096bbd53422490dac104` | `ETH` | 24056 | rest:24056 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `@230` | 13 | rest:13 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `@260` | 91 | rest:91 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `@719` | 10 | rest:10 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `@867` | 27 | rest:27 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `ETH` | 3 | rest:3 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `io:IONQ` | 6 | rest:6 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `io:PRL` | 500 | rest:500 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `mkts:BVIV` | 17 | rest:17 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:10Y` | 35 | rest:35 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:ANSEM` | 2 | rest:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:DRV` | 6 | rest:6 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:MELI` | 88 | rest:88 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:PAPER` | 38 | rest:38 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:TREAD` | 9 | rest:9 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `para:TTWO` | 7 | rest:7 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `xyz:GIGADEV` | 5 | rest:5 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x9909c128feea2b6046026d75c0a29451d3427aa9` | `xyz:JIO` | 21 | rest:21 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xa775d1bd91ee2cc4cae6113e5fd9c0c17b355277` | `SOL` | 20947 | rest:20947 | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `ANIME` | 353 | rest:353 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `BTC` | 2335 | rest:2335 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `ETH` | 997 | rest:997 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `SOPH` | 123 | rest:123 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `xyz:GOLD` | 387 | rest:387 | BBO échantillonné [1793021182558, 1793021420937] | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `xyz:SHAZ` | 48 | rest:48 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `xyz:SILVER` | 0 | aucun fill décodé | BBO échantillonné [1793021176068, 1793021421957] | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `xyz:SKHY` | 5 | rest:5 | BBO échantillonné [1793021176060, 1793021421966] | unknown |
| `0xf5d889840ff183c72b0b57aac895303eee76f226` | `xyz:XYZ100` | 2951 | rest:2951 | BBO échantillonné [1793021176304, 1793021421947] | unknown |
| `0xbb160cb61e694570f9d570f9fcde7c61dd2143ad` | `BTC` | 107887 | rest:107887 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `@719` | 544 | rest:544 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `CASHCAT` | 125 | rest:125 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `ENA` | 2 | rest:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `FARTCOIN` | 294 | rest:294 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `LIT` | 647 | rest:647 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `NEAR` | 445 | rest:445 | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `PUMP` | 74 | rest:74 | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `PURR` | 337 | rest:337 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `PURR/USDC` | 45 | rest:45 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `VVV` | 539 | rest:539 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `XMR` | 217 | rest:217 | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `XPL` | 128 | rest:128 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `ZEC` | 110 | rest:110 | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `io:ANTH` | 108 | rest:108 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `io:PRL` | 1231 | rest:1231 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `mkts:BVIV` | 271 | rest:271 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `para:ANSEM` | 20 | rest:20 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `para:CIFR` | 41 | rest:41 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `para:PAPER` | 92 | rest:92 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `para:TREAD` | 443 | rest:443 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `para:UNITREE` | 54 | rest:54 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:BB` | 375 | rest:375 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:CVX` | 15 | rest:15 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:EWZ` | 285 | rest:285 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:HO` | 14 | rest:14 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:IBM` | 8 | rest:8 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:JIO` | 66 | rest:66 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:LRCX` | 2 | rest:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:META` | 20 | rest:20 | BBO échantillonné [1793021176065, 1793021421952] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:MINIMAX` | 89 | rest:89 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:NBIS` | 4 | rest:4 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:NFLX` | 5 | rest:5 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:SOFTBANK` | 1209 | rest:1209 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:SPCX` | 10 | rest:10 | BBO échantillonné [1793021176328, 1793021421965] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:STRC` | 2 | rest:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:TSLA` | 39 | rest:39 | BBO échantillonné [1793021176322, 1793021421949] | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:UMC` | 7 | rest:7 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x37c2a0912e44ea4c293866dfa3735d58ef1ecb4f` | `xyz:UNITREE` | 74 | rest:74 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `AERO` | 8390 | rest:8390 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `ASTER` | 2178 | rest:2178 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `BNB` | 6311 | rest:6311 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `CFX` | 3680 | rest:3680 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `CRV` | 10220 | rest:10220 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `DOGE` | 7235 | rest:7235 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `ENA` | 8338 | rest:8338 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `ETC` | 2955 | rest:2955 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `HBAR` | 9455 | rest:9455 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `IO` | 7785 | rest:7785 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `KAITO` | 3906 | rest:3906 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `LTC` | 8096 | rest:8096 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `VIRTUAL` | 6906 | rest:6906 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `WLD` | 29062 | rest:29062 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `WLFI` | 5701 | rest:5701 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `ZK` | 4578 | rest:4578 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `kBONK` | 2851 | rest:2851 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x223537ac9a856c31f4043e86ced86bb29f06653e` | `kPEPE` | 29178 | rest:29178 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `@1118` | 74 | rest:74 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `@113` | 4 | rest:4 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `@242` | 12 | rest:12 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `io:PRL` | 578 | rest:578 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `para:ANSEM` | 9 | rest:9 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `para:TREAD` | 13 | rest:13 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `xyz:BOT` | 9 | rest:9 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `xyz:CAMBRICON` | 11 | rest:11 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `xyz:HO` | 17 | rest:17 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `xyz:JIO` | 442 | rest:442 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `xyz:KIOXIA` | 63 | rest:63 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x74674447ab891ac45fab82b0dfa3ad8b2f3bd5d6` | `xyz:SOFTBANK` | 104 | rest:104 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71730` | 28 | rest:28 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71731` | 39 | rest:39 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71741` | 152 | rest:152 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71751` | 63 | rest:63 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71770` | 46 | rest:46 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71771` | 25 | rest:25 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71780` | 3 | rest:3 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71781` | 126 | rest:126 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71801` | 11 | rest:11 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71811` | 26 | rest:26 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71860` | 31 | rest:31 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `#71861` | 21 | rest:21 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `@107` | 481 | rest:481 | BBO échantillonné [1793021176819, 1793021421970] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `@188` | 570 | rest:570 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `@272` | 12 | rest:12 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `@496` | 1471 | rest:1471 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `BTC` | 2959 | rest:2959 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `ETH` | 4975 | rest:4975 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `HYPE` | 9656 | rest:9656 | BBO échantillonné [1793021176298, 1793021421943] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `NEAR` | 6577 | rest:6577 | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `ONDO` | 528 | rest:528 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `PUMP` | 3769 | rest:3769 | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `SOL` | 2377 | rest:2377 | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `UNI` | 856 | rest:856 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `WLD` | 4315 | rest:4315 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `ZEC` | 11 | rest:11 | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x98eadc9dc42156f68cbf7d007d084bbf142bc0e3` | `xyz:DRAM` | 18 | rest:18 | BBO échantillonné [1793021176059, 1793021421964] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `ADA` | 76 | rest:76 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `BTC` | 842 | rest:842 | BBO échantillonné [1793021176062, 1793021421935] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `ETH` | 479 | rest:479 | BBO échantillonné [1793021176063, 1793021421937] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `ICP` | 44 | rest:44 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `JUP` | 937 | rest:937 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `NEAR` | 235 | rest:235 | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `PUMP` | 0 | aucun fill décodé | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `SOL` | 232 | rest:232 | BBO échantillonné [1793021176314, 1793021421938] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `VVV` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `WLD` | 152 | rest:152 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `XRP` | 192 | rest:192 | BBO échantillonné [1793021176800, 1793021421941] | unknown |
| `0x77eeda199553e33b246e4b4666849b9ad0972902` | `ZEC` | 309 | rest:309 | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `@107` | 2 | rest:2 | BBO échantillonné [1793021176819, 1793021421970] | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `AERO` | 133 | rest:133 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ALT` | 88 | rest:88 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ANIME` | 15 | rest:15 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `APT` | 83 | rest:83 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ARB` | 36 | rest:36 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `AVNT` | 81 | rest:81 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `AZTEC` | 301 | rest:301 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `BOME` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `CHIP` | 601 | rest:601 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `COMP` | 368 | rest:368 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `CRV` | 338 | rest:338 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `DYM` | 30 | rest:30 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `EIGEN` | 94 | rest:94 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ENA` | 48 | rest:48 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ETC` | 26 | rest:26 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `FARTCOIN` | 58 | rest:58 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `FIL` | 169 | rest:169 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `GRASS` | 363 | rest:363 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `GRIFFAIN` | 7 | rest:7 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `INJ` | 402 | rest:402 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `JUP` | 17 | rest:17 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `LIT` | 316 | rest:316 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `MEGA` | 94 | rest:94 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `MON` | 200 | rest:200 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `MOODENG` | 40 | rest:40 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `MORPHO` | 606 | rest:606 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `NEAR` | 234 | rest:234 | BBO échantillonné [1793021176297, 1793021421942] | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `NIL` | 1418 | rest:1418 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `NXPC` | 112 | rest:112 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `PENDLE` | 242 | rest:242 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `PENGU` | 122 | rest:122 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `PONS` | 147 | rest:147 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `PUMP` | 268 | rest:268 | BBO échantillonné [1793021176299, 1793021421944] | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `PYTH` | 446 | rest:446 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `REZ` | 30 | rest:30 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `RUNE` | 64 | rest:64 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `SAND` | 18 | rest:18 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `SOPH` | 64 | rest:64 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `SPX` | 201 | rest:201 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `STBL` | 17 | rest:17 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `STRK` | 1450 | rest:1450 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `STX` | 2 | rest:2 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `SYRUP` | 36 | rest:36 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `TIA` | 162 | rest:162 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `USELESS` | 414 | rest:414 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `VVV` | 980 | rest:980 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `WCT` | 25 | rest:25 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `XMR` | 217 | rest:217 | BBO échantillonné [1793021176064, 1793021421441] | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ZEC` | 21 | rest:21 | BBO échantillonné [1793021176301, 1793021421946] | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ZK` | 58 | rest:58 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ZORA` | 51 | rest:51 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `ZRO` | 857 | rest:857 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:AAOI` | 133 | rest:133 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:EWZ` | 52 | rest:52 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:HO` | 212 | rest:212 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:IREN` | 72 | rest:72 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:JIO` | 33 | rest:33 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:KR200` | 77 | rest:77 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:MRNA` | 31 | rest:31 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:NET` | 41 | rest:41 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:OURA` | 0 | aucun fill décodé | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:PURRDAT` | 120 | rest:120 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0x3895d155b005191686476a39580d43258a518e46` | `xyz:SOXL` | 26 | rest:26 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `@107` | 23 | rest:23 | BBO échantillonné [1793021176819, 1793021421970] | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `CASHCAT` | 38 | rest:38 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `PONS` | 28 | rest:28 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `io:PRL` | 314 | rest:314 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `para:VST` | 25 | rest:25 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `xyz:ASML` | 708 | rest:708 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `xyz:CRWV` | 206 | rest:206 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `xyz:INTC` | 51 | rest:51 | BBO non retrouvé dans l’échantillon borné | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `xyz:SP500` | 7 | rest:7 | BBO échantillonné [1793021176826, 1793021421961] | unknown |
| `0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b` | `xyz:TSLA` | 86 | rest:86 | BBO échantillonné [1793021176322, 1793021421949] | unknown |

## Interprétation par question

- **Descriptif** : les couples avec fills décodés, bornes événement/réception et références REST peuvent soutenir une description de l’activité observée. REST et pages agrégées ne prouvent pas que tous les fills sont conservés. Frais et funding doivent rester des champs observés, pas une comptabilité complète.
- **Rejeu d’un suivi** : seules des lignes `websocket` portent une disponibilité locale de flux utilisateur. Une réponse REST arrivée après l’événement ne reconstitue pas le signal de suivi. Les correspondances de carnet de l’échantillon borné ne prouvent pas encore un chemin complet exploitable.
- **Interruptions/récupération** : les preuves de santé sont jointes aux sessions observées sur les fills WebSocket; les intervalles heartbeat dépassant 65 s et les déconnexions explicites sont comptés séparément. La session n’archive pas l’ACK userFills par compte, et les sessions sans fill visible ne sont pas attribuables à un compte. Les trous peuvent refléter interruption ou export manquant; leur cause ne se déduit pas du seul silence.
- **Règle autonome** : aucune règle n’est définie par ce livrable; aucun résultat ne permet une étude économique autonome.
- **Positions** : le delta signé des fills ne fixe ni position initiale, ni exposition simultanée, ni continuité. `coherent_position_proven=false` tant que les deux bornes d’état et l’exhaustivité des fills ne sont pas établies.
- **Périodes** : les fenêtres issues des plans sont reportées comme réservées/utilisées; aucune période n’est libérée. Les données collectées depuis une pause ne sont pas requalifiées vierges.

## Limites de récupération et catégories

`absent` signifie seulement qu’aucun élément admissible n’a été décodé dans la fenêtre et les bornes de ce scan. `present_not_exported` signifie que le canal ou la référence existe mais que le plafond a empêché une projection complète. `reconciliation_missing` correspond à des fills/pages sans rapprochement de cotation ou d’état. `calculation_missing` désigne une métrique qui n’a pas été calculée. `unrecoverable` est réservé aux limites contractuelles de l’API ou à une frontière d’archive non récupérable; l’absence locale seule ne suffit pas.
La documentation API locale et [le contrat officiel Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) fixent `userFillsByTime` aux 10 000 dernières exécutions et 2 000 par réponse : un préfixe plus ancien absent de la rétention est irrécupérable par cet endpoint; pagination réussie ne le restaure pas. Un curseur `saturated_timestamp_unresolvable` indique aussi une frontière non résolue. Un intervalle cohérent en fills n’est pas un historique complet. Voir TAMTAM_AGAIN-A-1 et le manifeste pour le compte/cursor concernés.

## Reproduction

```sh
PYTHONPATH=src /home/Untergame/tamtam_again/.venv/bin/python scripts/archive-coverage.py \
  --db /home/Untergame/tamtam_again/data/tamtam.sqlite3 \
  --selection-report /home/Untergame/tamtam_again/data/historical-selection/current/report.md \
  --since 2026-10-15T15:00:00.000+00:00 \
  --cutoff 2026-10-26T13:30:21.970+00:00 \
  --max-accounts 64 --max-pages-per-account 300 --max-total-pages 25000 \
  --max-events-per-account 250000 --max-book-rows-per-endpoint 20000 \
  --output-dir docs/continuous-research/archive-coverage-20261026
```

Aucun changement de service, quota, autorisation ou base n’est inclus dans ce livrable.
