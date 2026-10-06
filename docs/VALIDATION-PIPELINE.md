# Validation de stratégies : état et exploitation

Cette implémentation sépare la description des comptes, la proposition de règles,
la mesure N1 et le fonctionnement N2. Une revue de modèles ne valide aucune
rentabilité. Le code Git est la référence ; les tickets 5, 6, 7 et 12 suivent les
changements et la recette réelle.

## État livré

Les modules `qualification.py`, `validation.py`, `engine.py`, `paper.py` et
`pipeline.py` ajoutent des tables sans supprimer les observations ou expériences
existantes. `cohort_membership_decisions` conserve les décisions futures de
sélection/exclusion ; `cohort-snapshot` conserve aussi les trois évaluations.
Les métriques non établies restent nulles : rendement corrigé des flux,
drawdown complet et dépendance de marché du compte ne sont pas inventés.

Le dispatch historique est désactivé ; le runtime v2 isolé est intégré et
contrôlé avec le véritable agent. `research-tick` prépare des plans prospectifs
puis exécute un job borné. Les plans initiaux et leurs corrections bornées concernent xyz:CL, XRP,
xyz:BRENTOIL et HYPE, avec comparaison de 24 h et finale de 48 h, séparées
par un embargo de 5 min. Ces durées sont des fenêtres pilotes configurables,
pas des seuils universels de maturité ou des preuves suffisantes.
Les quatre premiers runs needs_data restent archivés. Leurs corrections
d’export sont suivies dans TAMTAM_AGAIN-12 ; elles peuvent produire des variantes
figées, sans constituer une validation N1 ni autoriser le paper réel.

## Contrats et déroulement

1. Enregistrer un plan JSON avec `validation-plan plan.json` : fenêtres UTC
   demi-ouvertes exploration/comparaison/finale, embargo, critères et budgets.
   Pour des données réelles, comparaison et finale sont prospectives. Les données
   historiques déjà accessibles appartiennent au développement.
2. Enregistrer une variante avec `strategy-freeze PLAN_ID strategy.json`.
   La spécification v2 et les critères sont immuables et hachés. Modifier une
   règle ou un critère produit une nouvelle identité. Le gel précède la finale.
3. Exécuter `validation-evaluate VARIANT_ID --stage comparison`, puis `final`.
   Les événements réels proviennent exclusivement de l'archive locale. Les
   données synthétiques ne peuvent pas évaluer une variante réelle via la CLI.
4. `paper-start VARIANT_ID` exige une finale réelle passée. `paper-tick SESSION_ID`
   traite les nouveaux événements de manière transactionnelle. `pipeline-tick`
   automatise les évaluations arrivées à échéance et les sessions actives.
5. `pipeline-status` expose les versions, les évaluations et les motifs d'attente.
   `pipeline-decision diagnostic.json` permet rejet, non identifiable, attente,
   correction de collecte, reprise d'analyse ou suspension ; il ne promeut pas.

Tous les essais effectués par le moteur sont archivés, succès et échecs inclus.
La fenêtre finale entière est consommée **avant** le calcul, y compris en cas
d'erreur. Une entrée identique renvoie le résultat conservé. Une variante ou une
entrée différente ne peut réutiliser une réserve consommée du même compte ×
marché, même avec un autre plan. Il faut une nouvelle période future.

Les limites d'itérations et de durée sont appliquées aux évaluations ; la durée
s'applique aussi aux sessions N2. Le dispatch IA v2 enregistre les tokens,
la durée et le coût déclaré par le fournisseur. Un coût inconnu ou dépassant
la réservation bloque la suite. Une entrée terminée ou interrompue ne relance
pas les modèles ; le dispatch historique reste désactivé.

## Règles exécutables et limites

