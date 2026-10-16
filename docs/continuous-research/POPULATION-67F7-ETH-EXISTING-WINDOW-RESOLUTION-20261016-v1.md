# Résolution locale du bilan ETH — 2026-10-16

## Résultat

La tâche `501c352cd53c5a65ce3f035fe393ccdf15d640f418976b1a279b2d4bd248aece`
est passée de `needs_data` à `local_archive_analysis_complete` par le scheduler
existant. L’artefact déterministe complet est
[`POPULATION-67F7-ETH-EXISTING-WINDOW-RESOLUTION-20261016-v1.json.gz`](POPULATION-67F7-ETH-EXISTING-WINDOW-RESOLUTION-20261016-v1.json.gz),
empreinte `697a4b00d599d15fabbfa2ab530efd7fdfb24dfb162a49b6e3f7bc9440e65da1`.
Une seconde présentation a retrouvé cette empreinte avec l’état `unchanged`,
sans recalcul.

Le paquet de recherche restait inférieur aux limites existantes. Pour le bilan
intermédiaire réel `checkpoint_6h`, 2 031 fills (4 617 771 caractères) et la
couverture (21 505 121 caractères) donnent une projection autonome de 47 755
caractères. Avec le contexte historique, le paquet mesuré fait 89 096
caractères et le prompt 93 579, sous les limites de 225 000 et 260 000. Les
12 exemples sont distincts des statistiques calculées sur toute la population.
Le contrôle de 12 000 fills synthétiques répartis sur une journée passe aussi
par le scellement et le runtime simulé. Aucun rapport historique n’a été
réécrit ; les mesures détaillées sont dans
[`ETH-PACKET-PROJECTION-SIZE-CHECK-20261016.md`](ETH-PACKET-PROJECTION-SIZE-CHECK-20261016.md).

## Preuves locales retrouvées

L’intervalle d’événements est `[1791990000000, 1792076400000)`. Les 283 pages
REST complètes contiennent 9 874 fills uniques, joints exactement par `tid` au
bilan final ; 1 966 occurrences dupliquées ont été dédupliquées et aucun
conflit n’a été trouvé. La dernière page a été reçue après la fin de
l’intervalle : le cutoff de réception est donc `finalised_ms=1792076440179`,
tandis que les événements hors intervalle restent exclus.

Les archives livrent 844 306 événements carnet (684 948 BBO et 159 358 l2Book)
dans 437 338 lots. Les cotations de contexte sont strictement antérieures au
fill selon l’heure source ; les égalités d’horodatage restent ambiguës et sont
exclues. Les heures source, réception locale et archivage restent séparées.
9 835 fills ont les deux carnets antérieurs à 1 seconde, 9 868 à 5 secondes et
les 9 874 à 30 secondes. Une mesure de conditions de marché exige aussi son
contexte BBO de référence : 9 861 fills la satisfont au seuil descriptif de
30 secondes. Ce seuil décrit une couverture d’analyse, pas une limite paper.

Les 9 874 fills se reconstruisent arithmétiquement en un segment local, sans
rupture ni groupe d’horodatage invalide ou ambigu. Ses deux extrémités sont
censurées ; cette cohérence n’établit ni l’exhaustivité des pages ni la
continuité de toute la position. Les 6 724 ordres comprennent 1 786 ordres à
fills multiples (4 936 fills, jusqu’à 61 par ordre). Les fenêtres de résultat
à 60 secondes se chevauchent : 109 268 paires, jusqu’à 93 fenêtres
simultanées. Les fills ne sont donc pas des essais indépendants.

### Couverture et usage des données

