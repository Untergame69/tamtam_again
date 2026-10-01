# tamtam_again

Reprise séparée du travail d’analyse de marchés suspendu dans `polymarket/`.
Hyperliquid est la première source envisagée, mais le projet ne présume pas
qu’elle remplace les marchés événementiels de Polymarket.

## État

Le cadrage est suivi dans [TAMTAM_AGAIN-1](https://manhattam.com/work/issue/TAMTAM_AGAIN-1).
Le premier collecteur est suivi dans
[TAMTAM_AGAIN-5](https://manhattam.com/work/issue/TAMTAM_AGAIN-5), et l’étude
des sources de découverte dans
[TAMTAM_AGAIN-6](https://manhattam.com/work/issue/TAMTAM_AGAIN-6).

Voir [la note de faisabilité initiale](docs/FAISABILITE-INITIALE.md) pour les
constats, limites et prochaines décisions. Le plan de travail est organisé en
quatre étapes : collecte, analyse des stratégies, paper trading itératif, puis
sélection des candidats à examiner avant tout trading réel.

Le premier incrément de code et son modèle de données sont décrits dans
[docs/ARCHITECTURE-MVP.md](docs/ARCHITECTURE-MVP.md). Le ticket de collecte est
[TAMTAM_AGAIN-5](https://manhattam.com/work/issue/TAMTAM_AGAIN-5).

Le collecteur couvre maintenant le top 5 Hyperliquid par volume notionnel sur
24 h et les comptes classés sur le leaderboard public. Les cycles continus et
les commandes d’exploitation sont documentés dans l’architecture ; les réponses
brutes sont conservées dans SQLite, compressées et dédupliquées.

Les marchés propres à Polymarket (par exemple Up/Down et événements politiques)
restent hors du périmètre initial. Leur éventuelle transposition par des
instruments dérivés fera l’objet de l’étude
[TAMTAM_AGAIN-4](https://manhattam.com/work/issue/TAMTAM_AGAIN-4).

## Garde-fous de départ

- Lecture seule des données publiques ; aucune connexion wallet, clé privée,
  signature, dépôt, ordre ou exécution automatisée.
- Ne pas redémarrer les services et collecteurs de l’ancien projet POLY.
- Garder le code et les données de `polymarket/` intacts ; ce dépôt est isolé.
- Toute évolution doit avoir un ticket YouTrack, et être validée dans ce ticket
  une fois terminée.

Le service reste en collecte publique uniquement. Les observations et rangs ne
valident pas la rentabilité reproductible des comptes ; l’analyse et le paper
trading restent des phases à construire.
