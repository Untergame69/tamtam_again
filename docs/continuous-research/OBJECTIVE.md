**Objectif du Goal**

Faire évoluer `tamtam_again` vers une recherche continue sur une population large de comptes publics Hyperliquid :

**Découverte → qualification progressive → identification de comportements → hypothèses → évaluation prospective → paper → surveillance et révision.**

La recherche doit pouvoir découvrir des comportements inconnus, notamment sur plusieurs marchés. Les limites du pilote actuel — dix comptes, marché unique, horizon de deux minutes et familles de signaux restreintes — ne doivent pas devenir des hypothèses universelles.

Effectuer les travaux autorisés, les vérifier, puis produire un compte rendu détaillé pour une revue indépendante par l’autre agent. Ne pas considérer ses propres validations comme une approbation finale.

**Contexte et règles de travail**

- Lire `/home/Untergame/youtrack/AGENT-START.md`, l’index documentaire, puis les articles pertinents de `TAMTAM_AGAIN`.
- Consulter les tickets `TAMTAM_AGAIN-6`, `TAMTAM_AGAIN-7`, `TAMTAM_AGAIN-12` et leurs commentaires récents. Les descriptions anciennes peuvent être dépassées.
- Vérifier le code, les configurations et l’état réel avant toute modification.
- Vérifier les capacités et limites des API dans leurs sources officielles.
- Conserver les données existantes, les historiques de décisions et les essais échoués.
- Préserver les variantes et périodes réservées des pilotes CL, XRP, HYPE et BRENTOIL. Ne pas consulter leurs données réservées pour concevoir les nouvelles règles.
- Rester en collecte publique et paper local. Aucun ordre réel, wallet, clé privée ou nouvel abonnement payant.
- Préparer et chiffrer les besoins éventuels de VPS ou de fournisseurs. Leur achat et leur déploiement externe ne font pas partie de ce Goal.
- Faire des changements progressifs, avec migrations compatibles, tests pertinents et retour arrière documenté. Éviter une réécriture générale.

**1\. Établir un état initial et un plan d’exécution**

Recenser précisément :

- candidats découverts, comptes suivis et provenance ;
- endpoints interrogés, cadences, quotas et abonnements ;
- couverture des marchés et des comptes ;
- stockage, charge machine et retards de traitement ;
- familles de stratégies réellement exécutables ;
- plans, variantes et évaluations en cours, sans lire les observations réservées.

Séparer les limites officielles, les limites du code, les paramètres du pilote et les hypothèses non vérifiées.

**Livrable :** diagnostic initial, dépendances entre travaux, ordre d’exécution et état des pilotes à préserver.

**2\. Mesurer la capacité réelle de collecte**

Instrumenter ou compléter les mesures suivantes :

- poids REST consommé par endpoint et par tâche ;
- pagination, erreurs, limitations et reprises ;
- connexions, abonnements et adresses WebSocket ;
- débit reçu, retard de traitement, files d’attente ;
- croissance du stockage et coût des calculs.

Distinguer rattrapage historique et collecte incrémentale. Estimer la capacité soutenable selon plusieurs fréquences de suivi, en conservant une marge pour les reprises.

**Livrable :** budget de collecte mesuré et calcul de capacité reproductible. Ne pas déduire une capacité du seul nombre maximal annoncé par l’API.

**3\. Découpler la population étudiée des dix abonnements utilisateur**

Séparer explicitement :

- registre de découverte ;
- comptes interrogés périodiquement en REST ;
- comptes disposant d’un abonnement utilisateur en direct ;
- comptes en analyse ;
- stratégies en évaluation ou en paper.

Remplacer le couplage actuel entre cohorte et plafond WebSocket par un ordonnanceur configurable. Les cadences doivent dépendre de l’activité, du risque de dépasser la rétention et des besoins de recherche.

Conserver le moment réel de disponibilité : un fill récupéré par REST ne doit jamais être présenté comme un signal reçu en direct.

**Critère d’acceptation :** le système peut qualifier plus de dix comptes dans les quotas disponibles, sans prétendre leur fournir à tous la même observation en temps réel.

**4\. Ajouter une découverte indépendante du classement**

Exploiter les participants des flux de trades par marché pour alimenter le registre.

Conserver :

- source et date de découverte ;
- marché d’origine ;
- couverture de la fenêtre observée ;
- règle d’échantillonnage et version ;
- provenance multiple lorsqu’une adresse est retrouvée ailleurs.

Dédupliquer par adresse, sans favoriser automatiquement les comptes produisant le plus de fills.

Prévoir une couverture diversifiée des marchés et un budget d’exploration indépendant de la cohorte actuelle. Conserver le classement comme source complémentaire et comme référence de comparaison.

