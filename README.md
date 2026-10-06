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
puis cible les vingt-six marchés les plus utilisés sur les dernières 24 heures
par une cohorte dynamique de dix comptes au maximum. Il conserve leurs fills
live, les trades publics et le meilleur prix acheteur/vendeur via WebSocket,
avec un carnet détaillé sur les vingt-six marchés suivis au maximum. Les paires
dont la rétro demande un échantillon cumulatif plus grand passent d'abord, puis
les demandes les plus récentes; les places restantes reviennent au classement
notionnel glissant sur 24 heures. Cela permet d'inclure les marchés récemment
actifs d'une baleine, sans suivre tous les marchés de la plateforme. La collecte
HTTP complète l'historique. Les fills et états
historiques des comptes sont réconciliés toutes
les 15 minutes afin de réduire le délai de validation des cycles observés en
live; cette cadence ne remplace pas le seuil de cycles exploitable par paire.
Chaque heure, les comptes sans fill observé depuis sept jours libèrent leur
place pour des comptes aux classements PnL jour/semaine positifs; leurs
observations restent conservées. Ce délai sert uniquement à faire tourner la
cohorte suivie : il ne fixe ni le temps d'attente avant une analyse, ni le
volume de données requis.
Les réponses brutes sont conservées dans SQLite, compressées et dédupliquées.

Pour voir les comptes réellement couverts, les marchés utilisés et décider si
la période enregistrée suffit à démarrer un paper replay :

```sh
.venv/bin/python -m tamtam_again research-status
```

Ce rapport mesure désormais la maturité par compte × marché à partir des
excursions de position complètes : un retour flat-à-flat ou le retour à un
niveau de position observé après une nouvelle ouverture. Chaque fill du cycle
est contextualisé par BBO. Le rapport indique le premier et le dernier fill de
chaque paire, ainsi que l'ancienneté du dernier, pour distinguer une collecte
active d'un marché devenu calme pour cette baleine. Il montre les prérequis
manquants; une ETA n'est affichée qu'à partir du débit de ce couple. Les paliers
de volume déclenchent la boucle : 5 cycles pour la première RE exploratoire,
10 puis 30 pour approfondir et 100 pour comparer. Le calendrier ne bloque pas son
avancement; si une RE demande plus de données, son seuil propre au compte et au
marché prend le relais. Si un avis demande plus de cycles et l'autre une nouvelle
analyse, le workflow collecte d'abord jusqu'au nouveau seuil : répéter la RE sur
le même échantillon ne comblerait pas ce manque. Les deux avis restent archivés.
Le seuil est un minimum : Hermes reçoit tous les cycles déjà disponibles au
déclenchement, jusqu'à 100 (ou jusqu'au seuil demandé s'il est supérieur), afin
qu'un cycle supplémentaire ne soit pas écarté.
Voir [TAMTAM_AGAIN-7](https://manhattam.com/work/issue/TAMTAM_AGAIN-7) pour la
définition de la maturité, et
[TAMTAM_AGAIN-12](https://manhattam.com/work/issue/TAMTAM_AGAIN-12) pour la
boucle Hermes et le paper trading N1.

Les tâches Hermes de rétro et de paper N1 s'installent avec
`scripts/install-hermes-crons.sh`. Elles ne démarrent une analyse qu'à la
présence d'un run admissible dans la file locale.

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

La collecte reste en lecture seule et les rangs ne valident pas une rentabilité
reproductible. Les jobs Hermes, la revue Codex et la file versionnée RE → Paper
N1 sont raccordés; ils restent inactifs tant qu'aucun couple n'a le volume
d'excursions complètes et contextualisées requis. Le contrôle continu des instances
Paper N1 reste hors périmètre pour l'instant.
