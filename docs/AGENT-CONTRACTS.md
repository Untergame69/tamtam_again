# Contrats de recherche et de critique

La proposition de stratégie, sa critique et la mesure de rentabilité sont
séparées. Le contrat de proposition exige `strategy_spec` v2, type autonome ou
suivi, données effectivement observables, règles exécutables, coûts, horizon,
risque et critères de rejet. Les deux modèles peuvent vérifier sa cohérence ;
leurs accords ne sont pas deux preuves indépendantes d'un avantage.

Le runtime IA courant est suspendu par le code : le principal Unix partagé peut
lire la base brute. `workflow-tick` ne remet aucun run et `workflow-claim` refuse
le bail. Les instructions cron ont été réinstallées sur les jobs existants. La reprise
des appels IA reste subordonnée à l'isolation opérationnelle.

Avant toute reprise automatique, intégrer et vérifier un runtime qui reçoit
uniquement un paquet d'exploration immuable et le code explicitement permis.
Il ne doit pas pouvoir lire la base brute, les exports de comparaison/finale,
les résultats réservés, les anciens exports contaminés ou des outils qui les
rendent accessibles. L'absence d'outil filesystem/network dans un simple prompt
ne fournit pas cette garantie.

Chaque nouvelle entrée porte un fingerprint. Un échantillon inchangé ne relance
pas les modèles ; une correction précise requiert diagnostic, artefact nouveau
et budget restant. Mesurer coût et durée effectifs avant de réactiver cette
branche. Les limites sont dans le plan ; aucun booléen déclaratif d'isolation
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
