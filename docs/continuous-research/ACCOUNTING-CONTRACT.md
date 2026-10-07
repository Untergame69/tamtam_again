# Qualification comptable — contrat de normalisation v1

`accounting.reconcile_period` calcule une période explicite sur un périmètre
prouvé. Ce reducer n'interroge pas la base brute ni les fenêtres réservées.
Il ne constitue pas encore un adaptateur exhaustif des réponses Hyperliquid.

Entrée : start_ms, end_ms, as_of_ms ; scope (id, currency, account_mode) ;
coverage par fills/funding/flows/other_income/valuation_scope avec status et
références de preuves ; valuations (bornes exactes et checkpoints) ; events.
Les événements appartiennent à (start,end], les valuations aux deux bornes.
Chaque donnée porte event_ms et available_ms ; une donnée pas encore disponible
ne fournit pas une comptabilité complète. Les identités conflictuelles bloquent
les métriques et les doublons identiques sont comptés une seule fois.

Les références de couverture doivent venir d'un adaptateur qui a vérifié les
fenêtres/cursors, positions initiales et continuité. La présence d'une réponse
REST, y compris une page courte ou vide, ne suffit pas. Les fixtures ont des
références fixture-only et ne qualifient pas un compte réel.

## Formules et exigences

PnL économique = equity_finale - equity_initiale - flux_externes.
PnL composants = PnL réalisé + variation du latent - frais + funding + autres revenus.
Écart = PnL économique - PnL composants, conservé même lorsqu'il est non nul.
Un écart mesuré n'est jamais automatiquement considéré acceptable.

Les frais négatifs sont des remises. `fee` inclut builderFee : pas de seconde
charge. Une devise différente nécessite une conversion documentée au temps
réel de l'événement, jamais le prix courant. Pas de flux net par défaut pour
un transfert : l'adaptateur doit démontrer s'il traverse la frontière du
périmètre ou reste interne. Les relations de sous-comptes ne sont pas fusionnées
sans périmètre de consolidation prouvé.

Les valeurs de plusieurs dex ne sont jamais additionnées par ce reducer.
Les modes unifiedAccount/portfolioMargin/dexAbstraction exigent un modèle de
collatéral partagé vérifié par l'adaptateur, sinon les métriques restent inconnues.
Pour les autres modes, la preuve de valuation_scope reste obligatoire : le simple
nom du mode ne certifie pas une valorisation globale ou tous les revenus.

Le rendement Modified Dietz est explicitement une estimation, avec capital
pondéré par le moment des flux. Le TWR est calculé uniquement lorsqu'une
valuation existe au timestamp de chaque flux externe. Le drawdown est celui
de cette courbe corrigée des flux, aux checkpoints observés ; le drawdown
intra-checkpoint demeure inconnu. Un capital nul/négatif ne produit pas de
rendement valide par division arbitraire.

## Utilisation et état réel

```sh
PYTHONPATH=src .venv/bin/python scripts/accounting-reconcile.py normalized-period.json --output /tmp/accounting.json
.venv/bin/python -m unittest discover -s tests -q
```

Les premiers inventaires réels de population sont unifiés. Leur collatéral
consolidé, les historiques de flux et la couverture des frais sont à normaliser
et réconcilier avant un verdict de performance. Le code ne prétend pas que la
somme des snapshots standards et HIP-3 donne le capital du compte.

Travail restant : adaptateur Hyperliquid couvrant funding/ledger/autres revenus,
spot et valorisations/conversions nécessaires, bornes comparables et preuves de
complétude. Puis cas réels contrastés et exécution automatique sur la population.
La qualification v1 descriptive reste consultable pour l'historique, sans être
transformée rétroactivement en preuve de validation économique.
