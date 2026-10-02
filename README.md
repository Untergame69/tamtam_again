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

Le collecteur utilise le top 5 Hyperliquid par volume notionnel comme départ,
puis cible les cinq marchés les plus utilisés par sa cohorte stable de dix
comptes classés. Il conserve leurs fills live et les trades publics via
WebSocket, avec un carnet détaillé sur deux marchés, tout en gardant la collecte
HTTP pour compléter l’historique et vérifier les données.
Les réponses brutes sont conservées dans SQLite, compressées et dédupliquées.

Pour voir les comptes réellement couverts, les marchés utilisés et décider si
la période enregistrée suffit à démarrer un paper replay :

```sh
.venv/bin/python -m tamtam_again research-status
```

Les données déjà collectées sur les comptes non suivis restent archivées pour
permettre leur réévaluation. Seuls les comptes marqués `tracked` sont interrogés
en continu; les données archivées ne sont pas supprimées automatiquement.

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
