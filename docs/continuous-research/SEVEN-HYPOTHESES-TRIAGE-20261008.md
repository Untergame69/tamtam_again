# Tri des sept hypothèses réelles — 8 octobre 2026

## Statut et provenance

Document de proposition, aucune tâche nouvelle activée. Les sept résultats originaux restent immuables. Source : SEVEN-HYPOTHESES-SOURCE-20261008.json (request_id et hash exacts). Les chiffres ci-dessous sont des observations **rapportées par ces anciens dossiers**, pas une nouvelle vérification de leurs payloads. Aucun paquet ou résultat réservé n’a été lu pour ce tri. Chaque question réduite ci-dessous est une proposition de nouvelle tâche v1 attribuée au parent ; elle ne remplace ni n’allège rétroactivement son contrat de réveil.

## Capacité commune et limites

- Existant : population REST pour fills/funding/ledger, snapshots de positions et inventaire de compte ; population_orders.collect_orders pour historicalOrders et frontendOpenOrders sur un à trois DEX. Export causal à autoriser avant lecture, comptes pilotes exclus.
- Le worker de besoins structuré ne traite actuellement que les trois historiques et la preuve de pagination. Un collecteur orders existe mais son raccordement comme contrat de besoin automatique n’est pas livré. Ne pas marquer une demande order-lifecycle satisfaite par un snapshot.
- Capacité supplémentaire pour les hypothèses passives complètes : observations prospectives des décisions et changements d’ordres, continuité d’inventaire/non-trade, synchronisation marché ; conception d’un protocole puis adaptateur borné. L’existence d’un endpoint ne démontre pas la complétude du protocole.
- Privé/non établi : cible effective et signal du trader, délai client→ack du trader, priorité réelle de file, couvertures externes non divulguées. Plus de fills ne résout pas ces inconnues. Une cible estimée et figée est une nouvelle hypothèse, pas la découverte de la cible réelle.
- Future validation/exécution : règles figées, fenêtres prospectives, frais/funding, risque/collatéral et modèle d’exécution fidèle ; contexte optionnel pour la première jointure : carnets, external hedges, rendement global. Ils redeviennent nécessaires si la question porte précisément sur leur effet.

L’API publique fournit au plus2000 ordres historiques récents et des ordres ouverts ; elle ne promet pas tous les états intermédiaires. Fills temporels limités aux10000 derniers,2000 par réponse. Source officielle vérifiée : [Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint).

## Dossiers et prochaines décisions minimales

### D1 — 0x50c5132bbbe67357b74e115f9374d8a683439547 — HYPE, xyz:SP500

Parent `2291b04acf439159418ed17728f06666dc60e51bced96db75ef89a778de2b807` ; tâche proposée `triage-D1-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Les rafales HYPE proviennent-elles de plusieurs exécutions du même ordre, avec quantités compatibles avec son original ? |
| Observation minimale de discrimination | Joindre oid/tid et quantité des fills à origSz/side/type de quelques ordres récents ; identité et somme des tailles, sans inférer une cible. |
| Base déjà rapportée | 89 fills/8 ordres HYPE ;10/3 SP500 déclarés dans le dossier. |
| Collectable avec l’existant | Un rapport orders existe déjà (d4c0ad6d…, disponible1791373947355,1890 ordres historiques,2 ouverts, lifecycle_complete=false). Réutiliser ses données autorisées avant un nouveau coût ; deux appels orders standard au maximum pour une actualisation nécessaire ; ne pas exiger SP500 pour cette nouvelle question HYPE. |
| Capacité supplémentaire pour le mécanisme original | Réconciliation continue, règles de cible ou de liaison explicites ; observations causales des transitions. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; règles exécutables fidèles au mécanisme requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Confirmer ou invalider la concentration par ordre sur le sous-ensemble effectivement joint ; le contrôleur latent reste non identifié. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

### D2 — 0x570eb8d438bd209b0deeee3d2e0a8559f5d57fb7 — ETH, HYPE, NEAR

Parent `cdef25f13f1757102b07ee7c44dabf4d68d59e515abc8c28ffd872eeaf95408e` ; tâche proposée `triage-D2-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Les retours ETH à un inventaire non nul sont-ils compatibles avec des ajustements passifs plutôt qu’avec des enregistrements répétés ? |
| Observation minimale de discrimination | Identités distinctes des fills/ordres, position initiale vérifiable et réconciliation des quantités sur une excursion ETH ; garder les périodes manquantes. |
| Base déjà rapportée | 539 fills/14 marchés ; ETH48/48 maker déclarés ; excursions de41min à20,9h candidates. |
| Collectable avec l’existant | Deux appels orders standard ; fills/ledger et valorisations déjà collectés à vérifier sur la période choisie. |
| Capacité supplémentaire pour le mécanisme original | Observations prospectives d’ordres et inventaire causal ; cible/calibration séparée et contrôle marché. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; modèle passif fidèle requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Discriminer duplication et variation réelle ; causalité inventaire→quote reste non identifiable sans décisions de cotation et cible gelée. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

### D3 — 0x662823f3280bb67da4eec0c4195709caacf20215 — ICP, TRUMP, POL