La v2 exécute deux familles : `follower/leader_delta` et
`autonomous/momentum`. Elle exige des règles d'entrée, sortie par horizon ou
cible, taille, exposition, perte et levier, frais, slippage, latence et exécution.
Une spécification descriptive v1 ou un signal arbitraire n'est pas exécuté.
Le suivi utilise la réception du fill public live, puis notre cotation et nos
coûts ; son prix d'entrée n'est pas le prix de la baleine. Les snapshots ne sont
pas des signaux. Le momentum autonome n'utilise aucun fill de baleine.

Le moteur conserve temps d'événement, réception locale et disponibilité dans
l'archive. N2 ajoute son délai de traitement réel : il ne prétend pas décider à
une réception ancienne. La cadence pilote du timer fourni est 5 secondes ; une
stratégie sub-seconde n'est donc pas démontrée exécutable par cette cadence.
Le dépassement de TTL produit une non-exécution et le retard maximal est mesuré.
Les frais, le funding et les prix avec spread/slippage passent une seule fois
dans la comptabilité perp. Le funding réglé par unité signée de position du
compte source est appliqué à **notre** position au moment effectif du funding.
Son paiement total n'est jamais recopié. Une observation manquante reste inconnue.

Les ordres market IOC sont bornés par une fraction configurable de la taille
visible. Le modèle passif prudent produit zéro exécution : prix touché et carnet
public ne donnent pas la priorité de file. Une amélioration de ce modèle exige
un mécanisme implémenté et versionné. Les résultats incluent cash et exposition
longue conservée avec une taille comparable comme références, plus coûts et
liquidité dégradés.

Les critères combinent PnL net, drawdown, blocs temporels, diversité des régimes,
concentration et incertitude. La borne normale par blocs est **descriptive** :
elle ne prouve pas leur indépendance. L'alpha est corrigé par le budget d'essais
prédéclaré. La durée des blocs doit être justifiée par les dépendances réelles ;
les catégories up/down/quiet sont un proxy causal configurable, pas une couverture
exhaustive des régimes. Les seuils des exemples synthétiques ne sont pas une
politique de validation réelle. Le compteur de cycles ouvre une exploration et
ne fournit jamais une preuve statistique.

Le retour à un inventaire initial non nul reste une excursion ; il ne représente
pas le PnL latent ou le risque du portefeuille de fond. Les anciennes observations
sans preuve de continuité gardent un diagnostic prudent. La collecte nouvelle
archive session, abonnements reconnus, pong et déconnexion. Un BBO inchangé dans
la même session saine reste utilisable ; une interruption invalide cette preuve.
Une absence de heartbeat ou une rupture suspend N2 et conserve le ledger.
Le redémarrage exige une nouvelle session explicite : les précédentes restent
consultables, sans remise à zéro silencieuse.

## Sources officielles vérifiées le 6 octobre 2026

[Subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
précise BBO uniquement au changement, L2 rapide cinq niveaux et lent vingt,
snapshots des flux utilisateur et funding. Le carnet public n'établit pas la file.
[Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
limite userFillsByTime aux 10 000 dernières exécutions et 2 000 par réponse.
Le préfixe ancien inconnu et le suffixe récent retourné sont désormais séparés ;
la pagination ne rend pas exhaustif un passé absent de l'API.

## Recette locale

Depuis le dépôt :

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tamtam_again validation-recipe --output /tmp/tamtam-validation-recipe
.venv/bin/python -m tamtam_again pipeline-status
```

La recette vérifie aussi reprise sur une nouvelle connexion SQLite et absence de
double comptabilisation sur des événements déjà consommés. Elle utilise une base
temporaire distincte, un compte `fixture-only`, un
marché `SYNTH` et `synthetic=true`. Elle exerce exploration, comparaison, finale
et le même reducer que N2. Son résultat porte `real_strategy_validated=false` ;
il ne démarre aucune session réelle. Elle ne remplace pas une observation N2
continue, ni une validation sur marché réel.

## Déploiement local et N3

Les timers `tamtam-again-paper.timer` (5 s) et
`tamtam-again-research.timer` (5 min) sont activés localement. Le collecteur
reste actif ; la base brute et les observations existantes sont conservées.
Les anciens crons de recherche/paper sont en pause pour éviter un double dispatch.
Le worker v2 est protégé par verrou de fichier et bail SQLite conditionnel.
Les appels interrompus consomment leur réservation et ne sont pas repris.
La nouvelle recherche n'expose jamais comparaison/finale aux modèles ; le moteur
`pipeline-tick` reste seul responsable des promotions réelles.

```sh
.venv/bin/python -m tamtam_again research-isolation-check
.venv/bin/python -m tamtam_again research-prepare
.venv/bin/python -m tamtam_again research-tick
systemctl --user status tamtam-again-research.timer tamtam-again-paper.timer
```

Le pilote réserve 1 USD par rôle, plafond 2 USD par plan, avant tout appel.
Les usages observés via l'abonnement Codex sont déclarés `included`, coût 0 USD ;
ils consomment néanmoins des tokens/quota. Une estimation n'est pas une facture,
et la réservation locale n'est pas un plafond de facturation imposé au fournisseur.
Le nombre d'appels, le volume d'entrée, la sortie et le temps sont bornés.
Le détail des paramètres est versionné dans `config/research-policy.json`.

N3 reste une répétition future : environnement cible, même version du moteur,
latence mesurée, reprise de processus, archive et ledger persistants, interruptions,
limites de risque, taille et coûts défavorables. Aucun VPS n'est déployé.

## Retour arrière

Le baseline du code et une sauvegarde SQLite cohérente sont conservés dans
`data/rollback/validation-20261006/` : `code-before.tar`,
`tamtam-before.sqlite3` et `state-before.json`. Les données brutes ne sont pas
modifiées par les nouveaux calculs. Préférer le retour du code ciblé, avec arrêt
préalable des seuls jobs tamtam_again et conservation des nouveaux registres.
Restaurer toute la base ferait perdre la collecte postérieure au snapshot : ne
pas l'effectuer pour annuler simplement cette évolution. Les nouvelles tables
peuvent rester en place et seront ignorées par le code antérieur. Conserver les
nouveaux fichiers dans une archive avant de les retirer. La sauvegarde SQLite a été relue et ses effectifs de comptes/runs vérifiés.
La restauration de production n'a pas été exécutée.

L'accès REST YouTrack local fonctionne. Les notes des tickets 5, 6, 7 et 12
sont publiées avec déduplication et relecture via
`scripts/publish-validation-notes.py --apply`. Elles distinguent mise en œuvre,
contrôles synthétiques et absence de validation réelle.

### Annuler uniquement l'activation de la recherche v2

Arrêter et désactiver `tamtam-again-research.timer`, puis arrêter son service.
Conserver les plans, runs et réservations en base ; ne pas restaurer toute la
base et ne pas réactiver le dispatch historique non isolé. Le collecteur et le
paper déterministe peuvent rester actifs. Les commits de code sont séparés
pour permettre une annulation ciblée après conservation des registres.

## Export causal complet et passage à N1

Les paquets schema v2 conservent des épisodes d'archive disjoints jusqu'à la
latence et l'horizon de sortie, plutôt que seulement les cotations précédant
quelques fills. Les montants et offsets temporels sont exportés sans arrondi.
Les prix après signal ne sont utilisables que comme résultats exploratoires,
jamais comme entrées futures du moteur. L'inventaire source observé avant fill
est fourni ; l'inventaire virtuel de notre stratégie démarre à zéro.

L'extension versionnée du budget d'entrée (225 000 caractères de paquet,
260 000 de prompt) sert à conserver des chemins complets. Les coûts, risques,
latence et critères de promotion restent inchangés. Les tokens effectivement
consommés sont enregistrés, même si l'inférence relève d'un abonnement.

Une règle acceptée par la critique est figée avant sa nouvelle comparaison.
`pipeline-tick` attend la fin de cette fenêtre avant de mesurer N1. Il n'utilise
pas l'ancien passé réservé pour accélérer une promotion ; aucun passage au
paper ne découle de la seule acceptation de la proposition.
