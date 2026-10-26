# Faisabilité économique des expériences d’exécution — 26 octobre 2026

## Décision

**Aucune expérience supplémentaire n’est autorisée par cette mission. Les éléments examinés ne justifient pas encore de choisir une nouvelle expérience économique.** Les trois voies répondent à des questions différentes ; l'absence de certaines mesures ne doit pas devenir une interdiction générale d'étudier des hypothèses sous scénarios explicites :

- **Après réception REST**, on peut définir un signal tardif, puis simuler nos propres décisions et prix si les données le permettent. Les markouts existants ne constituent ni cette simulation ni son PnL, et n'établissent pas ici un avantage exploitable.
- **Après réception WebSocket archivée**, le paper sait déclencher une règle de suivi et simuler un IOC. Le délai de 5 s et le slippage sont des paramètres, pas une latence d’ordre mesurée; le résultat HYPE récent est court, négatif et encore exposé.
- **Maker passif / rebates**, le code n’a pas de modèle de fill positif : le modèle conservateur rend zéro fill. Une cotation touchée ou une taille visible ne donne pas la priorité de file.

La voie la plus proche des capacités déjà exercées est le paper IOC post-WebSocket pour a880/HYPE ; ce constat porte sur les parcours examinés, pas sur toutes les stratégies possibles. Les versions v4/v5 n’ont toutefois pas démontré une session avec clôture complète. Une nouvelle évaluation prospective demanderait une fenêtre distincte. Pour une étude de sensibilité préalable, des frais publics et plusieurs délais explicitement supposés sont utilisables ; le tarif réel de notre compte et les délais d'ordre non mesurés restent alors inconnus. Un résultat sous ces hypothèses ne prouve pas une exécution réelle.

## État vérifié et preuves conservées

- Commit de départ : `b1797b10b83db7edc1ef86d8f60ca056904f6ed7`.
- L’analyse a été faite dans le worktree `mission/execution-feasibility-20261026`, sans modification du checkout principal ni lecture de la base opérationnelle.
- Le cutoff HYPE des calculs historiques reste `2026-10-12T07:16:34.195Z`. Les 32 921 fills REST étaient répartis sur 171 pages toutes marquées incomplètes; les positions observées formaient deux segments censurés, séparés par une rupture de 16 h 17 min. Le résultat économique porte uniquement sur 652 épisodes bornés.
- Le paper v5 a tourné 30 minutes le 13 octobre : 234 signaux, 29 exécutions, dont 4 partielles, et 97 occasions manquées. Le net marqué était `−0,524081 USDC`; il restait `−0,61 HYPE` et un ordre virtuel en attente, donc le résultat aller-retour final est inconnu. La seule sélection de clôture v5 exécutée a rempli toute la taille prévue; elle n’a pas démontré le fill partiel visé.
- La fenêtre prospective ETH 67f7, figée du 14 au 15 octobre, est terminée. Elle a livré 9 874 fills uniques après déduplication. Le recontrôle Git du 26 octobre indique que la route est terminale et qu’aucune donnée nouvelle n’a été utilisée pour rouvrir ce travail.
- La vue opérationnelle Manhattan accessible en recherche indiquait au 17 octobre une observation 67f7 terminée et aucun ordre réel. Son état était explicitement daté du 17 octobre; ce n’est pas une preuve de l’état runtime au 26 octobre. La commande YouTrack n’était pas disponible dans cette session; les tickets TAMTAM_AGAIN-6/7/12 n’ont donc pas été lus directement. Aucun état de service n’est affirmé ici.

Références locales principales : [bilan HYPE v5](PAPER-V5-FINAL-20261013-A880-HYPE.md), [bilan HYPE v4](PAPER-V4-FINAL-20261013-A880-HYPE.md), [attribution économique HYPE](A880-HYPE-EPISODE-ATTRIBUTION-20261013.md), [résultat ETH 67f7](POPULATION-67F7-ETH-RESEARCH-RESULT-20261014.md), [contexte de marché ETH](POPULATION-67F7-ETH-INVENTORY-MARKET-CONTEXT-20261014.md), [résolution de la fenêtre ETH](POPULATION-67F7-ETH-EXISTING-WINDOW-RESOLUTION-20261016-v1.md), [recontrôle courant de la boucle ETH](ETH-LOOP-RECHECK-20261026.md).

