# Mémoire de recherche avec accès temporels

La bibliothèque research_knowledge conserve mécanisme supposé, origines,
périodes, preuves typées, expériences, conditions de réussite/échec, limites,
questions et liens. Statuts autorisés : hypothesis, observed_descriptor,
rejected_hypothesis et unsupported_mechanism. Aucun statut ne certifie un profit.
Les synthèses rédigées restent des affirmations à vérifier par leurs preuves,
jamais une nouvelle source indépendante.

Les identités dérivent du contenu canonique ; un même item ne se recrée pas
avec une date plus récente. Les anciennes versions restent enregistrées.
Les liens héritent explicitement de toutes les périodes des items précédents.
La présence d'un résultat rejeté ne l'efface pas de la mémoire.

## Frontières d'accès

Chaque période doit être entièrement passée à la date d'accès. Toute intersection
avec comparaison/finale d'un plan bloque écriture et export sauf libération
explicite de cette évaluation. Les observations de compte couvrent potentiellement
plusieurs marchés : leurs preuves exigent une période market="*", vérifiée
contre tous les marchés réservés de l'adresse, et non un sous-périmètre choisi.

Les preuves admises sont des évaluations terminales, items de connaissance
existants ou métadonnées d'observations account de la source population REST.
Le validateur ne lit pas les payloads. Il vérifie source, disponibilité, adresse,
réseau et containment des bornes. Un fichier arbitraire ne confère aucun accès.
Cela prouve les droits et le lien d'archive, pas la vérité sémantique d'une phrase.

Les tables research_period_releases conservent politique versionnée,
justification, délai choisi et date effective de publication. Une comparaison ou
finale doit être terminale et sa période terminée plus le délai configuré.
Une finale doit conserver son enregistrement consumed_holdouts. La libération
ne modifie ni le résultat initial, ni la réserve consommée, ni ses règles de
non-réutilisation en validation : cette période devient connaissance de
développement, jamais une nouvelle réserve vierge.

## Intégration IA

Les futurs paquets de research.prepare peuvent inclure les connaissances
pertinentes au compte/marché, créées et autorisées au cutoff exploratoire.
Leur taille est bornée ; elles ne tronquent pas les épisodes causaux. Les
paquets déjà scellés restent immuables, aucune reprise sur entrée inchangée
n'est déclenchée. Le modèle isolé reçoit uniquement ces items dans son paquet,
sans outil ni accès à la base. Les corrections de paquets anciens conservent
leur cutoff ; aucune connaissance publiée après ce cutoff n'est importée.

## Commandes explicites

```sh
PYTHONPATH=src .venv/bin/python scripts/research-memory.py --db data/tamtam.sqlite3 \
  --item connaissance.json --output /tmp/memory-write.json
PYTHONPATH=src .venv/bin/python scripts/research-memory.py --db data/tamtam.sqlite3 \
  --release-evaluation EVALUATION_ID --policy politique.json --output /tmp/release.json
PYTHONPATH=src .venv/bin/python scripts/research-memory.py --db data/tamtam.sqlite3 \
  --export-address ADRESSE --network hyperliquid-mainnet --market MARCHE \
  --as-of-ms CUTOFF --output /tmp/memory-export.json
```

La politique de libération exige version, justification et grace_ms non négatif.
Aucune politique réelle ou libération de pilote n'a été activée automatiquement.
L'ingestion automatique des profils, la revue des synthèses et l'évaluation de
leur utilité pour la recherche restent à compléter.

169 tests passent : période réservée, publication terminale, grace, conservation
du burn final, cutoff ancien, idempotence, budgets et chemins arbitraires.
Contrôle réel memory-control-20261007.json : un descripteur d'existence d'archive
population enregistré et exporté, aucune lecture de payload, zéro période pilote
libérée, zéro inférence et aucune qualification économique.

Rollback : arrêter worker recherche avant annulation ciblée du commit,
conserver tables et références. Ne pas supprimer consumed_holdouts pour annuler
une publication. Collecteurs et ledger paper restent indépendants.
