# Activation bornée du paquet d’analyse locale v5 — 2026-10-13

Paquet autorisé : `paper-local-evidence-research-v2`, fingerprint `466cd04d8d5a33f5593fbfba455d23492db648cc83cf9655e92441b1899777d9`. Enfant : `9dda3827e578bd17992a67dafd9849596a4a9b3119c8f3756d3468bd665f804a`, parent v5 `75c617af00435dab9bf1dd614aa5cbaddc26700446110affaaf7c781f0892746`.

## Activation et issue

Une autorisation dédiée a été liée à cet enfant et à cette empreinte exacte. Le mode est `subscription`, avec au plus deux appels, 80 000 tokens d’entrée par appel, 160 000 cumulés, 5 000 tokens de sortie par appel, 10 000 cumulés, 120 secondes par appel et 240 secondes cumulées. Aucun montant USD n’a été réservé ; les champs `reserved_cost_usd` sont nuls. Le plafond partagé et les autorisations des anciens enfants n’ont pas changé.

Activation : `1791897257576` ms; disponibilité de l’archive conservée à `1791877446807` ms. Le prompt de proposition mesurait 220 908 caractères, sous la limite configurée de 260 000. Le runtime a engagé un créneau d’appel puis terminé `suspended` avec `ValueError`. L’autorisation indique `calls_started=1`; la tâche n’a donc pas été relancée. Aucun résultat de proposition valide ni critique n’a été persisté. `usage_json=[]`, `actual_cost_usd=NULL`, et le résultat d’usage conserve des coûts et tokens inconnus — ce n’est pas un coût nul démontré.

Le code passe le contrôle de longueur du prompt avant l’appel isolé; les autres `ValueError` du contrat abonnement portent sur les métadonnées d’usage retournées (statut de coût, présence ou limites des tokens). Cela suggère un échec à la validation de l’usage après le chemin fournisseur, mais le type seul sauvegardé ne permet pas de déterminer quel champ a échoué ni de reconstituer l’usage. Cette inférence est distincte d’une preuve d’un appel facturé. Aucun retry n’a été fait. La nouvelle route persistante est `suspended`, diagnostic `ValueError`, action : résoudre l’échec de contrat avant tout nouvel essai expressément autorisé.

Une nouvelle connexion a rejoué `paper_runtime.run` : `unchanged_no_inference`. `calls_started` est resté à 1 et la route répétée est identique. Le créneau restant n’a pas été utilisé; aucune critique ne pouvait être demandée sans proposition valide.

## Ce que les archives montrent

La fenêtre conservée est `1791875646458`–`1791877446807` ms. Elle contient 521 occasions paper, 11 707 BBO, 3 323 l2Book, 60 heartbeats, 30 abonnements et 234 fills source. Le registre classe 492 occasions comme manquées, 25 exécutées et 4 partielles. Parmi les motifs enregistrés : cotation indisponible 350, cotation périmée 84, sous minimum de valeur 24, ajustement nul après arrondi 15, ajustement de réduction nul après arrondi 10 et réduction sous le minimum 9. Ces catégories décrivent les motifs consignés par le moteur; elles n’établissent pas qu’un signal refusé aurait été rentable.

Pour 434/521 occasions, l’âge de réception enregistré est au plus une seconde. L’archive a une disponibilité antérieure à la décision pour 521/521, contre 169/521 pour le champ de disponibilité alors enregistré; les deux instants concordent pour 0/521. Il y a de un à six contenus de carnet candidats par occasion. Le paquet démontre donc une forte présence de motifs liés aux cotations et un désaccord d’horodatages; il ne prouve pas quelle cotation précise a piloté chaque décision.

## Conclusion sur la question

- **Démontré :** les raisons d’indisponibilité/péremption dominent les échecs consignés (434 occurrences); les archives BBO/l2Book existent et permettent de décrire les occasions, leur réception et leur disponibilité d’archive. Les petites réductions sont aussi parfois classées sous minimum ou nulles après arrondi.
- **Hypothèse :** les seuils de valeur minimale, l’arrondi, la fraîcheur/admissibilité des cotations et la profondeur visible interagissent avec l’inventaire et la cible pour retarder ou empêcher certaines réductions. Les données rendent cette explication plus précise comme liste de mécanismes observables, mais ne départagent pas leurs effets causaux.
- **Non reconstructible rétrospectivement :** les liens exacts événement source → décision → cotation sélectionnée → ordre → fill pour chaque occasion. Les identifiants causaux n’ont pas été enregistrés; les rapprochements par temps restent ambigus. La clôture et le résultat final de v5 sont également inconnus : sa borne est censurée avec `-0.61 HYPE` et une réduction en attente. Cette session virtuelle suspendue ne se clôturera pas par une collecte Hyperliquid ultérieure.
- **Observations prospectives nécessaires :** une trace par décision avec IDs d’occasion/décision/événement source; snapshot BBO ou meilleur niveau l2Book effectivement choisi (prix, quantités, connexion et référence d’archive); horodatages événement, réception, disponibilité, décision et traitement; motif d’admissibilité; taille d’ordre choisie, fill(s) liés, reliquat et inventaire avant/après. Un point terminal pré-déclaré doit marquer l’inventaire ouvert comme censuré si le parcours paper n’atteint pas une clôture observée. Le besoin de fermeture future ne rouvre pas v5.

## Recommandation et état de reprise

Ne pas lancer d’expérience paper sur la base de cette activation : aucune réponse IA validée n’existe, donc aucune nouvelle hypothèse exploitable n’a été produite. Conserver l’hypothèse issue de v5 comme non établie et orienter la correction suivante uniquement vers la conservation du motif détaillé d’échec du contrat d’usage (sans secrets ni prompt) avant toute nouvelle autorisation. Pour une expérience ultérieure, instrumenter les liens causaux ci-dessus et pré-déclarer son point terminal; ne pas redemander les liens historiques absents ni attendre la clôture impossible de v5. Toute nouvelle activation ou expérience reste manuelle et doit avoir son autorisation propre.

Le rapport et le rectificatif de préparation antérieurs restent inchangés : [rectificatif paquet v2](V5-LOCAL-ARCHIVE-RESOLUTION-RECTIFICATIF-20261013.md), [rapport de préparation v1](V5-LOCAL-ARCHIVE-RESOLUTION-20261013.md). Aucun lancement paper, ordre réel, appel critique ou retry n’a eu lieu.
