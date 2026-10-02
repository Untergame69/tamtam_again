# Architecture du collecteur initial

## Portée

Hyperliquid sert de première source de données, avec l’API publique `/info` pour
les marchés et comptes. Le modèle conserve le réseau, la source, la requête et
la réponse brute compressée afin de pouvoir recalculer les indicateurs. Il
n’implémente aucune route d’ordre ou signature.

## Données collectées

| Objet | Endpoint public | Usage |
| --- | --- | --- |
| Univers de tous les perpétuels | `perpDexs`, `metaAndAssetCtxs` par DEX | Univers et contextes de chaque DEX perpétuel Hyperliquid, y compris les DEX HIP-3. |
| Noms des DEX perpétuels | `perpDexs` | Associe le DEX de chaque univers au classement et aux snapshots. |
| Marchés spot et contextes | `spotMetaAndAssetCtxs` | Paires spot, volumes notionnels et prix disponibles au moment de la collecte. |
| Exécutions du compte | `userFillsByTime` | Fills, PnL clôturé par fill, frais et horodatages. |
| Funding du compte | `userFunding` | Flux de funding reçus/payés et taux observés. |
| Ledger hors funding | `userNonFundingLedgerUpdates` | Dépôts, transferts, retraits et autres variations de capital à réconcilier. |
| Positions et marge courantes | `clearinghouseState` | Instantané de position ouverte; ne constitue pas l’historique latent. |
| Soldes spot courants | `spotClearinghouseState` | Soldes de tokens utiles pour repérer les comptes unifiés et les expositions hors perpétuels. |
| Ordres ouverts | `openOrders` | Intention de trading encore affichée, complément des exécutions déjà remplies. |
| Historique de compte résumé | `portfolio` | Points historiques fournis par la plateforme, à comparer aux événements reconstruits. |
| Classement public | données consommées par la page officielle de classement | Découverte de candidats par PnL/ROI sur day, week, month et allTime. La route de données du site n’est pas une API documentée et peut changer. |
| Fills en direct des comptes suivis | WebSocket `userFills` | Exécutions des comptes suivis, avec snapshot d’abonnement et nouveaux fills. |
| Trades publics des marchés suivis | WebSocket `trades` | Prix, taille, sens, heure et identifiant de chaque trade public. |
| Carnet détaillé des marchés principaux | WebSocket `l2Book` en mode `fast` | Cinq niveaux de prix de chaque côté, pour deux marchés au départ. |
| Meilleurs prix acheteur/vendeur | WebSocket `bbo` | Meilleur prix des deux côtés pour les vingt marchés les plus utilisés par la cohorte. |
| Bougies des marchés utilisés par la cohorte | `candleSnapshot` | Fenêtre récente en chandelles d’une minute pour les vingt symboles les plus utilisés; top volume global en solution de repli. |

Le top 5 est défini par `dayNtlVlm` décroissant sur tous les DEX perpétuels et
les paires spot Hyperliquid. Le marché, son type et son DEX restent enregistrés
avec chaque rang. Cette mesure de volume notionnel sur 24 h est recalculée toutes
les 15 minutes. Les bougies récentes restent rafraîchies toutes les 60 secondes.
Quand la cohorte a des fills, le WebSocket suit ses vingt marchés les plus
utilisés par volume notionnel observé; avant cela, il utilise le top 5 global
comme point de départ. Les trades et le meilleur prix acheteur/vendeur sont
suivis sur ces vingt symboles; le carnet détaillé reste limité aux deux premiers
pour contenir la croissance de SQLite. Les bougies d'une minute suivent les
vingt premiers marchés de la cohorte. La liste est recalculée à partir des fills
enregistrés. Cette couverture élargie inclut les marchés très utilisés par les
baleines même s'ils ne figurent pas dans le top 5 notionnel (par exemple INJ et
ZEC au dernier relevé). Le seuil de vingt symboles permet aussi de suivre PUMP,
qui était le marché principal d'un compte ajouté à la cohorte.

La page officielle de classement fournit actuellement quatre fenêtres. Le
collecteur conserve les 25 premiers rangs PnL/ROI positifs et actifs par fenêtre
(day, week, month, allTime). Il épingle jusqu’à dix comptes dans une cohorte
qui se renouvelle selon l'activité récente, en favorisant les rangs PnL day et
week lorsqu'une place se libère. Cette limite
correspond à la limite documentée des abonnements WebSocket propres aux
utilisateurs. Les historiques de ces comptes continuent d’être complétés par
HTTP; les nouveaux fills arrivent par WebSocket. Le classement ne prouve pas
qu’un compte possède un avantage reproductible : il peut refléter une période
courte, du risque élevé ou des biais de survivance. Les candidats sont des
adresses observables et ne sont pas automatiquement regroupés avec leurs
sous-comptes ou propriétaires.

