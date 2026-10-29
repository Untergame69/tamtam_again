# Boucle autonome — preuve de bout en bout

État au 29 octobre 2026 : **mission en cours, critère de fin non atteint**.
Cette fiche sera complétée par les identifiants du cycle réel ; une recette
synthétique ou une correction du worker ne suffit pas à le déclarer démontré.

## Preuves déjà obtenues

- Le worker de production a choisi neuf sujets les 27, 28 et 29 octobre, dans les
  enveloppes de trois études/six appels par jour. Leurs décisions restent
  descriptives, `needs_data`, `unsupported_mechanism` ou `non_identifiable`.
  Aucun de ces résultats ne contient une règle exécutable revue.
- Une préparation réelle SOL a rapproché les 100 fills de sa fenêtre avec les
  BBO/l2Book, en 19,73 s ; paquet de 48 247 caractères, sans appel IA.
- Le nouveau lecteur REST+WS a retrouvé 79 617 fills sur un compte instrumenté,
  dont 13 observations WS récentes, contre 79 604 dans le seul historique REST.
  Les 13 ne sont pas déclarés signaux live : ils étaient présents dans des
  snapshots. La fenêtre WS de 24 h et l'historique REST sont nommés séparément.
- L'audit de financement en lecture seule a vérifié 25 lots sur neuf comptes
  non protégés. Six groupes marché/échéance BTC/ETH/HYPE présentent des rapports
  `usdc/szi` distincts et des timestamps légèrement après l'heure ronde. Leur
  égalité exacte et une frontière à la milliseconde zéro seraient des hypothèses
  invalides. Aucun résultat économique n'a été fabriqué à partir de ces écarts.
- Le contrôle en lecture seule du 29 octobre a retrouvé neuf appels conservés,
  le compteur historique partagé à 11/8 et zéro évaluation réelle. Les trois
  études du 29 ont été faites par l'ancienne version encore installée ; elles
  ne démontrent pas les corrections présentes dans la branche de travail.
- La préparation réelle vérifiée le 29 octobre produit un paquet ETH de
  204 998 caractères en 32,394 s et un prompt de 214 494 caractères, sous les
  plafonds inchangés de 225 000 / 260 000. La calibration vérifie 64 enveloppes,
  345 681 octets décodés et 113 coefficients du marché dans la fenêtre bornée.
  Les deux profils optionnels passent les contrôles de paramètres après
  projection. Aucun signal ou hypothèse n'a été inventé pour ce contrôle,
  aucun appel IA et aucun plan prospectif n'ont été créés.

## Corrections raccordées dans la branche de travail

La préparation associe les observations au contexte de marché strictement
antérieur, avec les horloges et les références. Un scénario versionné fournit
les coûts, le délai simulé, le capital et le risque ; il n'impose pas le signal.
Les métadonnées perpétuelles USDC sont reconstruites depuis leurs sources avant
compilation des règles de précision/minimum d'ordre.

Les observations WS descriptives enrichissent les statistiques sans devenir des
signaux de suivi REST. Le lecteur conserve les conflits et les limites de
ressources. Les duplications de transport et les formats décimaux équivalents
ne doivent pas créer de nouvel essai. Les réserves sont contrôlées avant lecture.

Le financement manquant, une exposition finale non résolue ou un échantillon
insuffisant ne sont plus interprétés comme un rejet économique. Un contrat peut
figer jusqu'à neuf témoins de financement supplémentaires, déjà collectés et non
réservés, pour le même marché USDC. Leurs paiements ne deviennent jamais des
signaux. Les périodes sources sont conservées dans les résultats et la mémoire.

La première étude quotidienne privilégie les observations exploitables d'un
compte déjà instrumenté ; les autres créneaux conservent la découverte et la
rotation. Cette priorité décrit la disponibilité des preuves, pas la rentabilité.

Le rejeu utilise désormais un index temporaire pour dédupliquer les identifiants,
sans modifier le ledger persistant. Le contrôle synthétique de performance donne
0,061 / 0,252 / 0,635 s pour 10 001 / 40 001 / 100 001 événements. Ce contrôle ne
prouve ni une stratégie ni le temps d'une évaluation réelle complète. Les lectures
historiques utilisent l'index compte/marché–temps existant, sans scanner tous les
marchés d'un même endpoint.

