# Proposition d’admission à la recherche descriptive — 26 octobre 2026

Cutoff commun : `1793009400000` ms (`2026-10-26T10:10:00+00:00`). Période de question : `[cutoff − 30 jours, cutoff]`. Réseau : `hyperliquid-mainnet`.

## Décision de portée

Inventaire du screening historique `historical-curves-v2.0` : **2533** décisions. Admissibles à une étude descriptive : **22** ; à approfondir : **320** ; différés : **2190** ; exclus avant lecture : **1**.

Cette proposition évalue une question descriptive, pas une rentabilité. Elle ne change aucun état historique, n’attribue jamais `economic_validation=true` et n’autorise ni IA, collecte, paper, moteur, quota ou capital. L’autorisation de ressources reste une décision distincte.

## Contexte de décision

La clôture ETH du 16 octobre a terminé cette tâche sur son périmètre borné ; elle n’a ni défini de règle autonome ni démontré un avantage exploitable. Le recontrôle du 26 octobre garde ETH terminale et confirme que la voie générale ne dispose toujours pas d’une préparation descriptive distincte. Le scheduler courant continue d’exiger `economic_validation=true`, une readiness économique approuvée et des preuves avant la recherche IA. Cette proposition ne contourne pas ce gate et ne raccorde rien au scheduler.

