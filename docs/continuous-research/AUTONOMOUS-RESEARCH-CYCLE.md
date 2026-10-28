# Boucle autonome — preuve de bout en bout

État au 28 octobre 2026 : **mission en cours, critère de fin non atteint**.
Cette fiche sera complétée par les identifiants du cycle réel ; une recette
synthétique ou une correction du worker ne suffit pas à le déclarer démontré.

## Preuves déjà obtenues

- Le worker de production a choisi six sujets les 27 et 28 octobre, dans les
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

## Conditions de fin encore à prouver

| Transition | État |
|---|---|
| Admission automatique d'un candidat | Observée sur six sujets |
| Hypothèse exécutable et critique persistées | Non démontrées sur le parcours nouveau |
| Règle et critères figés avant données nouvelles | Aucun nouveau plan réel |
| Évaluation interprétable sur ces données | Aucune évaluation réelle enregistrée |
| Résultat utilisé par la mémoire et la décision suivante | Tests intégrés ; preuve réelle attendue |
| Action suivante exécutée sans retouche du dossier | Progression descriptive observée ; cycle scientifique attendu |

Les enveloppes IA et les fenêtres prospectives existantes restent inchangées.
Le renouvellement quotidien n'efface aucun essai historique. Un scénario de
financement empirique éventuel exige une qualification explicite de ses limites ;
il ne peut pas être présenté comme un coût de venue exactement réconcilié.

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

Git : production publiée jusqu'à `7cd33ce` au dernier contrôle ; les corrections
sont encore dans `codex/autonomous-cycle-20261027`, avant intégration et déploiement.
Aucun nouvel ordre réel, lancement paper ou appel IA manuel n'a été effectué
pour ces corrections. Les collecteurs existants continuent de fonctionner.
