# Paper expérimental — a880 / HYPE — 2026-10-12

## Décision d'exploration

**Oui, a880 justifie une recherche exploratoire**, sans qualification de rendement net. Au cutoff G2 `2026-10-12T07:16:34.195Z`, ses variations nominales déclarées sont positives sur les derniers points observés des horizons ciblés 30, 90 et 180 jours (+16 094.87 / +56 403.54 / +128 249.47 USDC). Les archives comptent 178 438 fills dédupliqués, cinq jours UTC actifs et 3.504 jours contigus avant épuisement du budget de pagination. Les pages sont incomplètes et ne couvrent pas la rétention historique. Le capital moyen, les flux complets, l'exposition consolidée et le rendement corrigé des flux restent inconnus. Le rapprochement d'une fenêtre courte du 8 octobre montre un retrait observé de 11 000 USDC et un résidu arithmétique conditionnel de −159.68 USDC; il n'atteste pas le compte dans son ensemble.

HYPE est le premier marché retenu car 32 921 fills (18.45 % du sous-échantillon) y sont observés, avec environ 46.4 M USDC de somme taille × prix. Ce total mesure le turnover observé, pas le capital, l'equity ni une exposition simultanée. Les directions incluent 7 962 ouvertures short, 7 507 clôtures short, 6 098 ouvertures long, 10 711 clôtures long et 643 flips. Une reconstruction prudente de la portion visible trouve 309 cycles avec position initiale nulle, médiane 247 s et p90 1 335 s. Cette statistique porte seulement sur les cycles identifiables dans l'archive tronquée.

## Hypothèse et version gelée

L'hypothèse est un **suivi de trades public**, pas une stratégie autonome : après réception d'un fill live HYPE non-snapshot, suivre sa variation signée à l'échelle 0.001. Le signal n'utilise ni snapshots ni prix d'entrée de a880. Les changements de position ultérieurs révisent la cible; l'horizon de sortie est 120 s. C'est une règle de recherche motivée par le turnover HYPE observé, pas une affirmation sur le programme réel de ce compte.

La stratégie, l'hypothèse et le plan sont figés dans `config/experiments/a880-hype-live-delta-v1.json`, `a880-hype-live-delta-hypothesis.json` et `a880-hype-live-delta-plan.json`. La taille est arrondie à 0.01 HYPE; l'ordre inférieur au minimum documenté de 10 USDC ne s'exécute pas. Le capital paper est de 1 000 USDC, le plafond d'exposition de 100 USDC, le levier maximal simulé de 1× et le plafond de perte/drawdown de 10 USDC. Le modèle de coûts utilise 4.5 bps taker, 5 bps de slippage, 5 s de latence déclarée, 10 % de la taille BBO visible, un âge de cotation maximal de 1 s et un TTL de 10 s. Une nouvelle position n'est pas ouverte si latence et horizon franchiraient la prochaine frontière horaire de funding; l'absence d'un funding observé n'est jamais traitée comme zéro. Ces paramètres sont des hypothèses prudentes de simulation; la latence n'est pas une mesure de production et la tranche de frais du compte n'est pas connue.

## Mode et bilan

Le plan est `experimental_paper_only`, budget IA 0 et sans évaluations exploration/comparaison/finale. Le pipeline N1 refuse explicitement ce mode; aucun résultat historique ne peut être marqué réussi et aucune promotion économique n'est possible par ce parcours. Le service paper détermine les fills virtuels avec le même moteur causal de réception, délai, BBO, coûts, financement reçu et limites. Une donnée manquante produit une attente, une exécution manquée ou un diagnostic visible. Aucun ordre réel n'est activé.

Le collector donne la priorité à une session paper active pour son compte et son marché, sans dépasser les plafonds existants de 10 comptes utilisateur, 30 marchés et 30 carnets. La première connexion WebSocket a une grâce explicite maximale de 180 s; après cela un heartbeat absent suspend l'expérience. Le timer paper existant ticke toutes les 5 s. Le bilan automatique est planifié toutes les 6 h : cette cadence représente de nombreux épisodes de l'ordre de la médiane historique HYPE de 247 s, tout en gardant un délai court pour examiner les pertes et la collecte. La durée maximale est de 7 jours.

Chaque bilan enregistre santé du flux, fills live, exécutions/misses/partielles, PnL simulé après frais et slippage, funding reçu (l'absence ne vaut pas zéro), exposition courante/maximale et limites d'observation. Il conclut par `continue`, `collect_data`, `abandon` ou `propose_new_version`; toute version suivante doit être nouvellement figée et ne peut utiliser que des observations postérieures.

## Activation et interruption observées

La version gelée `962aeb7821dcee4c1a1859ba8edca3947c163319a99b87c585fba1af61048307` a démarré le 12 octobre à `11:55:52Z`, session `4d28ca35fe7141e7aa77f56f1c95b08b`. Après correction de l'ordre de rotation des abonnements, le collecteur a redémarré à `11:59:09Z` et a donné la priorité à HYPE tout en conservant 10 comptes et 30 marchés. Les observations WebSocket postérieures au démarrage contiennent 72 frames `userFills` et 2 `userFundings` pour a880 jusqu'à `11:59:34Z`.

Le redémarrage du flux a toutefois interrompu la session paper après six signaux live. Le moteur a suspendu la session à `11:59:15Z` avec `connection_interrupted` et `missing_live_heartbeat`. Bilan automatique index 1 : zéro exécution, zéro position, zéro exposition maximale, cinq exécutions manquées (une expirée et quatre bloquées par la frontière de funding), PnL observé 0 USDC. Le registre et le ledger de cette version sont conservés; aucun ordre réel, appel IA ou budget supplémentaire n'a été créé. Le bilan recommande `collect_data`: vérifier une continuité fraîche BBO/heartbeat/fill avant de proposer une nouvelle version. La session n'est donc plus active et aucun résultat de rendement n'est revendiqué.

## Sources

- `economic-qualification-cards-20261012-g2.md` et `archive-reconciliation-a880-20261008.md` (qualification et limites).
- `data/tamtam.sqlite3`, pages `userFillsByTime` a880/HYPE jusqu'au cutoff; pages REST marquées incomplètes.
- Métadonnées HYPE fraîchement collectées `raw_observations:28248343` et `28248585` (précision, collatéral et marge).
- Docs Hyperliquid [tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size), [subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), et [API limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).