**Livrable :** au moins deux voies de découverte fonctionnelles et comparables, avec leurs biais documentés.

**5\. Étudier les comptes dans leur ensemble**

Pour chaque candidat, inventorier son activité publique accessible :

- perpétuels standards et HIP-3 ;
- spot ;
- sous-comptes et relations explicitement documentées ;
- mode de compte et organisation du collatéral ;
- marchés fréquentés et positions simultanées.

Découvrir une adresse sur un marché doit pouvoir déclencher l’examen de ses autres marchés.

Ne pas fusionner des comptes sur une simple ressemblance de comportement ou un transfert. Conserver les rapprochements incertains comme hypothèses.

**Livrable :** fiche de périmètre par compte, indiquant ce qui est observé, manquant ou extérieur à notre visibilité.

**6\. Rendre la qualification comptable fiable**

Construire une qualification sur des périodes explicites et comparables :

- capital et positions aux bornes ;
- PnL réalisé et variation du latent ;
- frais, devises de frais, remises et funding ;
- dépôts, retraits et transferts ;
- autres revenus identifiables ;
- exposition et trajectoire de risque.

Tenir compte des modes de compte Hyperliquid et éviter le double comptage du collatéral partagé.

Réconcilier les variations de valeur avec les flux. Calculer rendement corrigé des flux et drawdown seulement lorsque les données le permettent.

Une réponse d’API présente ne constitue pas une preuve de complétude. Une métrique impossible à établir doit rester inconnue, avec une explication et une action possible.

Commencer par quelques cas contrastés pour vérifier les calculs, puis appliquer automatiquement la méthode à tous les candidats disposant des données nécessaires.

**Livrable :** rapport de qualification reproductible, avec écarts de réconciliation, couverture et incertitudes.

**7\. Ajouter une préétude des comportements et des marchés**

Produire des descripteurs sans présumer la stratégie :

- durées de détention et excursions d’inventaire ;
- activité passive/agressive ;
- fréquence, tailles et regroupement des exécutions ;
- exposition directionnelle et concentration ;
- opérations coordonnées sur plusieurs actifs ;
- changements de marchés, de rythme ou de dimensionnement.

Pour les marchés, documenter les mécanismes nécessaires à l’analyse : funding, liquidations, liquidité, précision, références de prix et particularités HIP-3.

Distinguer observation et interprétation. Une simultanéité ne prouve pas un arbitrage ; plusieurs marchés ne prouvent pas une stratégie supérieure.

**Livrable :** profils descriptifs et liste d’hypothèses testables, avec les données supplémentaires nécessaires.

**8\. Définir une allocation progressive du budget de recherche**

Séparer :

- critères empêchant une évaluation ;
- résultats défavorables ;
- informations inconnues ;
- priorités de collecte ou d’analyse.

Conserver les évaluations performance, observabilité et reproductibilité séparées.

Distribuer les ressources entre approfondissement des candidats connus et exploration de nouveaux profils. Éviter qu’une bonne couverture historique donne une priorité permanente.

Créer des cohortes datées et des témoins comparables pour évaluer la valeur ajoutée de la sélection, notamment face au classement public.

**Livrable :** politique versionnée, décisions explicables et conservation des comptes retirés. Aucun seuil arbitraire présenté comme universel.

**9\. Remplacer les paramètres uniques par des profils d’expérience justifiés**

Distinguer :

- paramètres imposés par le marché ;
- capacités mesurées de notre système ;
- budgets de risque choisis ;
- paramètres propres à une hypothèse.

Permettre des expériences bornées sur plusieurs horizons, tailles et délais. Documenter leur justification et enregistrer toutes les variantes essayées.

Mesurer la sensibilité des résultats aux coûts, au retard et à la liquidité. Séparer délais réellement mesurés et délais simulés.

Préserver les paramètres des pilotes déjà figés.

**Livrable :** profils expérimentaux configurables et traçables, permettant de déterminer dans quelles conditions une hypothèse pourrait fonctionner.

**10\. Élargir le harness au-delà des deux familles actuelles**

Examiner les restrictions du moteur et introduire un contrat d’extension clair pour les stratégies, les données nécessaires et les modèles d’exécution.

Ajouter un état explicite : **« hypothèse intéressante, mécanisme non pris en charge »**.

Prévoir l’évaluation de règles portant sur plusieurs instruments : positions, financement, exposition agrégée, disponibilité de chaque marché, exécutions partielles et risque d’exécuter une seule jambe.

Implémenter une première capacité minimale de ce type, avec une règle de référence explicitement expérimentale et des tests comptables. Elle sert à vérifier le moteur, sans présumer sa rentabilité.