L'utilisateur a autorisé le 28 octobre un scénario de coûts prudent, **sans
promotion sur cette seule preuve**. Le scénario fige le plus grand coefficient
horaire absolu d'un échantillon autorisé borné comme débit symétrique sur notre
inventaire, quel que soit son côté. C'est une sensibilité choisie : ni borne
physique des coûts futurs, ni réconciliation des arrondis de la plateforme.
Les paiements observés et leurs désaccords restent séparés. Le scénario ne
modifie aucun quota ou critère et ne définit pas le signal de trading.

Ce profil est optionnel et figé avant les observations futures. Il interdit
sélection finale et paper, même si ses critères numériques passent. Une fois ses
comparaisons terminées et le délai de libération existant écoulé, sa finale
inutilisée peut être abandonnée administrativement : fenêtres et marqueur de
consommation conservés, aucune évaluation finale inventée et aucune réutilisation
comme réserve vierge. Les plans ordinaires gardent leur cycle initial.

Les 358 tests de régression pertinents ont réussi avant la dernière correction
de projection ; les 108 tests concernés par cette correction ont ensuite réussi.
Une revue indépendante a vérifié les frontières comptables et l'interdiction de
promotion, puis la projection, avec 61 tests ciblés et une compilation de fixture
identique avant/après projection. Ces contrôles ne remplacent pas le cycle réel.

## Conditions de fin encore à prouver

| Transition | État |
|---|---|
| Admission automatique d'un candidat | Observée sur neuf sujets |
| Hypothèse exécutable et critique persistées | Non démontrées sur le parcours nouveau |
| Règle et critères figés avant données nouvelles | Aucun nouveau plan réel |
| Évaluation interprétable sur ces données | Aucune évaluation réelle enregistrée |
| Résultat utilisé par la mémoire et la décision suivante | Tests intégrés ; preuve réelle attendue |
| Action suivante exécutée sans retouche du dossier | Progression descriptive observée ; cycle scientifique attendu |

Les enveloppes IA et les fenêtres prospectives existantes restent inchangées.
Le renouvellement quotidien n'efface aucun essai historique. Le scénario de
financement conserve ses limites explicites ; il ne peut pas être présenté
comme un coût de plateforme exactement réconcilié.

## Références et supervision

La [documentation du financement](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)
décrit une échéance horaire et un paiement fondé sur la taille, l'oracle et le taux.
Le coefficient par unité déduit d'un paiement est une construction de calcul ;
la règle d'arrondi des montants n'y est pas garantie.
Le [schéma WebSocket](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
distingue snapshots, fills et paiements de financement.

```sh
systemctl --user status tamtam-again-population-research.timer
journalctl --user -u tamtam-again-population-research.service -n 30 --no-pager
PYTHONPATH=src python3 scripts/verify_continuous_research.py --db data/tamtam.sqlite3 --output /tmp/continuous-research-proof.json
```

Git : les corrections sont intégrées à `main` et publiées jusqu'à `560a773` ;
la présente mise à jour documentaire les suit. Les deux timers ont été réactivés
après une intégration lorsque les services étaient inactifs. Les quatre unités
installées recherche/paper sont identiques aux fichiers versionnés ; les
collecteurs sont restés actifs. Les deux archives locales préexistantes et
`data/` restent non suivis et préservés.

Le contrôle après installation conserve neuf appels, 11 essais historiques
partagés et zéro évaluation réelle ; le rejeu des neuf tâches est sans inférence.
Le dernier passage de recherche terminé à 07:48:31 UTC précédait l'installation.
Le prochain passage naturel est annoncé à 08:03:31 UTC le 29 octobre ; il reste
à observer, sans le présenter comme déjà exécuté. Le quota des trois études du
29 est consommé ; son renouvellement reste le 30 octobre à 00:00 UTC, sans
réinitialisation anticipée ni nouveau budget. L'inférence et les futures mesures
restent à démontrer après ce déploiement.

Aucun nouvel ordre réel, lancement paper ou appel IA manuel n'a été effectué
pour ces corrections. Les collecteurs existants continuent de fonctionner.