| Données | Déjà dans le paquet IA | Utilisées par le calcul local | Écart ou exclusion |
|---|---|---|---|
| Fills du bilan | Statistiques complètes par maker/taker et effet de position, agrégats journaliers, frais signés, couverture et sensibilité des markouts ; 24 exemples distincts | 9 874 lignes rapprochées par `tid`; `oid` et les pages sources ajoutés depuis l’archive; regroupements par ordre, tranche de 5 minutes, jour, segment, sens et effet | Les 24 exemples ne sont jamais l’échantillon statistique. Tous les 9 874 fills alimentent les comparaisons locales. |
| BBO/l2Book | Comptes, lacunes, latences et références résumés; quelques cotations associées aux exemples | 844 306 événements / 437 338 lots recherchés; prédécesseur strict par événement et canal, spread, tailles des meilleurs niveaux, mouvements précédents et sensibilités d’âge | Aucun ordre relatif n’est supposé à timestamp égal. Les niveaux plus profonds ne sont pas déduits du résumé des meilleurs niveaux. |
| Résultats à 60 s | Agrégats complets du rapport et exemples bornés | Markout événementiel et markout après réception de la page REST gardés séparés pour les 9 874 fills | Les cotations futures servent uniquement aux résultats, jamais au contexte avant fill. |
| Disponibilité locale / décision | Réception, archivage, pages, connexions et gaps résumés, avec quelques détails d’exemples | Horloges source, frame reçue, lot archivé et requête/réponse REST conservés séparément; diagnostics de concordance locale | Pas d’horodatage de décision ni de calibration des horloges venue/local : l’accessibilité au moteur à l’instant réel de décision reste partiellement couverte et irrécupérable historiquement. |
| Placements et files | Absents | Non calculés à partir des exécutions | Ordres non exécutés, queue position et motivation privée ne figurent pas dans ces archives et ne sont pas inférés. |

Les comparaisons par spread, profondeur, mouvement récent, côté et effet de
position sont nouvelles sorties déterministes. Elles sont conservées dans
l’artefact local et le résultat persistant ; elles n’ont pas été renvoyées à
l’IA, puisqu’aucun nouvel appel n’était requis ni autorisé par cette tranche.

## Comparaison descriptive

Sur tous les fills, la médiane du markout directionnel événement→60 s est de
2,484 bps pour les takers qui réduisent la position (1 163 fills, 816 ordres),
contre 1,275 bps pour les ouvertures et inversions taker regroupées (995 fills,
800 ordres). En séparant les inversions, leur médiane est 0,851 bps ; les
ouvertures taker sont à 1,655 bps. À partir de la réception de la page REST,
les médianes deviennent respectivement −0,414 bps pour les réductions et 0
bps pour ouvertures/inversions regroupées. Cet écart de repère temporel empêche
de traiter le premier résultat comme une association robuste à la disponibilité
locale ou comme une règle de décision.

Au seuil strict d’une seconde, 9 835 fills sont couverts par les deux carnets ;
la médiane taker de réduction reste 2,484 bps (1 162 fills), tandis que celle
des ouvertures/inversions regroupées est 1,274 bps (994 fills). Les conditions
observables donnent 108 strates descriptives, mais les catégories sont
fragmentées et ne corrigent ni la dépendance, ni l’échantillonnage, ni les
horloges. Les markouts futurs servent uniquement de résultats, jamais de
contexte antérieur.

## Limites et suite

Les données archivées répondent aux demandes de jointure et de calcul
historique. Elles ne révèlent pas les placements non exécutés, la position
d’attente dans la file ou la politique de décision du trader. Les archives ne
permettent pas non plus de prouver que la cotation était disponible au moment
réel de chaque décision : aucun horodatage de décision ni offset calibré entre
horloges n’existe. Les comparaisons restent descriptives, avec sélection
incomplète et résultats chevauchants.

La route persistée conclut qu’aucune collecte historique supplémentaire ni
nouvelle inférence n’est justifiée. La question restante est la répétabilité
prospective de l’association conditionnelle sur des observations indépendantes
horodatées localement. Ce rapport ne lance aucune collecte, expérience paper,
ordre ou tâche IA.

## Vérification

- `tests.test_eth_report_projection`, `tests.test_research_work_queue` et le
  parcours synthétique de scellement/runtime : 11 tests réussis.
- `tests.test_eth_existing_window_resolution` : 3 tests réussis.
- `tests.test_population_local_join`, `tests.test_population_pilot` et
  `tests.test_research_work_queue` : 36 tests réussis.
- Passage scheduler réel : résultat `prepared`, 0 appel modèle, aucune collecte.
- Rejeu scheduler réel : `unchanged`, même empreinte, 0 appel modèle ; la ligne
  de file du bilan final reste `completed` après résolution.
- Le test d’intégration normal confirme aussi qu’un autre rapport prêt avance
  vers son état `waiting_data` pendant que cette résolution locale aboutit.
