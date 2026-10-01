# Architecture du collecteur initial

## Portée

Hyperliquid sert de première source de données, avec l’API publique `/info` pour
les marchés et comptes. Le modèle conserve le réseau, la source, la requête et
la réponse brute compressée afin de pouvoir recalculer les indicateurs. Il
n’implémente aucune route d’ordre ou signature.

## Données collectées

| Objet | Endpoint public | Usage |
| --- | --- | --- |
| Marchés perpétuels et contextes | `metaAndAssetCtxs` | Univers, mark/mid, funding courant, open interest, volumes et contexte du marché au moment de la collecte. |
| Exécutions du compte | `userFillsByTime` | Fills, PnL clôturé par fill, frais et horodatages. |
| Funding du compte | `userFunding` | Flux de funding reçus/payés et taux observés. |
| Ledger hors funding | `userNonFundingLedgerUpdates` | Dépôts, transferts, retraits et autres variations de capital à réconcilier. |
| Positions et marge courantes | `clearinghouseState` | Instantané de position ouverte; ne constitue pas l’historique latent. |
| Soldes spot courants | `spotClearinghouseState` | Soldes de tokens utiles pour repérer les comptes unifiés et les expositions hors perpétuels. |
| Ordres ouverts | `openOrders` | Intention de trading encore affichée, complément des exécutions déjà remplies. |
| Historique de compte résumé | `portfolio` | Points historiques fournis par la plateforme, à comparer aux événements reconstruits. |
| Classement public | données consommées par la page officielle de classement | Découverte de candidats par PnL/ROI sur day, week, month et allTime. La route de données du site n’est pas une API documentée et peut changer. |
| Carnet des cinq principaux marchés | `l2Book` | État du carnet au moment de chaque cycle. |
| Bougies des cinq principaux marchés | `candleSnapshot` | Fenêtre récente en chandelles d’une minute. |

Le top 5 est défini par `dayNtlVlm` décroissant sur le premier univers de
perpétuels Hyperliquid. Cette mesure de volume notionnel sur 24 h est recalculée
toutes les 15 minutes dans le service continu. Les carnets et cinq dernières
minutes de bougies sont repris toutes les 60 secondes. Ce choix est un filtre
de liquidité opérationnel, pas une mesure de qualité d’une stratégie.

La page officielle de classement fournit actuellement quatre fenêtres. Le
collecteur conserve les classements PnL/ROI positifs et actifs, puis approfondit
au plus cinq comptes par cycle dans le service. Le classement ne prouve pas
qu’un compte possède un avantage reproductible : il peut refléter une période
courte, du risque élevé ou des biais de survivance. Les candidats sont des
adresses observables et ne sont pas automatiquement regroupés avec leurs
sous-comptes ou propriétaires.

Les rangs compacts sont enregistrés à chaque cycle de découverte. La réponse
complète du leaderboard (plusieurs mégaoctets observés) est archivée une fois
par jour UTC, pour garder la provenance sans écrire le même jeu de dizaines de
milliers de lignes à chaque heure. Les comptes candidats sont ordonnés par
curseur de collecte : ceux jamais collectés passent d’abord, puis les historiques
les moins avancés sont repris avant de recommencer un compte déjà couvert.

Les requêtes de compte utilisent l’adresse maître ou sous-compte réellement
associée aux données. Une adresse d’agent peut ne rien retourner. Les comptes
liés ne sont pas automatiquement fusionnés.

## Stockage et provenance

`data/tamtam.sqlite3` conserve le registre, les rangs de marchés et de comptes,
les curseurs de collecte et les observations brutes. Chaque observation stocke
la plateforme/réseau, l’endpoint, l’entité, les bornes demandées, le moment de
collecte, un hash du JSON et le corps JSON compressé. Une contrainte d’unicité
empêche de réinsérer deux fois la même réponse pour le même sujet et la même
fenêtre. Les snapshots qui évoluent restent distincts grâce au hash de réponse.

Les nombres du JSON brut restent des chaînes quand l’API les renvoie en
chaînes. Les calculs d’agrégation utilisent `Decimal`. Une nouvelle version du
normaliseur pourra donc recalculer les indicateurs sans réécrire la source.
Le rapport dédoublonne les événements aux fenêtres inclusives et vérifie que
les intervalles persistés couvrent réellement toute la période demandée. Une
fenêtre initialement saturée reste incomplète jusqu’à la collecte de sa reprise.

## Ce que le premier rapport mesure