À chaque cycle horaire, un compte suivi sans fill observé depuis sept jours
repasse au statut candidat, puis le collecteur le remplace par un compte positif
au classement PnL jour/semaine si une place est disponible. Ce délai ne pilote
pas la maturité des données : les seuils de RE restent fondés sur les cycles
exploitables de chaque paire. Les rangs compacts sont enregistrés à chaque
cycle de découverte. La réponse
complète du leaderboard (plusieurs mégaoctets observés) est archivée une fois
par jour UTC, pour garder la provenance sans écrire le même jeu de dizaines de
milliers de lignes à chaque heure.

Les observations déjà enregistrées pour les comptes qui ne sont plus suivis
restent dans SQLite. Elles permettent de les requalifier sans perdre leur
historique; elles ne sont pas interrogées par les collectes des comptes suivis.
Il n'y a pas de suppression automatique des candidats ou des observations.

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

Les messages WebSocket sont enregistrés comme observations brutes, regroupées
par marché et par flux sur une seconde; chaque événement garde son heure de
réception et son heure source. À la reconnexion, les abonnements
sont reconstruits et les snapshots de fills renvoyés par le flux sont conservés.
Les cycles HTTP continuent à compléter les historiques et à réconcilier les
événements. Une interruption peut toutefois laisser un trou dans l’historique
des trades publics et du carnet; la collecte actuelle ne reconstruit pas
automatiquement chaque message de marché manqué. Le volume de stockage des
carnets doit être surveillé, car le flux est plus fourni qu’un relevé par minute.

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
.venv/bin/python -m tamtam_again init
.venv/bin/python -m tamtam_again collect-markets
.venv/bin/python -m tamtam_again collect-whales --limit-per-window 25 --max-accounts 10
.venv/bin/python -m tamtam_again top-markets
.venv/bin/python -m tamtam_again top-whales
.venv/bin/python -m tamtam_again research-status
.venv/bin/python -m tamtam_again collect 0x... --start-ms 1759276800000
.venv/bin/python -m tamtam_again report 0x... --start-ms 1759276800000 --end-ms 1790899200000
.venv/bin/python -m tamtam_again run-collectors --max-whale-accounts 10 --max-stream-markets 20 --max-depth-markets 2
```

Les commandes de découverte enregistrent les candidats et leurs rangs sans
action de portefeuille. `run-collectors` lance les cycles marché, baleines et
WebSocket en parallèle : bougies toutes les 60 secondes, classement de volume
toutes les 15 minutes, historique des baleines toutes les heures et flux live
en continu. Hyperliquid limite à dix les utilisateurs distincts abonnés aux
flux privés; cette première cohorte est donc limitée à dix comptes. Les trades
sont suivis sur vingt marchés dominants de la cohorte, avec BBO sur ces marchés
et carnet détaillé sur deux. Les bougies d'une minute couvrent aussi ces vingt
marchés. Les timestamps sont des millisecondes Unix UTC.

Le service systemd utilisateur est décrit dans
[`systemd/user/tamtam-again-collectors.service`](../systemd/user/tamtam-again-collectors.service).
Installation et consultation des journaux :

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
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

`research-status` est le point de contrôle avant d'écrire un replay. Il résume
les fills observés par compte, les marchés utilisés et les messages de marché
archivés pour ces symboles. Pour chaque paire compte × marché, il indique aussi
le premier et le dernier fill observés et l'ancienneté du dernier fill. Il ne
déclare pas encore le paper replay prêt : les
fills HTTP historiques couvrent une période plus longue que les flux de carnet,
et les marchés observés chez les comptes ne sont pas tous présents dans les
carnets suivis. Une stratégie de copie reste à définir avant d'estimer une
performance simulée.

Le rapport mesure la maturité par couple compte × marché. Il relie les fills
partiels via `startPosition` et reconstruit les excursions de position sur les
perpétuels. Une excursion peut être flat-à-flat, ou partir d'un niveau de
position observé, augmenter l'exposition puis revenir à ce niveau. Ce second
cas permet d'analyser une baleine qui garde une position nette ouverte tout en
faisant des allers-retours sur une partie de son exposition. Les sorties d'une
position déjà ouverte au début de la collecte ne comptent pas avant qu'une
nouvelle excursion soit observée. Les séquences ambiguës, tronquées ou
commencées avant la couverture observée sont exclues. Un cycle exploitable
exige que chacun de ses fills soit
dans une fenêtre HTTP `userFillsByTime` complète et possède un BBO archivé datant
de 1 s maximum. Si un fill de clôture traverse un baseline non nul, le cycle
n'inclut que la part de cette exécution nécessaire pour revenir au baseline;
frais et PnL sont alloués proportionnellement, le reste correspondant à la
réduction d'inventaire préexistant. Le rapport conserve aussi les ordres bruts, la couverture BBO
dans la fenêtre de capture et un indicateur à 250 ms pour distinguer les
hypothèses rapides.

Pour étudier une stratégie de copie, l'heure du fill sur la plateforme et
l'heure à laquelle notre collecteur reçoit le message `userFills` sont deux
repères différents. Les preuves RE utilisent l'heure du message WebSocket live
`userFills` (les snapshots `isSnapshot=true` sont historiques et exclus), puis
comparent l'heure locale de réception des BBO, trades et carnets au signal reçu
par le suiveur. Une cotation reçue
après l'exécution de la baleine peut donc être disponible au suiveur avant qu'il
reçoive le signal; elle ne l'était pas avant l'exécution de la baleine. Les
messages reçus dans la même milliseconde que le signal sont ambigus et exclus de
la couverture antérieure. Cette cotation ne garantit pas un fill au même prix :
le paper devra ajouter le délai de réaction, les frais, le slippage et le risque
de sélection adverse.

Les preuves conservent également l'ordre des fills reconstruit en reliant la
position de départ de chacun à la position après le fill précédent. Cet ordre
est essentiel lorsque plusieurs fills partagent le même horodatage; leurs
identifiants seuls ne donnent pas nécessairement l'ordre d'exécution.

Le premier palier est de 5 cycles exploitables pour lancer une RE exploratoire;
les suivants sont 10 puis 30 pour approfondir, et 100 pour comparer. L'unité
compte les excursions contextualisées, pas les fills ou les ordres isolés. Ces
seuils déclenchent une analyse, ils ne prouvent pas un avantage statistique et
ne fixent aucun délai. L'ETA est estimée au débit observé du couple dès que deux
cycles sont disponibles, sur les dix plus récents au maximum. Le calcul inclut
le temps calme depuis l'ouverture du premier cycle échantillonné jusqu'à
maintenant, afin qu'une interruption d'activité allonge l'estimation. Elle est
marquée de confiance faible avant dix cycles et reste indicative.
Le seuil est un minimum de déclenchement : la RE reçoit aussi les cycles déjà
collectés au moment où Hermes démarre, jusqu'aux 100 premiers cycles cumulés
(ou jusqu'au seuil complet si celui-ci dépasse 100). Les paliers supérieurs
reprennent ainsi l'échantillon antérieur et l'élargissent. Le calcul d'ETA ne
retarde jamais une RE.
Si Hermes ou la revue Codex demande plus de données, le prochain seuil
strictement supérieur propre au couple est conservé. Après une RE acceptée, la
collecte passe au palier suivant afin de comparer les versions de l'hypothèse
avec davantage de données.

Deux tâches Hermes surveillent la file SQLite toutes les cinq minutes et ne
appellent le modèle que lorsque sa sortie change : `tamtam-again-research`
déclenche la rétro au palier atteint; `tamtam-again-paper-n1` traite ensuite la
spécification paper. L'ordonnanceur est tické chaque minute par la crontab
existante. `workflow-complete` lance ensuite une revue Codex indépendante en
sandbox lecture seule et n'accepte une stratégie que si les deux avis
concordent. Chaque run possède une empreinte d'entrée, un bail de reprise et
des artifacts immuables. `needs_more_data` augmente le seuil; `redo_re` relance
la rétro au même seuil. Chaque RE acceptée crée une nouvelle révision Paper N1,
même si la stratégie proposée est identique : le N1 actif référence ainsi la RE
la plus récente et son échantillon courant. Les versions précédentes
sont conservées pour comparer l'évolution des hypothèses et des spécifications.
Le nouvel N1 ne devient actif qu'après validation de son artifact; une rétro
acceptée plus récente garde la priorité si deux runs paper finissent dans le
désordre.

Le N1 est local et virtuel : aucune clé, signature ou route d'ordre réel. Il
initialise un cahier des charges et un ledger virtuel; son moteur de contrôle
continu et son suivi des résultats restent une phase distincte.

Pour installer les deux surveillances Hermes :

```sh
scripts/install-hermes-crons.sh
```

Commandes de maintenance manuelle :

```sh
.venv/bin/python -m tamtam_again workflow-tick --stage research
.venv/bin/python -m tamtam_again workflow-tick --stage paper
.venv/bin/python -m tamtam_again workflow-claim RUN_ID
.venv/bin/python -m tamtam_again research-evidence RUN_ID --output data/automation/evidence/research/RUN_ID.json
.venv/bin/python -m tamtam_again workflow-complete RUN_ID data/automation/results/research/RUN_ID.json
```

## Sources

- [Hyperliquid — Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Hyperliquid — Perpetuals endpoints](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [Hyperliquid — Spot endpoints](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot)
- [Hyperliquid — Rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [Hyperliquid — Classement public](https://app.hyperliquid.xyz/leaderboard)
