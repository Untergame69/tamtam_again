# Catalogue causal des collatéraux

Le worker population partage un catalogue public issu de `allPerpMetas` et
`spotMetaAndAssetCtxs`, rafraîchi au plus une fois par heure dans le parcours
séquentiel actuel. Deux appels utilisent le quota projet ; aucun abonnement
utilisateur supplémentaire. La cadence est configurable, minimum 60 secondes.
Plusieurs workers metadata simultanés pourraient dupliquer ce rafraîchissement ;
ils resteraient bornés par le quota mais aucun bail partagé metadata n'est établi.

La table additive `collateral_catalogs` conserve les versions, leur disponibilité
réelle et leurs références brutes. Chaque instrument est associé au
collateralToken et au tokenId spot. L'index du jeton n'est jamais sa position
dans le tableau. Les préfixes des instruments identifient les DEX : aucune
correspondance par rang de réponse n'est supposée. Les univers vides/mélangés et
les identités ambiguës restent inconnus ; doublons d'index refusés.

L'adaptateur choisit le dernier catalogue disponible **avant l'événement**.
Un catalogue reçu plus tard ne qualifie pas rétroactivement une devise passée.
Si la devise change dans une période, les événements/bornes incompatibles
empêchent le rapprochement. Le catalogue ne fournit pas de prix FX, ne garantit
pas le maintien historique d'un instrument et n'additionne aucun capital partagé.

Contrôle réel du 7 octobre : 11 DEX et 535 instruments ; collatéraux USDC,
USDH, USDE et USDT0 identifiés. Les montants de ces jetons ne sont pas
interchangeables en USD. Preuve : `collateral-control-20261007.json`.
Les rapports historiques antérieurs restent inchangés et non qualifiés.

```sh
PYTHONPATH=src .venv/bin/python scripts/collect-collateral-catalog.py \
  --db data/tamtam.sqlite3 --output /tmp/collateral.json
.venv/bin/python -m unittest discover -s tests -q
```

Sans `--force`, la commande réutilise le catalogue frais sans appel réseau ni
nouvelle date de disponibilité. Les sources officielles :
[perpetual metadata](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals),
[spot tokens](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot).

Retour arrière : arrêter timer/service population avant annulation ciblée du
commit, conserver table et observations. Aucun changement des collecteurs
initiaux ou des pilotes. Valorisation consolidée, couverture, risque et FX
restent à vérifier ; identification de devise ne constitue pas validation.