## Comparaison des voies

| Dimension | Signal après réception REST | Signal après réception WebSocket archivée | Maker passif / rebates |
|---|---|---|---|
| Information disponible pour décider | Fill, prix, taille, côté, `crossed`, position de départ et frais du fill sont connus après réponse. Le collecteur ETH interrogé pour 67f7 pollait toutes les 5 min avec 1 min de recouvrement. L’heure de réception du fill lui-même n’existe pas dans les pages REST. | Pour les événements non-snapshot, le collecteur conserve temps événementiel, réception locale et archivage. Le suivi a880 consomme les fills live avec le BBO/L2 et la santé du flux; snapshots exclus. C’est la seule voie où le point de décision local est observable. | La règle de prix/quantité peut être choisie à partir du carnet disponible, mais il manque l’état de la file à ce prix et l’ordre hypothétique n’a ni ack ni cycle d’annulation réellement observable. |
| Modèle de fill | Aucun modèle d’ordre défini pour un signal reçu après coup. Les markouts REST d’ETH ne sont pas des fills simulés. | Moteur déterministe `market_ioc` : prix ask/bid observé, taille limitée à 10 % de la taille affichée, quote au plus vieux d’1 s, IOC expiré si non exécuté, slippage configuré à 5 bps. Les fill/miss/partiels sont simulés depuis le carnet visible. | `passive_conservative` enregistre `passive_queue_priority_unavailable` et ne remplit pas. C’est une borne prudente à zéro, pas une estimation centrale ni un fill passif plausible. |
| Délais | La cadence de 5 min donne une disponibilité tardive; l’horodatage REST est celui de la page, pas celui du fill. Aucune latence de décision d’un trader ne peut être déduite. | a880 v5 paramètre `latency_ms=5000`. Le tick paper vise 600 ms; le rapport a mesuré jusqu’à 806 ms entre ticks et 637,563 ms de traitement, mais ni trajet réseau d’ordre ni ack/fill exchange. Un quote de l’unique clôture sélectionnée avait 723 ms. Les 5 s restent supposées. | Le délai d’attente d’un fill et de révision/annulation n’est pas modélisé. Le BBO ou un trade au prix limite ne permet pas de déduire si notre hypothétique ordre aurait été servi. |
| Spread | Il peut être décrit avec les cotations archivées, mais l’origine REST est trop tardive pour fixer le prix d’entrée. Le markout après réception REST d’ETH est une autre mesure que le markout depuis le fill. | IOC prend le côté exécutable du BBO; le spread est donc payé à l’entrée/sortie en plus des coûts de commission et du slippage configuré. Les archives HYPE ont de gros trous et des quotes très âgés; le moteur rejette les quotes périmés, mais ne reconstitue pas l’état du marché entre les trous. | Il faut fixer le prix de cotation, le déplacement du prix, le TTL et la politique d’annulation. Le spread capturé dépendrait de la sélection et du fill; aucun bénéfice de spread n’est constaté sans fill. |
| Frais réellement accessibles | Les frais signés de 67f7 appartiennent au compte source; ils ne sont pas le barème de notre compte. Le barème effectif de notre compte n’est pas dans le paquet. | Le JSON v5 configure 4,5 bps pour maker et taker; pour les IOC seuls le coût taker est pertinent. Ce paramètre ne prouve pas notre palier effectif. | Les frais maker/rebates sont dynamiques par volume, part maker, réductions de parrainage/staking et type de marché. Le barème effectif de notre compte au cutoff n’est pas enregistré et aucune rebate source ne doit être copiée. |
| Funding | Les écritures source sont ponctuelles et incomplètes; elles ne donnent pas le funding de notre position simulée. | L’engine comptabilise les événements funding reçus sur notre position virtuelle. Dans v5, aucun événement n’a été observé; l’absence n’est pas zéro. L’intervalle Hyperliquid est horaire. | Il faudrait le taux/temps de règlement et la position réellement simulée à chaque heure. Aucun fill de maker n’étant modélisé, ces expositions n’existent pas dans le paper actuel. |
| Minimum et granularité | Le minimum ou l’arrondi du compte source n’est pas un modèle de minimum pour notre ordre. | Pour HYPE, la variante gelée a `szDecimals=2` et un minimum d’ordre de 10 USDC. V5 a manqué 24 signaux sous minimum, plus 9 réductions sous minimum et 10 réductions arrondies à zéro. Un résidu sous-minimum peut empêcher la clôture. | Le minimum de 10 USDC et les tailles/price ticks s’appliquent aussi aux ordres maker; les décimales viennent de la métadonnée du marché et doivent être figées au cutoff. |
| Partiels et clôture | Les partial fills source existent dans les API, mais sans un ordre d’origine complet, ils n’identifient pas l’ordre non exécuté ou notre taux de remplissage. | Le modèle capte des partiels à partir de la profondeur affichée. V5 en a observé 4; il a choisi une taille complète avant simulation, mais n’a pas rempli partiellement l’ordre spécialement testé. La position finale est restée non flat. | Taille partielle, ordre encore ouvert et reliquat sont précisément les inconnues du modèle. Sans queue/ordres hypothétiques, toute clôture ou rebate fabriquée serait une fausse preuve. |

