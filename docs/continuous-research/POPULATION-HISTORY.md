# Historiques REST indépendants — version 2

Les endpoints `userFillsByTime`, `userFunding` et
`userNonFundingLedgerUpdates` disposent chacun d'un curseur dans la table
additive `population_history_cursors`. Les anciennes observations restent
inchangées. Une nouvelle série commence au lookback choisi dans la politique,
sans hériter de la date de succès d'un ancien inventaire limité aux fills.

## Pagination et reprise

- Trois pages maximum par endpoint et passage, configurables de une à six.
- Le dernier timestamp est repris inclusivement. Les doublons aux bornes sont
  conservés dans les pages brutes puis dédupliqués pour le compteur d'activité.
- Une réponse de 500 lignes ou davantage est traitée comme potentiellement
  saturée : la limite générale porte sur des éléments **ou des blocs** et les
  fills peuvent atteindre 2000 lignes.
- Une saturation sans progression du timestamp produit
  `saturated_timestamp_unresolvable`. Aucun `+1 ms` ne saute ces événements.
- Une réponse mal formée ou hors fenêtre reste archivée et ne fait pas avancer
  le curseur. Une page sauvegardée précède toujours l'avancement du curseur.
- Le backlog garde sa borne finale jusqu'à épuisement de pagination ; une
  nouvelle requête ne remplace pas silencieusement cette borne.
- Les écritures de curseur vérifient le bail sous transaction. Un ancien worker
  ne peut écraser le progrès du nouveau.
- Un backlog ou une anomalie ramène le prochain passage à la cadence de reprise
  configurable, actuellement cinq minutes. Ce délai est un paramètre pilote.

`pagination_exhausted` signifie seulement que la pagination a rencontré une
réponse courte. Toutes ces observations portent `complete=false` et
`pagination_only_retention_unknown`. Une rétention tronquée, un préfixe ancien
absent ou une lacune ne deviennent pas complets à la fin d'une pagination.
La qualification comptable doit établir ses propres preuves de période.

## Charge et disponibilité

Au maximum neuf appels d'historique par passage avec la politique actuelle,
en plus de l'inventaire. Les réservations passent par le quota partagé du projet.
Le budget du passage ne borne pas à lui seul les retries HTTP du client ; le
timeout systemd de 600 secondes et le bail restent les bornes opérationnelles.
Une interruption conserve les pages et reprend leur borne inclusive.

Les tâches de télémétrie `population-rest-history_backfill` et
`population-rest-incremental` distinguent les historiques. L'inventaire conserve
`population-rest-overview`. La disponibilité d'un événement REST est toujours
l'insertion réelle dans l'archive, sans admission comme signal follower live.

## Sources officielles vérifiées le 7 octobre 2026

- [Info endpoint : pagination et limite des fills](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Perpetuals : historiques de funding et ledger, bornes inclusives](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)

## Vérification et retour arrière

```sh
.venv/bin/python -m unittest discover -s tests -q
systemctl --user status tamtam-again-population.service tamtam-again-population.timer
```

Arrêter le seul timer et service de population avant une annulation ciblée du
commit. Conserver les nouvelles tables et observations. Aucun collecteur de
marché, pilote réservé ou registre de variantes n'est modifié par cette migration.

La normalisation du ledger et du funding et la valorisation consolidée restent
à terminer. Cette étape livre leurs pages et les preuves de transport, sans
annoncer une qualification économique.