Le rapport sépare les fills spot et perp, le PnL clôturé par type de marché,
les frais par jeton de frais, le funding et le nombre d’événements de ledger. Il
montre pour les perps `PnL clôturé - frais USDC connus + funding` comme
contribution observée sur la fenêtre. Ce chiffre n’est pas un rendement total :
il ne réconcilie pas encore les transferts de capital, tous les frais en jetons
différents, les comptes liés, les positions latentes, les liquidations ou une
couverture historique lacunaire.

La documentation officielle limite `userFillsByTime` aux 10 000 fills les plus
récents, à 2 000 lignes par réponse ; les autres endpoints temporels sont
paginés à 500 lignes ou blocs distincts. Le collecteur applique le plafond
propre à chaque endpoint, conserve le recouvrement de timestamp pour
déduplication et marque les fenêtres saturées comme incomplètes. Il mémorise le
dernier timestamp couvert afin que le cycle suivant reprenne la collecte sans
recommencer toute la fenêtre; une répétition au même timestamp ne fait jamais
avancer le curseur. La limite de requêtes est pondérée selon le poids API
documenté, avec une marge sous le plafond IP; les réponses HTTP 429 et 5xx sont
retentées avec attente exponentielle et `Retry-After`. Une mesure de rentabilité
ne peut pas être qualifiée avant que ces limites et la réconciliation de capital
soient résolues.

## Découverte et qualification des candidats

Le registre exige une source de découverte pour chaque adresse. Le collecteur
lit le classement utilisé par la page officielle Hyperliquid, qui est un canal
pratique mais non documenté comme interface stable. Une panne ou un changement
de format arrête le cycle des baleines sans interrompre celui des marchés. Il
faudra comparer ce canal aux indexeurs et explorateurs, et mesurer les biais de
survivance. Les adresses, sous-comptes et identités liées restent des hypothèses
tant qu’elles ne sont pas corroborées.

## Exécution locale

Depuis `tamtam_again/` :

```sh
PYTHONPATH=src python -m tamtam_again init
PYTHONPATH=src python -m tamtam_again collect-markets
PYTHONPATH=src python -m tamtam_again collect-whales --limit-per-window 5 --max-accounts 5
PYTHONPATH=src python -m tamtam_again top-markets
PYTHONPATH=src python -m tamtam_again top-whales
PYTHONPATH=src python -m tamtam_again collect 0x... --start-ms 1759276800000
PYTHONPATH=src python -m tamtam_again report 0x... --start-ms 1759276800000 --end-ms 1790899200000
PYTHONPATH=src python -m tamtam_again run-collectors
```

Les commandes de découverte enregistrent les candidats et leurs rangs sans
action de portefeuille. `run-collectors` lance les cycles marché et baleines en
parallèle : marchés toutes les 60 secondes, classement de volume toutes les 15
minutes, découverte des baleines toutes les heures. Les limites peuvent être
ajustées avec les options de la commande. Les timestamps sont des millisecondes
Unix UTC.

Le service systemd utilisateur est décrit dans
[`systemd/user/tamtam-again-collectors.service`](../systemd/user/tamtam-again-collectors.service).
Installation et consultation des journaux :

```sh
mkdir -p ~/.config/systemd/user
cp systemd/user/tamtam-again-collectors.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tamtam-again-collectors.service
loginctl enable-linger Untergame
journalctl --user -u tamtam-again-collectors -f
```

Le mode linger maintient le gestionnaire systemd utilisateur actif après la
fermeture de session et au démarrage de la machine.

## Phases suivantes

1. Comparer le classement web aux indexeurs et explorateurs, vérifier sa
   stabilité et détecter ses changements de schéma; ce travail est suivi dans
   [TAMTAM_AGAIN-6](https://manhattam.com/work/issue/TAMTAM_AGAIN-6).
2. Valider la complétude et la réconciliation des fills, funding, ledger,
   dépôts/retraits et valeurs de portefeuille.
3. Définir des métriques de qualification (période, profit net réconcilié,
   drawdown, stabilité, coûts, capital et capacité) avant de classer les comptes.
4. Définir un backtest hors échantillon, puis plusieurs paliers de paper trading.
5. Relier Hermes à un harness versionné après revue de ses capacités et contrats
   actuels. Les tickets TAMTAM_AGAIN ordinaires ne déclenchent pas Hermes.

## Sources

- [Hyperliquid — Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Hyperliquid — Perpetuals endpoints](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [Hyperliquid — Spot endpoints](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot)
- [Hyperliquid — Rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [Hyperliquid — Classement public](https://app.hyperliquid.xyz/leaderboard)
