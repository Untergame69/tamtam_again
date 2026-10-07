# Recherche descriptive sur la population REST

Le paquet `population-descriptive-v1` est distinct des épisodes live du pilote.
Il contient la dernière fiche de périmètre disponible au cutoff : inventaire,
activité, profil descriptif multi-marché, mécanismes et limites connues. Champs
inattendus exclus, preuve account_scope_reports conservée, profil temporel
vérifié. Les comptes protégés sont refusés avant lecture des rapports.

Le paquet permet de poser une hypothèse falsifiable, une demande précise de
données, une non-identifiabilité ou une extension nécessaire. Il ne fournit pas
une règle validée ou un chemin d'exécution complet. Les fills REST ne deviennent
jamais des signaux follower live. Performance et reproductibilité restent
unproven, indépendamment d'un éventuel résumé favorable.

Commande :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-research-packet.py \
  --db data/tamtam.sqlite3 --address ADRESSE --as-of-ms CUTOFF \
  --max-chars 225000 --output /tmp/population-packet.json
```

225000 est un exemple de budget explicite, pas un minimum universel. Si la fiche
entière dépasse le budget, réponse needs_data avec taille nécessaire, aucune
troncature silencieuse. Une fiche sans activité peut être exportable mais ne
constitue pas à elle seule une raison d'appeler un modèle.

Contrôle réel : population-packet-control-20261007.json, 52 comptes hors réserve,
51 exportables et un dépassant le budget. Exemple fonctionnel : premier compte
lexical avec activité observée non nulle, trois marchés/1041 fills observés,
178790 caractères. Critère de choix descriptif explicite, aucun classement par
PnL. Paquet complet local /tmp/population-research-packet.json ; aucune archive
brute ou réserve lue, aucun appel IA.

Reste à raccorder : registre/quotas de requêtes indépendant du pilote, détection
de nouveauté pertinente, runtime isolé pour hypothèses ouvertes, revue,
routage vers famille d'expérience ou mécanisme unsupported, critères et nouvelles
fenêtres prospectives. La préparation IA existante reste liée au pilote ; ne pas
augmenter son budget global pour intégrer ces fiches. Aucun service modifié.

Tests : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p
'test_population_packet.py'`. Retour arrière ciblé du module/script ; conserver
les fiches et toutes les données de collecte.
