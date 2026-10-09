# Tranche comptable ciblée — 9 octobre 2026

La revue externe du checkpoint 483be69 accepte la tranche précédente. Ce lot
traite ses deux lacunes comptables, sans sélection sur le résultat financier.
Plan déclaré et commité avant nouvelle lecture économique : 70bcd01,
`ACCOUNTING-TRANCHE-PLAN-20261009.json`. Disponibilité commune :
1791527290652. Les anciennes bornes diagnostiques restent fixes ; elles ne
deviennent pas des fenêtres actuelles ni des rendements comparables.

## Résultat du parcours historique

### Default : 0x87f9cd15f5050a9283b8896300f7c8cf69ece2cf

Périmètre : perp validateur USDC uniquement, mode public indépendant.
Bornes exactes 1791458734427 →1791479504849, durée 20770422 ms
(5 h 46 min 10,422 s, dans la tolérance pilote de six heures).

| Mesure | USDC |
| --- | ---: |
| Capital initial déclaré | 1193389,3529370001 |
| Capital final déclaré | 5641139,3529369999 |
| Variation brute | 4447749,9999999998 |
| Flux nets attribués au périmètre | 4447750,0 |
| Variation corrigée des flux | −0,0000000002 |
| Composantes observées | 0 |
| Résidu d'attribution observé | −0,0000000002 |

Le trou ledger/funding a été fermé par l'archive déjà reçue :
`raw_observations:12393255` et `:12393256`. La dernière preuve est disponible
à1791480875076, **après** l'ancien cutoff1791480414394. Aucun appel de collecte
supplémentaire. Les anciennes publications restent conservées. La hausse brute
provient des flux ; le résidu minuscule est conservé, sans le convertir en gain.

La mesure repose sur le contrat public de pagination et la valorisation
indépendante déclarée. La rétention exhaustive des fills n'est pas établie,
la réconciliation complète reste `unknown`. Aucun fill ni funding observé n'est
une preuve d'absence absolue. Pas de drawdown continu, de consolidation spot/autres
DEX/coûts externes, de qualification du compte ou d'avantage stratégique.
Décision de recherche : la hausse brute ne justifie pas une priorité fondée sur
la performance ; les décisions comportementales restent à étudier séparément.

### Disabled : 0xb695651daa495f59dd2725c6fe98322d8b51a92d

Bornes1791458998323 →1791479780164. Capital initial36691613,430941999,
final38756465,5288690031USDC. Variation brute2064852,0979270041USDC.
Pagination ledger/funding couverte. **Flux, résultat corrigé et résidu restent
inconnus.** Les composantes observées (réalisé127815,178356 ; frais42,468575 ;
funding4998,763110 ; variation latente4432079,4824259998USDC) ne constituent
pas un résultat complet corrigé des flux.

L'événement autorisé `raw_observations:12392108`, temps1791474081121,
déclare un `send` de2500000USDC depuis le perp validateur vers
0x2000000000000000000000000000000000000000 / `spot`, `fee=0`,
`feeToken=""`, `nativeTokenFee=0.0001142`.

Sources officielles consultées :

- [Send Asset](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint#send-asset)
  définit les périmètres de transfert et le montant demandé.
- [HyperCore/HyperEVM](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/hypercore-less-than-greater-than-hyperevm-transfers)
  décrit les adresses système et les frais de transfert Core vers EVM.
- [Schémas L1](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/nodes/l1-data-schemas)
  expose le champ nativeTokenFee sans établir son périmètre de débit pour ce send.
- [Activation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/activation-gas-fee)
  documente un autre mécanisme ; il ne justifie pas de classer automatiquement ce cas.

Ces sources et ce ledger ne suffisent pas à établir conjointement le principal
brut/net et l'actif/compte/solde débité pour les frais. La destination suggère
un transfert système, sans prouver toute sa comptabilité. Aucun débit HYPE ou
USDC n'est inventé. Le code conserve désormais principal, champs de frais,
participants, DEX et questions manquantes dans le diagnostic ; aucune écriture
de flux ou revenu n'est produite pour un send à frais non nuls.
Réveil : sémantique officielle de ces champs ou preuve autorisée du débit
par transaction et périmètre. Collecter davantage du même ledger ne répond pas
à cette question. Décision : suspendre la qualification économique de ce cas.

## Application uniforme et cadence

Le rapport `ACCOUNTING-TRANCHE-RESULT-20261009.json` couvre les87comptes
admissibles au cutoff annoncé, avec la même politique6h±15min, fin≤1h :
45fins anciennes,31bornes de durée absentes,11sans deux valorisations,
zéro fenêtre sélectionnée actuelle et zéro compte qualifié. Les lignes sans
fenêtre n'ont pas de capital/rendement calculable pour cette règle ; aucune
fenêtre plus courte n'est substituée. Les modes partagés restent hors modèle.

La cohorte courante conserve12exploration,12approfondissement et4+4témoins,
rotation quotidienne à1791590400000. Elle existe depuis1791504111598 et dispose
encore de plus de17h avant rotation au cutoff : maintien compatible avec6h.
Les32derniers intervalles réels sont3662482 à3749362ms, médiane3695065,5ms,
donc environ61–62,5min malgré une cible de60min après fin du job. Une fin de
cohorte dépasse1h au relevé. La fraîcheur continue de tous les comptes n'est
donc pas garantie par cette cadence. Aucun seuil n'est abaissé pour masquer cela.

Échéance préannoncée1791548890652 : vérifier les nouvelles bornes exactes sur
la même cohorte et appliquer la même politique. Chaque ligne de cadence expose
les temps observés, la dernière durée et l'observation attendue. Si la tolérance
de début ou la fraîcheur reste absente à cette échéance, conclure explicitement
à une inadéquation de cadence/capacité pour la règle, avec correction ciblée à
revoir ; ne pas attendre indéfiniment ni lancer d'inférence sur l'entrée inchangée.
Ce réveil prospectif n'est pas nécessaire pour conserver le calcul historique
réparé ci-dessus ; ce checkpoint est soumis à revue avant autres extensions.

## Reproduction et retour arrière

```sh
PYTHONPATH=src .venv/bin/python scripts/accounting-tranche-report.py --db data/tamtam.sqlite3 --plan docs/continuous-research/ACCOUNTING-TRANCHE-PLAN-20261009.json --period-policy config/account-qualification-period-policy.json --output /tmp/accounting-tranche-recheck.json
cmp docs/continuous-research/ACCOUNTING-TRANCHE-RESULT-20261009.json /tmp/accounting-tranche-recheck.json
.venv/bin/python -m unittest discover -s tests -q
```

Rapport recalculé deux fois, comparaison exacte réussie. Base ouverte en lecture
seule avec transaction cohérente ; aucun ordre, appel IA ou nouvelle requête
Hyperliquid. Collecteur920368 vérifié actif. Aucun service/cadence/budget changé.
Retour arrière : annuler le commit de diagnostic e2c2106 et le script/rapport si
nécessaire ; conserver les observations et anciennes publications, sans restaurer
la base ni interrompre la collecte. Vérifications finales consignées dans le CR.
