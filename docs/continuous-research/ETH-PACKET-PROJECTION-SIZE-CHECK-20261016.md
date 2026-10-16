# Vérification de taille des paquets ETH — 2026-10-16

## Résultat

La projection unique de `eth_report_projection.project` est utilisée par la file de travaux et par `seal_final_eth_observation`. Les statistiques sont calculées sur tous les fills ; les exemples sont une section distincte, bornée à deux lignes par jour × classe taker/maker × effet de position. Leur sélection dépend de l’identité stable du fill et de la strate, jamais de son prix, de ses frais ou du résultat.

La projection conserve les décomptes, agrégats de comparaison, couverture, lacunes, latences, limites, références, empreintes et quelques références d’exemples. Les inventaires détaillés ne sont pas copiés : leurs empreintes et références permettent de retrouver les archives conservées. Les champs nécessaires à la comparaison sont présents dans le paquet lui-même.

## Mesure hors ligne du bilan intermédiaire réel

Source : `67f7-eth-public-observation-24h-20261014-v1`, étape `checkpoint_6h`, empreinte d’entrée `dbee82b2616c5776961a7d740f393c54e08a235112f54ddd36a563ae1b058d23`. Il s’agit du bilan intermédiaire ; aucune valeur ci-dessous ne le présente comme final et aucun état de rapport n’a été modifié.

| Mesure | Caractères / effectif |
|---|---:|
| Rapport source JSON archivé | 26 901 871 |
| Fills (2 031 événements) | 4 617 771 |
| Couverture | 21 505 121 |
| Projection autonome, statistiques + couverture + exemples | 47 755 |
| Exemples sélectionnés | 12 |

L’empreinte sémantique est `2635afc233b71da8b28796a6c557bca6c46ad6f607d0304500de832486101c78` et l’empreinte de projection `9aa63284f3462949d773cd17b77af8220eb22a0500ba70ba73de1888f38f219c`. Le total des champs fills et coverage passe de 26 122 892 à 47 755 caractères dans la projection, sans tronquer le JSON.

Pour contrôler aussi l’enveloppe historique complète, la projection intermédiaire a été substituée hors ligne dans une copie du paquet déjà scellé, avec sa référence de rapport ajustée. Cette copie est une mesure de taille seulement, pas un nouveau paquet scellé : paquet complet 89 096 caractères et prompt proposition 93 579 caractères. Les plafonds concernés restent respectivement 225 000 et 260 000 caractères.

Le paquet final déjà conservé en base, qui inclut les éléments historiques, mesure 120 744 caractères ; son prompt proposition mesure 125 227 caractères. Ces mesures sont des lectures du travail existant, sans appel fournisseur ni nouvelle activation.

## Parcours simulé de volume

Le test d’intégration de scellement, file et runtime utilise 12 000 fills synthétiques répartis sur une journée UTC (pas de 7,2 secondes), plus 12 000 références de carnet. Il vérifie : statistiques sur les 12 000 lignes, exemples bornés séparément, projection identique dans la file et le paquet scellé, empreintes/références, taille du paquet complet avec le paquet historique de base, taille du prompt et exécution du runtime avec réponses fournisseur simulées. Le test n’utilise aucun appel IA réel.

Les plafonds restent inchangés : 225 000 caractères pour le paquet et 260 000 pour le prompt. Aucun rapport archivé, résultat, décision, quota ou autorisation n’a été réécrit.

## Tests ciblés

`python -m unittest tests.test_eth_report_projection tests.test_research_work_queue tests.test_population_pilot.PopulationPilotTests.test_final_eth_report_drives_v2_proposal_critique_and_persistent_decision -v`

Résultat : 11 tests réussis. Le traitement du vrai bilan final reste confié à la file automatique existante dans l’enveloppe déjà autorisée ; ce contrôle n’a appelé ni le runtime fournisseur ni le collecteur.

## Recontrôle de cette tranche

Le bilan `checkpoint_6h` a été relu depuis SQLite en mode lecture seule et reprojeté avec `eth_report_projection.project`. Les valeurs ci-dessus sont reproduites : 26 901 871 caractères pour le rapport source, 4 617 771 pour les fills, 21 505 121 pour la couverture et 47 755 pour la projection, avec 12 exemples. L’étape reste `checkpoint_6h`, jamais interprétée comme un résultat final.

Le paquet final déjà persisté a été relu sans écriture : paquet complet, historique inclus, 120 744 caractères ; prompt de proposition, 125 227 caractères. Le test d’intégration a également rejoué un jour synthétique de 12 000 fills et 12 000 références de cotations jusqu’au runtime à réponses simulées. La file et le paquet scellé portent la même projection ; les tailles complètes restent respectivement sous 225 000 et 260 000 caractères.

Reproduction ciblée :

```sh
PYTHONPATH=src python -m unittest tests.test_eth_report_projection tests.test_research_work_queue tests.test_population_pilot.PopulationPilotTests.test_final_eth_report_drives_v2_proposal_critique_and_persistent_decision -v
```

Résultat du recontrôle : 11 tests réussis. Aucune écriture en base, activation, nouvelle inférence ou collecte n’a été effectuée pendant cette vérification.
