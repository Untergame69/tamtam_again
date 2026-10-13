# Activation IA limitée de la tâche v5 — 2026-10-13

## Autorisation et exécution

Tâche autorisée : `75c617af00435dab9bf1dd614aa5cbaddc26700446110affaaf7c781f0892746`.
L'autorisation dédiée `explicit-user-approval-2026-10-13-v5-75c617af` est liée à
cette tâche et à l'empreinte source
`4f199ebf17f5cb944fe6c7a44b317d363be655d63e2387bb1f23f7f744d064c4`. Elle
autorise au plus deux appels et réserve au plus 2 USD. Le plafond partagé est
resté à huit; les huit essais antérieurs restent comptés. Après activation, le
compteur indique neuf essais engagés au total, dont cette tâche v5.

Activation : `2026-10-13T12:19:31.162Z`. Le runtime isolé a terminé à
`2026-10-13T12:20:59.860Z`. Il a conservé le modèle `gpt-6.1-sol`, 120 secondes
par appel, 5 000 tokens de sortie par appel et la limite d'âge d'une heure à
partir de l'activation.

| Appel | Rôle | Entrée | Sortie | Durée | Coût déclaré |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | Proposition | 72 143 tokens | 1 698 tokens | 63,705 s | 0 USD, `included` |
| 2 | Critique, appelée car une hypothèse a été proposée | 72 942 tokens | 565 tokens | 23,961 s | 0 USD, `included` |

Coût total déclaré : 0 USD. Réservation consommée : 2 USD. Le registre indique
`calls_started=2`, `actual_cost_usd=0.0`, état d'autorisation `completed` et
résultat `needs_data`. Le rejeu du même runtime a rendu `unchanged_no_inference`;
le nombre d'appels est resté à deux.

## Résultat et décision

L'hypothèse proposée est que les seuils de valeur minimale et l'arrondi, les
refus de cotation et les limites de taille visible peuvent rendre le suivi de
cible dépendant de l'état déjà atteint. Des réductions manquées ou partielles
pourraient laisser une position jusqu'à la sortie par horizon, voire au-delà de
la limite du rapport.

La critique juge le mécanisme cohérent et testable, mais demande des preuves
supplémentaires pour attribuer les tentatives. Les refus agrégés ne disent pas
quelles réductions ont échoué ni leurs effets sur l'inventaire. Des liens
source→décision manquent ou ne sont que temporels; les fills 19 et 20 ont une
attribution ambiguë. La position résiduelle et une réduction en attente ne
constituent pas une clôture. Le financement et la continuité du flux restent
inconnus là où les traces événementielles manquent. Aucun résultat de
rentabilité n'est établi.

La route persistante est `needs_data`, avec l'action `collect observations
specified by decision`. Elle demande :

- les enregistrements canoniques par tentative, avec état avant/après, cible,
  ajustement non arrondi et arrondi, seuils, motif de refus, cotation, limite de
  profondeur, filiations de reprises et identifiants exacts de fills;
- les événements HYPE de cotation, profondeur et santé du flux, horodatés de
  l'événement au traitement, avec la cotation sélectionnée pour chaque tentative;
- les clés causales source→décision persistées, ou une déclaration que les clés
  historiques absentes sont irrécupérables;
- l'évolution de l'inventaire, de l'ordre en attente, des fills et du marquage
  jusqu'à la clôture observée ou à une borne explicitement censurée, avec la
  couverture de financement.

La collecte doit venir des archives locales du runtime paper et du carnet/flux.
La réponse n'a pas fourni de route d'acquisition ni de preuve d'adaptateur; le
système n'a donc pas lancé de collecte ni d'expérience supplémentaire. La
prochaine étape reste manuelle : rendre ces traces disponibles ou déclarer les
liens perdus irrécupérables. Le bilan et le réveil `missing_observations_available`
sont enregistrés pour reprendre sur ces preuves.

## Provenance conservée

- Le paquet `paper-outcome-research-v1` demeure inchangé. Son adaptation
  séparée `paper-outcome-to-runtime-v2` porte l'empreinte
  `a9ce0ea080b9b17af83387dd41ffe946da004126ee19a447ec61f8b5b2d49f8c`.
- Préparation : `1791885699939` ms; données disponibles : `1791877446807` ms;
  activation : `1791893971162` ms; âge des données à l'activation :
  `16 524 355` ms. Ces dates n'ont pas été rafraîchies.
- L'ancienne route `budget_required` reste dans le registre principal. La
  décision postérieure est une seule ligne dans l'historique de routes, liée à
  l'empreinte du résultat `3c6ca09e3051852362bc84d85756a20597c6ea079f52c7e75f219c240f55a393`.
- Aucun lancement paper, changement de session ou ordre réel n'a eu lieu.

Code de l'autorisation dédiée et de l'arrêt sans retry : commits `0aa3654`,
`96b5c98`, `656ca28`. Les tests ciblés correspondants ont passé (31 tests).
