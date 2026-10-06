# Contrats de recherche et de critique

La proposition de stratégie, sa critique et la mesure de rentabilité sont
séparées. Le contrat de proposition exige `strategy_spec` v2, type autonome ou
suivi, données effectivement observables, règles exécutables, coûts, horizon,
risque et critères de rejet. Les deux modèles peuvent vérifier sa cohérence ;
leurs accords ne sont pas deux preuves indépendantes d'un avantage.

Le runtime v2 s'exécute via `research-tick` dans un namespace Bubblewrap neuf.
Seuls le code runtime explicitement autorisé, Python et un répertoire temporaire
d'authentification sont montés. La base, les rapports, la mémoire Hermes,
les configurations globales, les outils MCP et les exports historiques sont absents.
Le client d'inférence utilise le réseau pour Codex ; le modèle reçoit zéro outil.
Le paquet passe par stdin et contient uniquement l'exploration scellée.
Un contrôle construit le vrai agent, vérifie zéro outil, l'absence de la base et
d'un témoin réservé, ainsi que le code en lecture seule. Il est répété avant
chaque nouveau run. Aucune exécution sans Bubblewrap n'est prévue.

Hermes propose et le backend Codex `gpt-6.1-sol` low critique dans une seconde
session neuve uniquement si une règle exécutable est proposée. Les deux rôles
utilisent le même modèle dans ce pilote : aucun accord n'est présenté comme
preuve indépendante. Le profil d'exécution et de risque ne peut être abaissé
par un modèle. La règle doit être gelée avant la comparaison prospective.

Le dispatch historique `workflow-claim` reste refusé. Les deux anciens crons
propres à tamtam_again sont en pause ; leur remplacement est le timer
`tamtam-again-research.timer`. Aucun agent de développement ne reçoit les données
de comparaison/finale par ce runtime.

Chaque nouvelle entrée porte un fingerprint. Un échantillon inchangé ne relance
pas les modèles ; une correction précise requiert diagnostic, artefact nouveau
et budget restant. Les tokens, coût déclaré par le fournisseur et durée sont conservés pour
chaque appel ; un coût inconnu ou excessif bloque la suite. Les limites sont dans le plan ; aucun booléen déclaratif d'isolation
ne suffit à autoriser une reprise.

Le paquet d'exploration doit séparer les fills disponibles avant décision, le
signal live du suiveur, les cotations recevables et les observations futures.
Une demande de données précise l'observation absente, la question tranchée et
la condition de réveil. Collecte défaillante → correction du collecteur ; mécanisme
inaccessible → non identifiable ; résultat net insuffisant → rejet ; hypothèse
ambiguë → reprise bornée avec question précise. Les seuils de cycles restent
exploratoires.

Le code gèle les règles et critères, mesure les périodes disjointes, consomme la
réserve, conserve les échecs et décide des promotions. N2 ne peut être créé par
une affirmation dans un commentaire ou un JSON rédigé par un modèle.

## Pilote prospectif borné

`config/research-policy.json` fixe quatre plans au maximum, un job par tick et
au plus deux rôles par entrée. Un paquet terminé ou interrompu n'est pas relancé.
Les demandes `needs_data` sont conservées avec l'observation manquante et la
question qu'elle permettra de trancher. Le pilote ne crée pas automatiquement
une révision d'un plan simplement parce que le temps passe : une reprise exige
un diagnostic précis, de nouvelles preuves ou une correction identifiée et un
nouveau budget explicite. Les réserves consommées restent interdites.

Les données transmises sont un échantillon descriptif borné, pas un rejeu complet.
Si le modèle demande un chemin de prix complet déjà présent dans la base, il
faut corriger cet export avant de demander davantage de collecte. Les quatre
premiers runs ont demandé notamment inventaire initial et épisodes causaux
complets ; ces demandes ne constituent pas une validation.
