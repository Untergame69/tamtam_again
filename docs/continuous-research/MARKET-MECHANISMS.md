# Mécanismes et règles de précision

Les profils produits depuis le catalogue public séparent faits de métadonnées,
règles documentées, inconnues par marché et capacités du moteur. Ils conservent
précision, collatéral, levier maximum, modes/tables de marge, delisting, référence
oracle du funding et limites de liquidation/exécution. Aucun modèle de
liquidation exacte, de marge isolée par tiers ou de file passive n'est annoncé.
Les paramètres funding HIP-3 du déployeur et définitions de référence de prix
doivent encore être étudiés par marché.

## Extension optionnelle du moteur v2

Une **nouvelle** variante peut déclarer `execution.market_rules` :

```json
{
  "version": 1,
  "instrument": "SYNTH",
  "currency": "USDC",
  "available_ms": 1000,
  "evidence_refs": ["fixture:metadata"],
  "sz_decimals": 2,
  "minimum_order_usdc": "10",
  "max_leverage": "2"
}
```

Exemple synthétique, pas un profil réel. Cette déclaration fait partie de la
spécification immuable. Les variantes anciennes ne reçoivent pas silencieusement
ce champ ; leur évaluation doit conserver la limite historique de précision.

Le moteur vérifie disponibilité des règles avant exécution, précision des
cotations et lot. Il arrondit les tailles vers zéro, borne également le levier
par la limite du marché, et refuse un ordre demandé sous le minimum documenté
de 10 USD. Il ne rejette pas automatiquement une petite exécution partielle
d'un ordre initialement admissible : la taille effectivement disponible est
arrondie au lot. Le modèle de slippage peut produire un prix moyen de fill qui
n'est pas un tick individuel ; aucun ordre limite réel n'est envoyé.

La vérification du minimum est conservatrice, y compris lors des sorties ; un
résidu trop petit peut rester ouvert. Il n'est pas clôturé gratuitement ou
effacé. Les exceptions réelles de réduction et règles spécifiques restent à
implémenter. Les règles ne modélisent pas oracle-band, open-interest caps,
liquidation ni marge isolée exacte. Leur présence ne suffit pas à certifier
l'exécution sur la plateforme. Les collatéraux non USDC restent un mécanisme
non pris en charge par la comptabilité du moteur v2.

Les prix autorisent cinq chiffres significatifs et au plus 6-szDecimals
décimales pour les perps ; les prix entiers constituent l'exception documentée.
Les helpers distinguent aussi la règle spot de huit décimales, sans déclarer
pour autant un moteur spot implémenté.

## Preuves et reproduction

139 tests passent : exemples officiels de prix, tailles signées, minimum,
métadonnées futures et refus explicite de devise non prise en charge.
Contrôle réel : 535 profils, précision renseignée pour 535, 233 indicateurs
onlyIsolated=true et 199 isDelisted=true au snapshot. Ces indicateurs ne sont
pas une liste d'instruments autorisés à trader.

```sh
PYTHONPATH=src .venv/bin/python scripts/market-mechanism-report.py \
  --db data/tamtam.sqlite3 --output /tmp/market-mechanisms.json
.venv/bin/python -m unittest discover -s tests -q
python3 scripts/research-baseline.py --db data/tamtam.sqlite3 --output /tmp/current.json
```

Les hashes des huit plans et des specs/critères des trois variantes ont été
comparés explicitement au baseline et sont identiques. Aucune donnée brute
réservée consultée. Sources et références dans
`market-mechanisms-control-20261007.json`.

Les inventaires population intègrent les profils de leurs marchés observés.
Rollback : arrêter le worker population avant annulation ciblée du commit,
conserver catalogues et rapports. Aucun changement du service collecteur ni
des variantes figées. Les profils d'expérience, l'extension multi-instruments
et l'allocation adaptative restent à livrer.

## Addendum — reliquats perpétuels sous le minimum (13 octobre 2026)

La documentation officielle expose `MinTradeNtl` (« Order must have minimum
value of $10 ») et l'erreur `ReduceOnly` séparément. Elle définit Reduce Only
comme une contrainte empêchant l'ordre d'augmenter la position, sans documenter
d'exception au minimum pour fermer un petit reliquat. Le moteur reste donc
conservateur : un reliquat dont la valeur est sous 10 USD n'est pas déclaré
closable à partir de ces pages seules.

La politique optionnelle `avoid_uncloseable_residual_v1`, activée pour la v5,
choisit avant simulation une instruction de fermeture complète lorsque la
réduction demandée produirait un ajustement sous 10 USD et que l'ordre complet
est admissible. La taille choisie est consignée séparément du fill. Le fill
partiel est ensuite déterminé uniquement par la profondeur visible : il n'est
ni plafonné ni réécrit pour préserver un reliquat donné. Le reliquat réellement
calculé est conservé; s'il reste sous le minimum, une nouvelle tentative de
sortie peut échouer et déclencher le diagnostic prévu. Une position déjà sous
le seuil reste inchangée lorsqu'aucun ajustement admissible n'existe.

Cette politique n'est pas activée rétroactivement sur v1–v4 et ne constitue pas
une preuve de fermeture réelle. Sa validation n'autorise pas à elle seule une
nouvelle expérience.

Sources officielles : [erreurs API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses),
[types d'ordre](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types),
[précision et lots](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size).
