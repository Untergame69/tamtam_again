# Consolidation des quatre missions — 26 octobre 2026

Les quatre livraisons sont réunies sur `integration/research-consolidation-20261026`, depuis `b579de1`. Les worktrees de mission et les fichiers opérationnels non suivis sont conservés. Ce document est le point de reprise ; les identités et états observés sont dans [la preuve compacte](CONSOLIDATION-EVIDENCE-20261026.json).

## Livraisons retenues et corrections

| Mission | Livraison | Revue et correction |
|---|---|---|
| Admission descriptive | `5c6d1f9` : évaluateur autonome, 2 533 décisions, 22 propositions admissibles, 320 à approfondir, 2 190 différées et 1 exclusion | `c5b52a1` : refus des collisions sortie/base et sorties entre elles, tolérance par ligne aux snapshots mal formés, date issue du cutoff. Artefact JSON compressé sans changer les octets décompressés : 12 188 551 → 695 266 octets. |
| Couverture | `e1beb28` : inventaire borné des comptes, fills, carnets, funding et périodes | `c14069a` : horloges source/locale non mélangées, funding des marchés sans fill inclus, plafonds visibles, identités conflictuelles exclues des métriques et chemins de sortie protégés. |
| Exécution | `f95bf25` : comparaison REST, WebSocket/IOC et maker/rebates | La consolidation précise que des scénarios explicites de frais/délais permettent une étude hors ligne ; ni un aller-retour d'ordre réel ni le tarif personnel ne sont un préalable universel au paper. Aucune nouvelle expérience n'est autorisée. |
| Cycle complet | `e36fc83` : test depuis observations brutes jusqu'au paquet suivant consommant la mémoire | `c38df57` : les écritures d'artefacts du premier traitement et du rejeu restent dans le répertoire temporaire. |

Les commits d'intégration reproduisent ces changements par cherry-pick ; les références ci-dessus identifient les livraisons d'origine. Aucune politique active, aucun service, quota, collecteur ou état opérationnel n'a été changé par cette consolidation.

## Ce que les résultats permettent de décider

L'admission proposée concerne une étude descriptive, pas une qualification de rentabilité. Son seuil 10 fills / 2 jours est une heuristique explicite ; les variantes 5/1, 20/4 et 40/6 donnent respectivement 48, 2 et 1 propositions mono-marché, contre 22 pour 10/2. Les 217 comptes multi-marchés suffisamment actifs restent à ventiler par instrument ; ils ne sont pas rejetés pour leur diversité. Cette proposition n'est pas branchée à l'admission de production.

Le rapport de couverture ne prouve pas onze jours de carnet continu. Son échantillon global plafonné couvre une courte fin de période ; le reste est inconnu dans cet inventaire. Les anciennes comparaisons de positions dépourvues de temps source ont été rectifiées en inconnues, avec la limite indiquée dans le manifeste. Cela ne signifie pas que les archives correspondantes sont absentes. Aucun nouveau scan massif n'a été effectué pour la revue.

Le test assemblé démontre sur base temporaire : observation → rapport → préparation du contrat et scellement → réponses fournisseur simulées → résolution locale → mémoire révisée → paquet admissible suivant. Les lecteurs et le fournisseur ne sont pas rappelés au rejeu. Cette preuve ne constitue ni une exécution fournisseur live ni une évaluation économique réelle.

ETH reste une tâche terminée : les résultats à l'heure source n'établissent pas d'avantage avec les pages REST étudiées. Le suivi live n'est pas réfuté, et aucune règle autonome n'est définie. La revue d'exécution ne justifie pas de relancer les anciennes variantes HYPE.

## Vérifications réalisées sur l'intégration

- 85 tests réussis en 27,400 s : admission, nouveau cycle intégré, observation ETH, contrat/résolution générique, pilote, mémoire, runtime, file, paquets, registre et pipeline.
- 13 tests de couverture réussis en 0,036 s après intégration des corrections de cette mission.
- Les tests de cycle utilisent SQLite temporaire et des réponses fournisseur simulées. Le premier résultat et le rejeu écrivent seulement dans leur dossier temporaire.
- Les deux outils de rapport protègent les entrées contre les collisions de chemins, y compris alias de fichiers.
- Les preuves opérationnelles ont été consultées en lecture seule, avec des requêtes bornées sur les registres ; aucun appel IA réel, acquisition, paper ou ordre n'a été déclenché.

Commande de reproduction ciblée depuis la racine (aucune base active nécessaire) :

```sh
PYTHONPATH=src python3 -m unittest tests.test_descriptive_admission tests.test_archive_coverage tests.test_population_research_cycle_integration tests.test_eth_prospective_observation tests.test_population_local_archive_resolution tests.test_population_pilot tests.test_population_resolution_memory tests.test_population_runtime tests.test_research_work_queue tests.test_population_packet tests.test_population_research tests.test_population_pipeline
```

## Décision restante et reprise

Le premier sujet proposé est **43ad / BTC** (`0xbb160cb61e694570f9d570f9fcde7c61dd2143ad`) au cutoff de présélection `1793009400000` : 165 055 fills observés sur 16 jours, et courbes déclarées positives sur les horizons mesurés de 90/180 jours. Les fills sont une borne inférieure ; le PnL déclaré n'est pas réconcilié au capital et les risques restent incomplets. La priorité vient de l'activité observée, pas d'un score de rentabilité.

La première question est une tabulation déterministe des jours actifs et de la couverture des pages BTC. Elle ne requiert pas d'IA. Une question de mécanisme ne devrait être soumise au modèle qu'après cette vérification.

L'enveloppe v2 conserve 2 appels utilisés sur 6 et 2 tâches sur 3, mais n'autorise que a880, 67f7 et be504. **Sa capacité numérique restante n'autorise pas 43ad.** Le goal interdit de changer les budgets et politiques économiques pour forcer une progression. Aucune permission d'étude du nouveau sujet n'a été ajoutée.

Une [proposition bornée prête à examiner](NEXT-DESCRIPTIVE-STUDY-PROPOSAL-20261026.json) contient l'adresse, le cutoff, les références et la question : un seul sujet, d'abord calcul local, puis au plus une proposition et une critique si une question nouvelle le justifie et si l'utilisateur l'autorise. Plafonds proposés : 2 appels, 160 000 tokens d'entrée, 10 000 de sortie, 240 secondes au total, usage abonnement sans réservation USD. Le document n'est pas une politique exécutable et ne donne aucune autorisation.

Recommandation : autoriser ce seul pilote descriptif, sans toucher à `economic_validation`, aux compteurs historiques, à la collecte ou au paper. Alternative plus large : arrêter une politique d'admission descriptive et son enveloppe totale avant de l'activer. Conserver les permissions actuelles laisse la collecte et les screenings fonctionner, mais n'ouvre aucun nouveau sujet IA.

Après décision : vérifier à nouveau les empreintes et l'autorisation des périodes, préparer l'étude avec les outils existants, puis consommer sa décision dans la file/mémoire. Arrêter avec un motif précis si les données ou le profil pris en charge ne suffisent pas. L'évaluation économique prospective reste une étape distincte, non autorisée par cette proposition.
