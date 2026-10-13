# Bilan final — v4 HYPE (13 octobre 2026)

## Disposition

La session indépendante `4303114ebedf4d238241a605a41c591c` s'est terminée automatiquement le 12 octobre à 17:30:49 CEST, après 23 min 26 s. Le rapport final #5 (`217019a2…`) recommande `abandon` / `stop_and_reconcile`. La position paper reste `+0,05 HYPE`; le dernier ordre prioritaire expiré et toujours présent dans `pending` ne vaut pas exécution. La session est suspendue et aucune session v4 n'est active.

## Cinq cycles complets

Les cycles sont segmentés à chaque retour du cumul des fills signés à zéro. Le net de chaque cycle est le PnL réalisé du cycle moins ses frais simulés.

| Cycle | Taille aller-retour | PnL réalisé | Frais | Net après coûts |
|---|---:|---:|---:|---:|
| 1 | 0,26 HYPE | -0,017259060 | 0,019745152947 | **-0,037004212947 USDC** |
| 2 | 0,34 HYPE | -0,044345180 | 0,025834665519 | **-0,070179845519 USDC** |
| 3 | 0,40 HYPE | -0,078532000 | 0,030358810080 | **-0,108890810080 USDC** |
| 4 | 0,39 HYPE | -0,016949985 | 0,02964598290225 | **-0,04659596790225 USDC** |
| 5 | 0,37 HYPE | -0,020529635 | 0,02813366908575 | **-0,04866330408575 USDC** |
| **Total des cinq cycles** |  |  |  | **-0,311334140534 USDC** |

Ces résultats sont descriptifs sur cinq cycles courts; ils ne permettent pas d'inférer un avantage durable.

## Sixième cycle incomplet et bilan final

Le sixième cycle a ouvert `+0,29 HYPE`, puis réduit `-0,24 HYPE`; il reste `+0,05 HYPE`. La valeur de ce reliquat au dernier prix observé était 4,219625 USDC. Le reliquat n'est pas une perte réalisée et n'a pas été effacé.

Au dernier état : 183 signaux live, 13 exécutions simulées, 116 exécutions manquées, PnL réalisé cumulé -0,216363500 USDC, frais 0,15386106867075 USDC, PnL latent -0,00686217500000 USDC et net marqué -0,37708674367075 USDC. Il ne s'agit pas d'un résultat final à plat ni d'une valorisation au 13 octobre. Le plafond de perte de 10 USDC n'a pas été atteint.

La clôture prioritaire a échoué sous la règle de minimum du simulateur : 16 tentatives `priority_exit_below_venue_minimum`, puis une expiration. Le rapport #5 a enregistré `priority_exit_unresolved_position` et conservé le reliquat. La valeur affichée de 4,219625 USDC décrit l'exposition résiduelle au dernier prix, pas le coût définitif de sa liquidation.

## Règle officielle consultée et correction limitée

Les pages officielles Hyperliquid publient une erreur `MinTradeNtl` (« Order must have minimum value of $10 »), décrivent `Reduce Only` comme une protection contre l'augmentation de position, et documentent les lots/arrondis. Elles ne déclarent pas d'exception au minimum pour une fermeture perpétuelle reduce-only. La conclusion prudente est donc : ne pas simuler une fermeture d'un ordre sous 10 USD sans preuve officielle supplémentaire.

### Rectificatif de politique moteur et disposition (lié, 13 octobre 2026)

Le texte de la politique précédent décrivait un plafonnement d'un fill partiel pour préserver un reliquat d'au moins 10 USD. Ce comportement après coup est supprimé. La v5 sélectionne une instruction de fermeture complète avant simulation, puis utilise le fill fourni par la profondeur visible, sans le modifier. Le reliquat v4 reste `+0,05 HYPE`; son ordre paper expiré peut faire l'objet d'une annulation administrative de file, sans fill ni clôture. La v4 demeure incomplète et son résultat aller-retour final reste inconnu. Voir le [rectificatif lié et la demande v2](PAPER-V4-CLOSEABLE-REDUCTION-REQUEST-20261013-V2.json) ainsi que le bilan v5 lorsqu'il sera produit.

Une politique opt-in `avoid_uncloseable_residual_v1` est ajoutée au moteur : si une réduction planifiée laisserait moins de 10 USD et que la position complète vaut au moins le minimum, la cible est ramenée à zéro; un fill partiel est plafonné pour laisser zéro ou une position arrondie d'au moins 10 USD. Une position déjà sous 10 USD reste intacte; une sortie obligatoire échoue avec diagnostic si elle ne peut pas être exécutée. Le comportement est opt-in et n'est activé sur aucune expérience historique.

Tests ciblés couvrant fermeture complète si admissible, fill partiel sans poussière, et préservation d'une position déjà sous le minimum : voir le test `test_opt_in_reduction_policy_*` dans `tests/test_paper_engine_v3.py`.

## Demande liée et reprise

La demande structurée `PAPER-V4-CLOSEABLE-REDUCTION-REQUEST-20261013-A880-HYPE.json` relie le diagnostic, les cinq cycles, le rapport final, les règles officielles et le correctif. Elle demande comme question future : « La politique de réduction qui évite les reliquats sous-minimum réduit-elle les sorties prioritaires non résolues, tout en préservant les reliquats déjà sous-minimum et sans simuler de fill non admissible ? »

Cette question n'autorise pas une relance v4 ni une nouvelle expérience. Avant toute reprise : valider le modèle et les règles contre des fixtures documentées; garder le `+0,05 HYPE` v4 dans son registre et le porter explicitement comme reliquat non réconcilié; définir dans la nouvelle version la question, les bornes et le traitement de ce reliquat. Aucun budget IA supplémentaire, appel IA ou ordre réel n'est autorisé par cette demande.

## Références de preuve

- Rapport automatique final #5 : `paper_experimental_reports:217019a2b7915f7e4b34baddccb23a8159edc08e8d6fea6bd671893980c4248c`.
- Suspension : `paper_suspensions:4303114ebedf4d238241a605a41c591c`.
- Session, état et registre des fills : `paper_sessions:4303114ebedf4d238241a605a41c591c`.
- Démarrage, parcours entrée-sortie et bilans précédents : `PAPER-V4-START-20261012-A880-HYPE.json`, `PAPER-V4-LIVE-CYCLE-AND-REPORT-20261012-A880-HYPE.json`.
- Rectificatif de journal d'opportunités : `PAPER-V4-OPPORTUNITY-LOG-RECTIFICATION-20261012-A880-HYPE.json`.
