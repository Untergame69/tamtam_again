# Faisabilité initiale — 1 octobre 2026

## Intention

Construire un processus indépendant pour repérer, comprendre et évaluer des
stratégies exécutées par des comptes on-chain rentables. Polymarket n’étant plus
une source exploitable pour ce projet, les sources et plateformes seront
évaluées séparément ; Hyperliquid est une première piste, pas un choix arrêté.
Cette reprise ne réactive aucun service POLY.

Le parcours visé est :

1. **Collecte** — constituer un historique vérifiable des comptes candidats,
   transactions et positions observables, avec les données de marché et les
   indicateurs propres à chaque blockchain ou plateforme.
2. **Analyse** — distinguer les stratégies qui semblent reproductibles des
   performances dues au hasard, à une période particulière ou à des biais de
   sélection. Documenter les hypothèses, coûts et limites des données.
3. **Paper trading** — simuler les stratégies à plusieurs niveaux de fidélité,
   du signal théorique jusqu’à une simulation intégrant frais, latence,
   liquidité et règles d’exécution. Les résultats d’analyse et de simulation
   alimentent des boucles de révision, de nouvelles hypothèses et de nouveaux
   essais.
4. **Sélection** — comparer les candidats sur des périodes et critères définis,
   conserver la provenance des mesures, puis retenir une liste courte pour
   revue humaine. Le trading réel est une phase ultérieure, avec validation
   distincte ; aucune transaction ne fait partie du cadrage ou des premiers
   incréments.

Hermes pourra orchestrer les cycles d’expérimentation et leur harness : chaque
itération devra conserver la version de stratégie, les données d’entrée, les
paramètres, les résultats et les motifs d’acceptation ou de rejet. Les capacités
réellement actives de Hermes restent à vérifier dans la configuration Git avant
de s’appuyer dessus.

