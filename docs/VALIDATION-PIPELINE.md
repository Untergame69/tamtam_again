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

Le dispatch Hermes historique et `workflow-claim` sont suspendus dans cette
version. Ces agents utilisent le même principal Unix que le collecteur et
peuvent lire la base brute. Une restriction de prompt ou un sandbox en lecture
seule ne cache pas les périodes réservées. Aucun booléen du plan ne réactive ce
dispatch. Sa reprise demande un véritable environnement d'agent isolé, puis
son intégration vérifiée : seuls les exports d'exploration et le code autorisé
doivent être lisibles, avec interdiction d'accès à la base, aux autres exports,
aux résultats réservés et aux outils permettant de contourner cette limite.
Cette intégration opérationnelle n'est pas réalisée par ce changement.

Le moteur déterministe fonctionne sans IA. Les nouveaux exports de recherche
refusent les requêtes historiques mélangeant exploration et réserve. Une ancienne
initialisation de ledger ne peut plus activer un paper N1.

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
s'applique aussi aux sessions N2. Le dispatch IA étant fermé, son coût est nul
et ses corrections sur une entrée inchangée sont interdites. Les paramètres de
budget IA du plan devront être reliés à des mesures effectives avant sa reprise.

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

Le timer/service `systemd/user/tamtam-again-paper.*` est installé et activé
localement depuis le 06/10/2026 ; `pipeline-tick` termine avec succès.
Le collecteur a été rechargé et ses nouvelles observations `streamHealth`
ont été relues en base. Aucun plan réel, variante réelle ou paper actif n'est
présent. Les crons Hermes existants portent les contrats suspendant le dispatch
historique. Bubblewrap masque la base brute lors d'un contrôle préliminaire ;
l'intégration et la vérification du runtime IA complet restent nécessaires.

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