## Ce que les nombres permettent de dire

### HYPE / a880 : rebates historiques non transférables

Sur les 652 épisodes localement bornés, l’analyse attribue `−6,13149 USDC` au flux de prix, `−519,93765 USDC` au champ de frais signé (donc des rebates nets observés), et `+6,222528 USDC` au funding strictement attribué. La somme exploratoire après ces deux derniers champs est `+520,02869 USDC`. Les deux segments ont des résultats après frais/funding opposés (`+2 028,13` puis `−1 508,10 USDC`), les pages sont incomplètes et les queues censurées sont exclues.

Le turnover achat + vente correspondant vaut `46 236 051,72 USDC`. Sensibilité déterministe, avant funding et sans prétendre à un fill alternatif :

| Hypothèse de taux appliquée à tout ce turnover | Coût de frais | Flux de prix après ces frais |
|---|---:|---:|
| Maker base public, `+1,5 bp` par côté notionnel | `+6 935,41 USDC` | `−6 941,54 USDC` |
| Taker base public, `+4,5 bp` | `+20 806,22 USDC` | `−20 812,35 USDC` |
| Rebate maker conditionnelle, `−0,1 bp` | `−462,36 USDC` | `+456,23 USDC` |
| Rebate maker conditionnelle, `−0,2 bp` | `−924,72 USDC` | `+918,59 USDC` |
| Rebate maker conditionnelle, `−0,3 bp` | `−1 387,08 USDC` | `+1 380,95 USDC` |

Ce sont des scénarios de taux appliqués uniformément, pas une reclassification des fills source ni un résultat de stratégie. Le frais effectif net source, `−0,11245 bp` sur ce turnover, dépend du compte et de son mix maker/taker; il n’est pas portable. Le prix seul est légèrement négatif, et le bénéfice calculé vient surtout du frais source. Cela ne valide aucune rentabilité répétable.

### ETH / 67f7 : markout sensible à l’origine temporelle

Dans l’extrait rapporté, le markout directionnel médian à 60 s depuis l’événement est `+2,484 bp` pour les fills taker de réduction et `+1,275 bp` pour les ouvertures/inversions groupées. Depuis la réception de la page REST, il est respectivement `−0,414 bp` et `0 bp`. Les deux origines répondent à deux questions différentes; l’écart n’est pas une mesure du délai exact du fill ni un PnL.

Pour une échelle de coûts seulement, 2,484 bp représente `0,02484 USDC` sur 100 USDC. Le taux public de base taker est 4,5 bp par exécution, soit 9 bp pour une entrée et une sortie; les 5 bp de slippage configurés dans v5 ajoutent 10 bp sur deux côtés, avant le spread. Cela illustre l’ordre de grandeur, sans comparer un markout unilatéral au PnL complet d’une règle. Le résultat ETH ne supporte donc pas une règle économique de copie.

### Sensibilité de délai/cout du IOC gelé

À 100 USDC de notionnel de chaque côté, 4,5 bp de frais par côté valent `0,09 USDC` et 5 bp de slippage par côté valent `0,10 USDC`, donc `0,19 USDC` avant le spread et le funding. Cette sensibilité utilise les hypothèses de la config v5. Elle ne prouve pas que l’ordre aurait été rempli au prix de cette simulation ni que le délai fixe de 5 s correspond au trajet réel.