Parent `eb8acf3b14a03ef185ecfb9dee93f840a74af01b92047d9cd8d384a0594620f7` ; tâche proposée `triage-D3-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Les quatre fills POL correspondent-ils effectivement à un ordre partiellement exécuté ? |
| Observation minimale de discrimination | Même oid, tid distincts, chronologie et quantité totale compatibles avec origSz ; retour historique de cet ordre ou diagnostic rétention. |
| Base déjà rapportée | 19 fills/9 marchés ; POL4 fills sur1ordre en2611ms déclarés. |
| Collectable avec l’existant | Deux appels orders standard ; pas besoin ICP/TRUMP pour ce sous-test POL. |
| Capacité supplémentaire pour le mécanisme original | Observations prospectives d’ordres et inventaire causal ; cible/calibration séparée et contrôle marché. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; modèle passif fidèle requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Confirmer structure partielle ou incohérence ; quatre fills ne deviennent jamais quatre décisions indépendantes. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

### D4 — 0x6cf4ddb4a311f0f6bbd2e9395bcd8c8b1511eb3d — ETH, NEAR, ZEC

Parent `980d0533c53008c3d57b363b4fb8e2c592e0aae0accaeb5518044ee8a84d7340` ; tâche proposée `triage-D4-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Les ajustements ETH augmentent-ils ou réduisent-ils le short existant ? |
| Observation minimale de discrimination | Deux fills ordonnés avec side/startPosition et snapshot initial/final reconciliés ; événements non-trade de l’intervalle. |
| Base déjà rapportée | Shorts ETH/NEAR/ZEC ;2fills ETH,1NEAR ; aucun fill ZEC fourni. |
| Collectable avec l’existant | Fills et ledger via collecteur historique existant ; deux appels orders standard facultatifs pour préciser le type. |
| Capacité supplémentaire pour le mécanisme original | Réconciliation continue, règles de cible ou de liaison explicites ; observations causales des transitions. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; règles exécutables fidèles au mécanisme requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Classer ajout/réduction/inconnu ; les bandes et cibles du panier restent non identifiées. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

### D5 — 0x7bfee91193d9df2ac0bfe90191d40f23c773c060 — io:OAI

Parent `369de9ec64e32525795254c63f6848286f16c2bae07c6344311048a6c10e7bfc` ; tâche proposée `triage-D5-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Le regroupement io:OAI en ordres partiels explique-t-il une part des rafales sans nouvelle décision à chaque fill ? |
| Observation minimale de discrimination | Joindre un sous-ensemble récent de139oid déclarés aux ordres ; vérifier tailles/identités et quantifier taux de jointure. |
| Base déjà rapportée | 250 fills maker/139ordres ;36ordres multi-fills et3excursions candidates déclarés. |
| Collectable avec l’existant | Deux appels orders avec dex io ; inventaire initial et ledger nécessaires seulement pour conclure sur les excursions. |
| Capacité supplémentaire pour le mécanisme original | Observations prospectives d’ordres et inventaire causal ; cible/calibration séparée et contrôle marché. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; modèle passif fidèle requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Établir structure des exécutions observées ; pas de preuve de rétroaction d’inventaire ni de rentabilité. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

### D6 — 0x878079c5f38051884f1b1d8fc2a61f328a6dae82 — CAKE

Parent `61393b387a1b9160aaed618c82a9b70ae4968931ef33b190eb00095afcc4b86b` ; tâche proposée `triage-D6-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Le fill CAKE isolé est-il compatible avec une exécution partielle d’un ordre passif ? |
| Observation minimale de discrimination | Ordre oid du fill, type/side/origSz et position initiale ; aucune inférence de répétition à partir de ce seul cas. |
| Base déjà rapportée | Un fill CAKE113,4 et position post-fill−100,9 déclarés ; aucun épisode complet. |
| Collectable avec l’existant | Deux appels orders standard ; si ancien oid absent, enregistrer rétention/inconnu sans accumuler arbitrairement. |
| Capacité supplémentaire pour le mécanisme original | Observations prospectives d’ordres et inventaire causal ; cible/calibration séparée et contrôle marché. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; modèle passif fidèle requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Vérifier un cas descriptif ; mechanism inventory response non identifiable dans ce dossier actuel. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

### D7 — 0xfc27136e42af1732ddc9ce2605ea9bff1b959d9d — xyz:BRENTOIL, xyz:CL

Parent `85dac04caa5251051ecabd4dc242e7def2f1480e49db927a36078b42483654f2` ; tâche proposée `triage-D7-v1` (non enregistrée).