Les tickets [TAMTAM_AGAIN-6](https://manhattam.com/work/issue/TAMTAM_AGAIN-6) (qualification/découverte) et [TAMTAM_AGAIN-12](https://manhattam.com/work/issue/TAMTAM_AGAIN-12) (boucle de recherche jusqu’au paper N1) restent les registres de décisions opérationnelles ; le code reste la référence des règles exécutables.

## Règle explicite

Base : un seul instrument observé dans les fills de la même fenêtre de 30 jours, au moins 10 fills observés et 2 jours UTC actifs dans les 30 jours avant cutoff. Le seuil 10/2 est une proposition minimale de répétition pour une tabulation descriptive par jour ; il ne signifie ni puissance statistique ni activité complète. Le seuil historique 20/4 décrivait déjà une activité fréquente observée. Les PnL, le mode du compte, les risques et la compatibilité d’exécution sont affichés séparément et ne filtrent pas l’admission.

| Seuil de fills/jours actifs | Comptes mono-marché admissibles |
|---|---:|
| 5 / 1 (sensibilité basse) | 48 |
| 10 / 2 (proposé) | 22 |
| 20 / 4 (critère historique fréquent) | 2 |
| 40 / 6 (sensibilité stricte) | 1 |

**Cas sensible :** `5bcf` est admis à 10/2 malgré un screening de PnL déclaré négatif ; il passe à approfondir sous 20/4. Cette règle retient donc aussi une question non gagnante économiquement.

**Comptes multi-marchés :** 217 satisfont déjà le volume/jours 10/2, mais restent à approfondir parce que le snapshot ne ventile pas activité et couverture par instrument. Ils ne sont pas exclus ; leur question demande cette preuve avant de choisir ou agréger un marché.

## File prioritaire

P1 en premier ; la file courte réserve ensuite une place au candidat le mieux documenté de chaque namespace de marché supplémentaire, puis trie par jours actifs, fills observés et adresse. Cette rotation garde visibles les marchés préfixés tels que `xyz:`. Aucune mesure de performance ne participe au tri. Les comptes sont des sujets d’étude, pas des gagnants.

| Rang | Compte / marché | Activité observée | Performance déclarée | Risque connu / inconnu | Couverture | Compatibilité |
|---:|---|---|---|---|---|---|
| 1 | `43ad` / BTC | 165055 fills / 16 jours | positive_declared; delta déclaré 90 j 26529.038000 | mode disabled; drawdown PnL 180 j -5759.913633; risques non résolus 2 | 337 points courbe; 15.94 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour BTC, quelle est la distribution par jour UTC des 165055 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 2 | `5277` / SOL | 20414 fills / 5 jours | positive_declared; delta déclaré 90 j 68983.500735 | mode disabled; drawdown PnL 180 j -1891.716790; risques non résolus 2 | 116 points courbe; 4.374 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour SOL, quelle est la distribution par jour UTC des 20414 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 3 | `e452` / xyz:TSLA | 575 fills / 2 jours | unknown; delta déclaré 90 j inconnu | mode unifiedAccount; drawdown PnL 180 j inconnu; risques non résolus 2 | 91 points courbe; 1.936 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour xyz:TSLA, quelle est la distribution par jour UTC des 575 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 4 | `bcd3` / SOL | 473 fills / 3 jours | unknown; delta déclaré 90 j inconnu | mode unifiedAccount; drawdown PnL 180 j inconnu; risques non résolus 2 | 168 points courbe; 1.985 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour SOL, quelle est la distribution par jour UTC des 473 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 5 | `39d0` / BTC | 220 fills / 3 jours | unknown; delta déclaré 90 j inconnu | mode default; drawdown PnL 180 j inconnu; risques non résolus 2 | 208 points courbe; 2.983 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour BTC, quelle est la distribution par jour UTC des 220 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 6 | `9fd2` / BTC | 11 fills / 3 jours | unknown; delta déclaré 90 j inconnu | mode unifiedAccount; drawdown PnL 180 j inconnu; risques non résolus 2 | 130 points courbe; 2.584 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour BTC, quelle est la distribution par jour UTC des 11 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 7 | `1e07` / ETH | 2416 fills / 2 jours | unknown; delta déclaré 90 j inconnu | mode disabled; drawdown PnL 180 j inconnu; risques non résolus 2 | 93 points courbe; 1.966 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour ETH, quelle est la distribution par jour UTC des 2416 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |
| 8 | `aaf6` / ZEC | 1003 fills / 2 jours | unknown; delta déclaré 90 j inconnu | mode unifiedAccount; drawdown PnL 180 j inconnu; risques non résolus 2 | 83 points courbe; 1.975 j de requêtes; troncature inconnue=True | not_assessed |
|  | Question | Pour ZEC, quelle est la distribution par jour UTC des 1003 fills observés pendant les 30 jours avant le cutoff 1793009400000, et quelle couverture des requêtes est réellement documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché. |  |  |  |  |

## Comptes multi-marchés à approfondir

Ces comptes ont déjà au moins 10 fills observés sur au moins 2 jours, mais restent distincts de la file admise jusqu’à preuve d’activité et de couverture par marché. La sélection ci-dessous sert à résoudre cette lacune ; elle ne constitue pas une exclusion scientifique.

| Compte | Marchés observés | Fills 30 j / jours actifs | Question proposée | Preuve manquante |
|---|---|---:|---|---|
| `a92d` (17) | @107, BNB, BTC, ETH, GRAM et 12 autres | 22053 / 17 | Pour le compte a92d, parmi les marchés observés (@107, BNB, BTC, ETH, GRAM et 12 autre(s)), lesquels disposent d'une couverture par marché suffisante pour une description séparée sur 30 jours ? Ne pas agréger les marchés. | Fills observés et jours UTC actifs ventilés par marché sur la fenêtre de 30 jours.; Couverture/pagination des requêtes rattachée à chaque marché avant toute sélection d'un marché. |
| `eb3d` (8) | ALGO, BTC, ETH, NEAR, ONDO et 3 autres | 767 / 17 | Pour le compte eb3d, parmi les marchés observés (ALGO, BTC, ETH, NEAR, ONDO et 3 autre(s)), lesquels disposent d'une couverture par marché suffisante pour une description séparée sur 30 jours ? Ne pas agréger les marchés. | Fills observés et jours UTC actifs ventilés par marché sur la fenêtre de 30 jours.; Couverture/pagination des requêtes rattachée à chaque marché avant toute sélection d'un marché. |
| `8e46` (74) | @107, AERO, ALGO, ALT, ANIME et 69 autres | 18176 / 13 | Pour le compte 8e46, parmi les marchés observés (@107, AERO, ALGO, ALT, ANIME et 69 autre(s)), lesquels disposent d'une couverture par marché suffisante pour une description séparée sur 30 jours ? Ne pas agréger les marchés. | Fills observés et jours UTC actifs ventilés par marché sur la fenêtre de 30 jours.; Couverture/pagination des requêtes rattachée à chaque marché avant toute sélection d'un marché. |
| `6098` (18) | @260, AERO, CHIP, CRV, ICP et 13 autres | 1374 / 13 | Pour le compte 6098, parmi les marchés observés (@260, AERO, CHIP, CRV, ICP et 13 autre(s)), lesquels disposent d'une couverture par marché suffisante pour une description séparée sur 30 jours ? Ne pas agréger les marchés. | Fills observés et jours UTC actifs ventilés par marché sur la fenêtre de 30 jours.; Couverture/pagination des requêtes rattachée à chaque marché avant toute sélection d'un marché. |

## Séparation des dimensions

Le JSON contient, candidat par candidat : performance déclarée par horizon ; risque connu/risque non résolu ; couverture des courbes et requêtes ; activité observée par jours et marchés ; compatibilité d’exécution. Cette dernière reste `not_assessed` car aucune stratégie ou spécification de moteur n’est proposée.

Les comptes multi-marchés ayant assez d’activité sont `needs_more_evidence`, avec la preuve manquante par marché explicitée. Les candidats sans instrument visible sont différés ; l’unique compte marqué `excluded_before_payload_read` reste exclu sans décoder son snapshot.

## Sources et limites

Source : lignes `population_historical_decisions` à cutoff exact, produites par le screening historique autorisé ; aucune observation brute ni archive n’a été relue. Le cutoff n’est pas une période vierge et ne libère aucune période réservée. Le fichier JSON adjacent conserve les décisions détaillées des 2 533 comptes.

Références locales : `docs/continuous-research/ETH-DECISION-CLOSURE-20261016.md`, `docs/continuous-research/ETH-LOOP-RECHECK-20261026.md`, `docs/continuous-research/HISTORICAL-SELECTION.md`, `src/tamtam_again/population_scheduler.py`.