## Lecture des règles officielles Hyperliquid

- Un ordre `ALO` est post-only; un ordre `IOC` annule le reliquat qui ne s’exécute pas immédiatement. Le carnet suit une priorité prix-temps. Un snapshot public ne révèle pas notre rang dans la file. [Order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types), [order book](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-book).
- Le barème perp public de base est `4,5 bp` taker et `1,5 bp` maker. Le tarif maker devient une rebate seulement sous les seuils publiés de fraction maker à 14 jours. Le endpoint `userFees` expose le taux propre à un compte. Ces barèmes évoluent avec volume, referral et staking; aucun appel `userFees` n’a été fait ici. [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Info endpoint (`userFees`)](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint).
- Les perps sont réglés par heure; le paiement dépend de la position et du taux observés. Un funding absent des archives ne vaut pas zéro. [Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding).
- Pour les perps, l’ordre doit respecter les décimales de taille et les ticks de prix de la métadonnée; l’erreur officielle `MinTradeNtl` signale le minimum de 10 USD. [Tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size), [error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses).

## Plus petit manque concret et condition de reprise

Pour une future expérience IOC, la trace utile doit lier, dans le même épisode : réception WebSocket non-snapshot, règle/taille décidées, quote localement disponible, délai choisi, décision simulée de fill/partiel ou expiration, coûts, position restante et funding disponible. L’engine actuel contient plusieurs de ces éléments ; il faut vérifier leurs liens avant d'ajouter une collecte. Un aller-retour d'ordre réel auprès de la venue n'est pas un préalable au paper. Sans lui, le délai de soumission et le modèle de fill demeurent des hypothèses dont on doit mesurer la sensibilité. Aucun ordre réel n'est proposé pour combler cette limite.

Avant une nouvelle expérience, il faut figer la question économique (valeur incrémentale du suivi par rapport au cash et au HYPE hold), la fenêtre future, les frais observés ou les scénarios de frais, et le traitement des résidus. Le taux `userFees` de notre compte peut remplacer un scénario lorsqu'il est disponible ; son absence n'empêche pas un calcul hors ligne avec hypothèses affichées. La règle de signal de a880 v5 est déjà spécifiée ; aucune stratégie nouvelle n’est proposée ici. Les périodes v4/v5 et 67f7 restent fermées et leurs preuves intactes.

Revue de consolidation du 26 octobre : les pages officielles [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Order book](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-book) et [Order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types) ont été relues. Les taux de base utilisés dans les scénarios, la priorité prix-temps et les options ALO/IOC y sont documentés. Ces règles ne fournissent ni notre probabilité de fill passif ni une mesure de notre latence d'ordre.

Une décision future pourrait changer si cette observation démontre un résultat net positif **après** frais propres au compte, spread, slippage et funding, avec une clôture déterminée, et sans dépendre d’un seul bloc temporel. Une session à net négatif, un résidu non liquidable, des frais/timestamps inconnus ou une couverture trop faible laisserait la voie au statut rejeté ou indéterminé. Ces critères décrivent un seuil de décision pour une étude ultérieure; ils n’autorisent ni collecte, ni paper, ni ordre dans cette mission.

## Commande reproductible et portée

Reproduction du calcul de sensibilité à partir des artefacts déjà versionnés (aucune base opérationnelle requise) :

```sh
cd /home/Untergame/.worktrees/execution-feasibility-20261026
python3 - <<'PY'
turnover = 23118028.92543 + 23118022.79394
price_result = -6.13149
for name, rate_bp in (
    ("maker_base", 1.5), ("taker_base", 4.5),
    ("maker_rebate_tier_1", -0.1),
    ("maker_rebate_tier_2", -0.2),
    ("maker_rebate_tier_3", -0.3),
):
    fee = turnover * rate_bp / 10000
    print(name, f"fee={fee:.2f}", f"price_after_fee={price_result-fee:.2f}")
PY
```

Aucun script ou test n’a été ajouté : le livrable est l’analyse autonome. Aucun accès à la base, service, collecteur, quota, appel IA, paper ou ordre n’a été effectué. Limite principale : historique de fills incomplet et absence de latence d’ordre réelle/position de file; la vue YouTrack par ticket n’était pas accessible via les outils de cette session.
