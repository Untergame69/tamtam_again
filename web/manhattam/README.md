# Comptes Hyperliquid sur l’accueil

Le collecteur publie déjà `docs/tamtam-whales.json`. Le lien symbolique public
`api/tamtam-whales.json` expose uniquement cette cohorte d’adresses publiques,
avec ses liens Hypurrscan et les rangs disponibles. Rafraîchissement au chargement.
La revue détaillée est un relevé ponctuel daté, pas un statut recalculé en direct.
Les comptes sortis restent dans la base, mais disparaissent de la liste active.

Publication autorisée sur l’accueil existant :

```sh
python3 scripts/publish-manhattam-cohort.py --html-root /home/Untergame/supervision/html
```

Aucun redémarrage de service. Le fichier HTML initial est sauvegardé dans
`data/rollback/manhattam-*/index.html`. Pour revenir en arrière, restaurer cette
copie et retirer les deux JSON `/api/tamtam-*` et `/assets/tamtam-cohort.js`.
Le fichier `docs/tamtam-whales.json` et la collecte sont conservés.

Les chiffres de `clearinghouseState` sans dex portent sur les perpétuels standards.
Un capital nul dans ce périmètre ne prouve pas l’absence de capital sur HIP-3.
La revue ne constitue ni un filtre de promotion ni une validation de stratégie.
