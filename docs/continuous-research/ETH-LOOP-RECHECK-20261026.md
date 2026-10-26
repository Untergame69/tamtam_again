# Recontrôle de la boucle de recherche ETH — 26 octobre 2026

Ce relevé complète la clôture du 16 octobre sans modifier le bilan, la décision,
les mémoires ni les paquets précédents. Le contrôle opérationnel a été fait le
26 octobre à 13:46, heure de Paris, sur la base courante avec la commande :

```sh
PYTHONPATH=src python3 scripts/population-research-tick.py \
  --db data/tamtam.sqlite3 \
  --policy config/population-research-policy.json \
  --pilot-policy config/research-loop-pilot-v2.json \
  --prepare-only --max-jobs 1
```

Le résultat complet du tick a été conservé temporairement hors du dépôt pendant
la vérification. Il indique `model_calls: 0`, aucune résolution locale nouvelle,
aucun travail avancé et `no_admissible_candidate`. La tâche ETH
`501c352c…aece` reste `completed` dans la vue courante ; sa route terminale est
conservée. La décision persistée reste celle de
[la clôture du 16 octobre](ETH-DECISION-CLOSURE-20261016.md).

## Motif d’absence d’une nouvelle tâche

Dans l’allocation non renouvelable `research-loop-pilot-20261014-v2`, le
scheduler a évalué :

- `a880` : `unchanged_no_inference`, mêmes question, cutoff d’archives et
  empreinte du contenu des fills ;
- `67f7/ETH` : `terminal_route`, route `completed` ;
- `be504` : `unchanged_no_inference`, mêmes question, cutoff et empreinte des
  fills.

L’allocation reste distincte du plafond général : deux tâches sont déjà
persistées, deux appels ont été réservés et quatre appels au maximum restent
dans l’enveloppe autorisée. Aucun de ces appels disponibles n’a été consommé.
Le tick n’a ni réarmé ni dupliqué une tâche.

La voie générale a réévalué 32 candidats : 0 qualifié, 0 autorisé et 0 avec
budget disponible. Les 32 présentent de nouvelles données selon ce contrôle,
mais 26 échouent la qualification historique et 6 attendent la revue
économique distincte du filtrage courbe/activité. Le registre partagé compte
11 travaux engagés pour un plafond de 8. Les causes sont séparées : la nouvelle
preuve seule ne lève ni la qualification ni le plafond.

La file courante reste à 4 travaux `completed`, 3 `technical_required` et 9
`waiting_data`. Aucun travail en attente n’a bloqué l’évaluation des candidats ;
ce tick n’a simplement trouvé aucune entrée admissible à faire avancer.

## Règle d’admission descriptive encore manquante

La voie générale ne dispose toujours pas d’un état explicite de préparation à
la recherche descriptive. La règle minimale proposée dans la clôture reste
distincte de toute validation économique : prescreen documenté, question bornée
par compte/marché/période, preuves autorisées et observables, empreinte
sémantique nouvelle, et autorisation de ressources applicable. Elle n’est pas
implémentée ni appliquée par ce recontrôle. Elle ne devrait autoriser que la
recherche descriptive, jamais le paper ou le capital.

## Preuve de raccordement préservée

Le passage réel du 16 octobre reste la preuve positive de transition : la
résolution locale terminée a remplacé l’état actif `waiting_data` par
`completed`, l’historique brut est resté conservé, une mémoire versionnée a
relié question, preuves, conclusion, inconnues et prochaine action, et un paquet
ultérieur a effectivement sélectionné cette mémoire sans être envoyé à l’IA.
Le tick du 26 octobre prouve séparément la reprise idempotente : même résultat,
aucun nouvel appel, aucune nouvelle tâche et aucune modification du bilan ETH.

Le cas où un autre travail avance pendant qu’ETH est terminale est couvert par
les tests simulés déjà consignés dans la clôture ; il n’est pas présenté ici
comme une transition réelle. Les huit tentatives historiques, toutes les
décisions antérieures et les deux tâches du pilote v2 restent intactes.

Les détails structurés du tick, ses empreintes de route, les liens de mémoire,
les lignes brutes/courantes de file et le compte rendu des 80 tests figurent
dans [la preuve JSON](ETH-LOOP-RECHECK-20261026.json). La route conserve quatre
versions historiques ; la file brute en garde cinq lignes, tandis que sa vue
courante n’expose que la ligne terminale.