| Champ | Proposition |
| --- | --- |
| Question falsifiable réduite | Existe-t-il au moins une modification réellement liée des deux expositions pétrolières ? |
| Observation minimale de discrimination | Transitions signées de chaque jambe, état avant/après et événement de funding disponible avant ; d’abord vérifier existence et chronologie des transitions. |
| Base déjà rapportée | Snapshot long BRENTOIL/short CL ;1fill résumé mais0fill accepté,1rejeté dans profil. |
| Collectable avec l’existant | Fills/ledger/funding existants et deux appels orders dex xyz ; résoudre ligne rejetée avant une comparaison causale. |
| Capacité supplémentaire pour le mécanisme original | Réconciliation continue, règles de cible ou de liaison explicites ; observations causales des transitions. |
| Informations privées/non observables | Cible et déclencheur réels, couverture externe, délais privés ; pas accessibles par pagination seule. |
| Future validation/exécution | Contrat autonome/suivi séparé, coûts et risque, fenêtres futures ; règles exécutables fidèles au mécanisme requis. |
| Contexte facultatif au sous-test | Carnet complet, couvertures externes, performance globale ; leur absence limite l’interprétation, sans bloquer une simple identité d’ordre. |
| Décision possible | Si aucune transition admissible : attente bornée ou non identifiable ; aucun effet funding déduit du snapshot. |
| Coût marginal proposé | 0 IA pour jointure déterministe ; 0 à2 requêtes orders, au plus140 unités réservées avant retries pour un DEX ; historiques supplémentaires bornés séparément. |

## Prochaine tranche réelle proposée — non activée

Question retenue : D1/HYPE, structure de partial fills ; D3/POL, contrôle contrasté peu actif. Choix fondé sur la question et les identités rapportées, sans classement de PnL. Les adresses complètes et parents sont ci-dessus. Admissibilité à revalider au démarrage : absence de réserve/pilote, autorisation des périodes, archive disponible, identités publiques ; si une adresse est protégée, arrêt sans substitution après lecture de résultat.

1. Créer deux tâches enfants explicites avant collecte et calcul : triage-D1-v1 et triage-D3-v1 ; original immutable, pas d’autorisation de promotion. Fixer cutoff et sous-ensemble déterministe : au plus20oid par compte, les plus récents de l’exploration autorisée, jamais sélectionnés sur résultat ou PnL.
2. Relire uniquement les réceptions déjà autorisées. Réutiliser d’abord le rapport orders D1 existant, après autorisation. Actualisation seulement si les oid choisis sont hors de son périmètre ou si la nouvelle question demande une date ultérieure. Au maximum une collecte orders par compte : historicalOrders + frontendOpenOrders DEX standard, donc au maximum4 requêtes initiales au total (possiblement2 seulement si D1 est exploitable sans actualisation). Sous réserve de revue, exécuter via client quota commun et bail population existant ; aucun abonnement WS supplémentaire ni nouvelle cadence globale.
3. Budgets proposés :4 requêtes logiques, au plus24 tentatives réseau si cinq retries existants par requête ; réservations cumulées au plus1680 unités (280 hors retries), distribuées par limite locale900/min, pas une promesse de débit. Poids calculés par code : historicalOrders120, frontendOpenOrders20 ; charge réellement facturée inconnue, journaliser la télémétrie. [Limites officielles](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).
4. Coût fournisseur supplémentaire0USD (public REST), pas d’achat ; CPU/temps de travail non facturés ici et non estimés comme0. Budget d’inférence de cette discrimination :0appel/0USD. Éventuelle proposition ultérieure : maximum deux appels isolés, réservation1USD/rôle, plafond2USD, uniquement dans une nouvelle tranche explicitement approuvée. Le plafond partagé de huit essais consommés reste inchangé.
5. Arrêt après un passage des deux comptes ou30min de durée murale, premier atteint. Pas de boucle permanente si oid absent/rétention. Saturation, identité ambiguë, absence de borne initiale : résultat inconclusif/observation manquante précise. Réponse échouée : diagnostic collecteur, conservation du résultat et aucune nouvelle inférence.
6. Sortie par compte : nombre d’oid admissibles, joints/non joints, ambiguïtés, somme des tailles versus origSz, timestamps et provenance. Incohérence démontrée invalide la proposition étroite ; cohérence confirme uniquement la structure du sous-ensemble. Pas de seuil statistique universel ni de conclusion d’avantage. Absence de lifecycle complet reste inconnue, pas un zéro.
7. Suite conditionnelle : si une question descriptive est tranchée, décider d’une nouvelle hypothèse comportementale prospective ou classement non identifiable. Pas de paper avant contrat et validation future. Tester l’adaptateur enfant et ses protections avant activation ; ce document n’est pas une configuration exécutable.

## Écart qualification → allocation et proposition minimale

allocation.py conserve performance=unknown/reproducibility=unproven et priorise inventaire, rotation et tirage déterministe. Les nouvelles mesures comptables ne pilotent donc pas les priorités. Sur le contrôle6h :14périodes/69 sélectionnées, zéro périmètre mesuré ; il serait incorrect de les classer par variation brute de capital.

Proposition à revoir avant implémentation : dans les slots deepen existants, priorité temporaire à une **question comptable résoluble** (ledger manquant ou événement à classifier avec bornes disponibles), avec motif, preuves, coût et expiration. Rotation max_deepen_epochs conservée. Exploration et témoins uniformes/classement conservés tels quels. Résultat inconnu reste inconnu ; aucune priorité économique sur des PnL de périmètres/durées différents. Mesurer ensuite le taux de questions effectivement résolues par unité de budget et publier les exclusions. Aucune politique générale d’allocation modifiée dans cette tranche.