Les marchés spécifiques à Polymarket, dont Up/Down et les événements politiques,
sont exclus du périmètre initial faute d’équivalent directement transposable.
Leur éventuelle représentation par des dérivés est une piste de recherche
séparée, sans supposer qu’elle soit possible, légale ou économiquement
équivalente. Elle est suivie dans le ticket
[TAMTAM_AGAIN-4](https://manhattam.com/work/issue/TAMTAM_AGAIN-4).

## Constats vérifiés

- La documentation Hyperliquid décrit une API publique. Ses exemples ciblent
  `https://api.hyperliquid.xyz` ; la documentation indique aussi l’endpoint
  distinct `https://api.hyperliquid-testnet.xyz` pour les essais.
- L’endpoint `info` documente des requêtes de marché telles que les mid-prices,
  les snapshots de carnet et les chandelles. Les requêtes portant sur les
  données d’un compte demandent une adresse utilisateur ; ce premier cadrage
  n’en a pas besoin. Les limites de débit et de rétention restent à mesurer
  pour le cas d’usage retenu.
- Hyperliquid documente du spot et des contrats perpétuels. Les perpétuels sont
  des dérivés sans échéance, financés périodiquement. Cela ne reproduit donc pas
  les marchés événementiels et probabilités de Polymarket.
- L’analyse POLY peut inspirer les traitements de données (marchés, échanges,
  positions et enrichissements), mais les objets et les questions métier
  devront être redéfinis pour Hyperliquid. Il ne faut pas migrer le pipeline à
  l’identique sans vérifier l’équivalence de chaque donnée.
- Les orientations UE de l’ESMA demandent de traiter les contrats perpétuels
  comme des contrats dérivés à examiner au regard de MiFID II. L’AMF rappelle
  que certaines offres de dérivés crypto réglés en espèces peuvent relever des
  instruments financiers et de règles d’agrément. En février 2026, l’ESMA a
  aussi rappelé que certains perpétuels à effet de levier peuvent relever des
  mesures nationales applicables aux CFD selon les caractéristiques du produit.
  Ce cadrage n’est pas un avis juridique et ne permet pas de conclure à lui seul
  si un usage particulier est autorisé en France.
- La documentation consultée ne suffit pas à établir les conditions actuelles
  d’accès depuis la France à l’interface ou aux activités de trading. Cette
  vérification est à faire avant toute utilisation autre que l’étude de données
  publiques.

## Proposition pour le premier incrément

Définir un schéma commun minimal pour les comptes suivis, leurs événements
on-chain, les positions observables, les instruments et les métriques de
performance. Puis produire un inventaire comparatif des sources candidates
(couverture historique, qualité, identifiants, limites de débit et coûts
d’accès) avant de choisir un collecteur pilote en lecture seule. Le collecteur
doit conserver les données brutes ou leur référence, les horodatages, la
provenance et les transformations appliquées.

Le premier prototype doit mesurer si les comptes et leurs résultats peuvent
être reconstruits de façon suffisamment complète. L’API de production et tout
accès nécessitant un compte restent à examiner séparément. Les tests de protocole
peuvent utiliser un environnement de test lorsqu’il existe, sans confondre ce
test avec une validation de stratégie.

Le premier harness d’évaluation devrait rejouer les signaux sur des données
historiques avec des règles explicites de sélection, de coûts et de disponibilité
des données. Le paper trading en flux réel viendra après cette étape. Hermes
servira à automatiser les itérations et à comparer les résultats, sans pouvoir
autoriser seul le passage au trading réel.

## Collecteur initial implémenté

Le ticket [TAMTAM_AGAIN-5](https://manhattam.com/work/issue/TAMTAM_AGAIN-5)
porte le collecteur public Hyperliquid et le registre de candidats. Le code se
trouve sous `src/tamtam_again/`; l’architecture, les commandes et les limites
sont dans [ARCHITECTURE-MVP.md](ARCHITECTURE-MVP.md). Le premier cycle réel a
enregistré les métadonnées et indicateurs de 234 perpétuels sur le DEX principal,
puis le top 5 par volume notionnel sur 24 h avec carnets et bougies. Le collecteur
évolue pour comparer aussi les autres DEX perpétuels et le spot dans un classement
unique. Le canal de classement public
a fourni 46 955 lignes; cinq comptes ont été retenus et leurs historiques,
instantanés de positions et portefeuilles ont été collectés. Les fenêtres de
fills les plus actives sont signalées incomplètes à la limite de rétention API.

Le classement est lu depuis le service de données utilisé par la page officielle
Hyperliquid. Cette route est non documentée et peut changer; elle est un canal de
découverte, pas une garantie d’exhaustivité ni une validation de performance.
Les observations réelles sont locales et ne contiennent pas de clé ou secret.

## Décisions encore ouvertes

1. Quelles blockchains et plateformes publiques offrent une visibilité utile
   sur les comptes, positions et historiques ?
2. Quels critères qualifient un compte de « performant » : période minimale,
   profit net, drawdown, volatilité, régularité, liquidité et coûts observables ?
3. Quels types de stratégies et horizons seront étudiés en premier ?
4. Quels niveaux et critères de sortie distingueront les étapes de paper
   trading, et comment éviter les fuites entre données d’entraînement et de
   validation ?
5. Quelles capacités Hermes et quel harness sont réellement disponibles dans
   l’environnement ?
6. Quel avis professionnel est nécessaire avant toute interaction avec des
   dérivés ou toute opération réelle ?

## Sources primaires consultées

- [Hyperliquid — API publique](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)
- [Hyperliquid — endpoint info et requêtes de données](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Hyperliquid — spécifications des contrats](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications)
- [ESMA — Guidelines on the conditions and criteria for the qualification of crypto-assets as financial instruments (décembre 2024), notamment §47](https://www.esma.europa.eu/sites/default/files/2024-12/ESMA75453128700-1323_Final_Report_Guidelines_on_the_conditions_and_criteria_for_the_qualification_of_CAs_as_FIs.pdf)
- [ESMA — Statement on derivatives within the scope of national CFD product-intervention measures (24 février 2026)](https://www.esma.europa.eu/sites/default/files/2026-02/ESMA35-243228190-8024_-_Public_statement_on_derivatives_in_scope_of_the_CFD_product_intervention_measures.pdf)
- [AMF — Analyse sur les dérivés crypto réglés en espèces et leur qualification (7 novembre 2025)](https://www.amf-france.org/sites/institutionnel/files/pdf/56953/fr/L%27AMF_considere_que_l%27offre_de_derives_sur_crypto-monnaies_necessite_un_agrement_et_est_interdite_a_la_publicite_par_voie_electronique.pdf)

## Suite

Faire tourner le service de collecte et surveiller sa stabilité, étudier les
limites de rétention et de pagination, puis bâtir la réconciliation et les
métriques de qualification. L’analyse, le backtest et les paliers de paper
trading restent à concevoir avant toute sélection de stratégie. Garder toute
décision de trading réel hors de ce cycle de recherche et de paper trading.