**Livrable :** extension démontrée, limites documentées et absence de rejet économique causé uniquement par une incapacité du moteur.

**11\. Construire la boucle d’adaptation continue**

Formaliser les transitions :

**nouvelle information → diagnostic → proposition → comparaison → promotion paper ou rejet → surveillance.**

Distinguer les déclencheurs :

- données supplémentaires pertinentes ;
- correction de collecte ;
- changement apparent de comportement ;
- dégradation de performance ;
- hypothèse nouvelle.

Définir à l’avance les règles de suspension, de remplacement et de retour à une version précédente. Éviter les changements incessants déclenchés par quelques résultats bruités.

Conserver les versions immuables et attribuer correctement les positions et résultats lors des changements.

**Livrable :** parcours automatique vérifié jusqu’au paper, avec reprise après incident et sans promotion fondée sur le seul avis d’un modèle.

**12\. Évaluer le harness comme un système adaptatif**

Ajouter une évaluation chronologique de la procédure entière :

- informations accessibles à chaque décision ;
- candidats et variantes examinés ;
- versions sélectionnées ;
- périodes d’attente ;
- coûts de recherche et de changement ;
- résultats agrégés, y compris les échecs.

Comparer la procédure à des références simples : absence d’adaptation, règles fixes et sélection témoin lorsque cela est pertinent.

Organiser l’accumulation des connaissances : une ancienne période évaluée peut devenir disponible pour une recherche ultérieure selon une règle explicite, mais son résultat initial reste conservé et elle ne redevient jamais une période vierge.

**Livrable :** évaluation reproductible de l’adaptation, sans réécriture rétrospective des choix.

**13\. Organiser la mémoire de recherche**

Conserver une bibliothèque structurée :

- mécanisme supposé ;
- comptes et marchés d’origine ;
- données et périodes utilisées ;
- expériences effectuées ;
- conditions de réussite et d’échec ;
- limites d’exécution ;
- questions ouvertes et liens entre hypothèses.

Permettre aux agents de réutiliser les connaissances autorisées sans accéder aux périodes encore réservées. Les synthèses IA doivent pointer vers leurs preuves et conserver leur statut d’hypothèse.

**Livrable :** mémoire exploitable pour proposer progressivement nos propres stratégies, avec contrôle des accès temporels.

**14\. Préparer une décision de montée en capacité**

Comparer à partir des mesures obtenues :

- REST plus large et moins fréquent ;
- flux mutualisés par marché ;
- collecteurs répartis sur plusieurs IP stables ;
- fournisseur de données ;
- nœud propre si pertinent.

Pour chaque option, préciser capacité attendue, coût, couverture, latence, maintenance et risques de perte de données.

Préparer si utile le découpage des responsabilités entre collecteurs, la déduplication et la provenance. Ne pas déployer de flotte de VPS ou acheter de proxies pendant ce Goal.

**Livrable :** recommandation chiffrée et architecture concrète, avec les incertitudes à lever avant dépense.

**15\. Vérifier, documenter et produire le compte rendu**

Exécuter les tests pertinents, notamment sur :

- comptabilité et transferts ;
- comptes unifiés et périmètres multiples ;
- déduplication et pagination ;
- interruptions, reprises et quotas ;
- horodatages et absence de fuite temporelle ;
- positions sur plusieurs instruments ;
- promotion, suspension et changement de version ;
- conservation des essais et périodes réservées.

Distinguer tests synthétiques, contrôles sur données réelles et résultats prospectifs encore en attente. Ne pas abaisser des critères pour terminer le Goal.

Mettre à jour les tickets pertinents et la documentation opérationnelle, sans y recopier tous les journaux. Produire des commits cohérents et un retour arrière praticable.

**Le compte rendu final doit contenir :**

- état initial et état livré ;
- tableau de chaque tâche : terminée, partielle ou bloquée, avec preuve ;
- commits, fichiers, migrations et services modifiés ;
- mesures de capacité avant/après ;
- critères et paramètres retenus, avec justification ;
- tests exécutés et résultats ;
- limites, défauts connus et hypothèses non démontrées ;
- état des pilotes existants ;
- coûts engagés et coûts seulement estimés ;
- procédure de retour arrière ;
- commandes et éléments précis permettant la revue indépendante.

**Condition de fin du Goal :** les capacités livrées sont vérifiables et les travaux restants sont explicitement identifiés. Une attente de données futures doit produire un état documenté ; elle ne doit entraîner ni résultats inventés, ni répétition automatique d’analyses sans information nouvelle.

***

À son retour, transmets-moi le CR et les références des commits. Je vérifierai en priorité la comptabilité, la causalité des évaluations, les limites réelles de collecte et la capacité du harness à comparer ses propres décisions d’adaptation.