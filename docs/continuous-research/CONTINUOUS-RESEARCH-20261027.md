# Recherche continue — livraison du 27 octobre 2026

L'autorisation utilisateur du 27 octobre demande de terminer les cinq chantiers d'automatisation. Le worker continu remplace l'entrée du timer population-research existant. Il utilise les collecteurs et le moteur de validation existants ; aucun ordre réel n'est possible dans ce parcours.

## Parcours et décisions

| Chantier | Raccordement |
|---|---|
| Admission descriptive | Le dernier screening exact alimente `descriptive_admission`, puis `continuous_research_policy.candidates_for_admission`. Une étude descriptive ne demande pas une validation économique déjà acquise. Les données réservées sont exclues avant lecture. |
| Consommation renouvelable | Autorisation quotidienne indépendante, immuable et persistée avant appel dans `continuous_research_tasks/calls`. Les essais échoués restent consommés. Les registres et plafonds historiques ne sont pas réinitialisés. |
| Résolution | `continuous_research_resolution` exécute les calculs locaux explicitement pris en charge, mémorise leurs preuves, suit les contrats d'observation et vérifie les réveils du collecteur. Un contrat absent ou non pris en charge produit une tâche technique ; les autres sujets continuent. |
| Hypothèse → évaluation | `research_evaluation.handoff_locked` n'accepte qu'une spécification structurée revue et un profil compatible. Il fige les paramètres et les fenêtres futures avec l'allocation externe. Une association descriptive ne devient pas une règle par déduction du programme. |
| Évaluation → prochaine décision | Le pipeline existant mesure comparaison/finale et contrôle le paper. Le worker relève les résultats, conserve les critères échoués dans une mémoire exportable et poursuit les autres candidats. La politique existante de libération des périodes terminées reste appliquée, sans rendre une finale consommée vierge. |

Une seule tâche d'inférence est exécutée par tick, sous le verrou de recherche partagé. Les résolutions et évaluations en attente n'occupent pas ce créneau. Les curseurs persistants évitent qu'une longue file de travaux anciens bloque les suivants. La rotation privilégie les comptes les moins récemment examinés ; un compte couvrant beaucoup d'instruments ne monopolise pas les premiers créneaux.

## Ressources et portée

`config/continuous-research-policy.json` autorise au maximum **3 études et 6 appels par jour UTC**, 480 000 tokens d'entrée, 30 000 de sortie et 720 secondes réservées. Chaque tâche conserve les limites du runtime abonnement : deux rôles au plus, 80 000 tokens d'entrée et 5 000 de sortie par appel, 120 secondes. Aucun USD fictif n'est réservé. Ces valeurs sont une allocation initiale de ressources, pas des seuils scientifiques ; un changement exige une nouvelle identité de politique.

`config/continuous-experiment-policy.json` conserve les critères et fenêtres de l'allocation prospective précédente. Son enveloppe distincte autorise au plus un nouveau plan par jour et deux évaluations simultanément en attente. Une allocation échouée n'est pas remboursée ; un nouveau jour ne déplace pas les fenêtres déjà figées. Les expériences historiques conservent leur budget de vie propre.

L'admission utilise au moins 10 fills observés et deux jours actifs comme heuristique descriptive, avec les limites et sensibilités du rapport d'admission. Les comptes multi-marchés sont ventilés à partir des fills autorisés : au plus deux comptes sont tabulés par tick, puis la preuve est réutilisée tant que son entrée ne change pas. Tous leurs instruments suffisamment documentés peuvent rejoindre la même file.

Les statistiques de recherche peuvent couvrir tout l'historique autorisé avant le cutoff ; la fenêtre d'activité servant à l'admission est distincte et explicitement nommée. Les autres instruments sont du contexte de compte, sans autoriser une hypothèse sur eux dans une étude mono-marché.

Les limites finales restent 225 000 caractères de paquet et 260 000 de prompt. Le préparateur peut lire une représentation de travail de deux millions de caractères avant projection ; cette représentation n'est jamais envoyée au modèle. En cas de contexte multi-marché volumineux, les statistiques du marché étudié restent entières, les autres marchés deviennent du contexte d'activité et la représentation complète est conservée sans perte en gzip dans SQLite. Une projection encore trop grande est refusée explicitement.

## Invariants

- Le scellement du job et son autorisation sont transactionnels : aucune coupure entre les deux ne crée de job orphelin.
- La déduplication repose sur les fills dédupliqués du marché, les statistiques économiques et les nouvelles preuves de demandes satisfaites. Un changement de sérialisation, de politique, de jour, de réception équivalente ou des fills d'un autre instrument ne suffit pas.
- Les demandes en langage libre ne deviennent jamais des appels réseau ou des commandes. Une demande `needs_data` peut porter un contrat typé public ; le collecteur existant l'exécute dans son bail et son quota partagés. Sans contrat exploitable, la disposition courante est technique, avec passage au candidat suivant ; la réponse fournisseur originale reste intacte.
- Les horloges d'événement, de réception et d'archivage restent distinctes. Les fills REST ne deviennent pas des signaux de suivi live.
- Les mémoires conservent leurs comptes, marchés, périodes et références transitives, y compris les résultats d'évaluation. Une mémoire nouvelle seule n'autorise pas une nouvelle inférence sur les mêmes faits ; un véritable résultat de validation ou un bilan paper inactif apporte au contraire une nouvelle preuve exploitable, même sans nouveau fill source.
- Un modèle maker non pris en charge reste une limite technique. Aucun fill passif, rebate accessible à notre compte ou résultat de clôture n'est inventé.
- La validation réelle et les conditions de paper restent celles du pipeline ; un test synthétique ne peut pas les satisfaire.

## Exploitation et retour arrière

Le service installé doit correspondre à `systemd/user/tamtam-again-population-research.service`. Le timer existant attend 900 secondes après la fin d'un passage. Les timers de collecte et de paper restent indépendants.

```sh
PYTHONPATH=src python3 scripts/continuous-research-tick.py --db data/tamtam.sqlite3 --policy config/continuous-research-policy.json --experiment-policy config/continuous-experiment-policy.json --collection-policy config/research-need-collection-policy.json --reserve-policy config/reserve-cycle-policy.json --prepare-only
systemctl --user status tamtam-again-population-research.timer
journalctl --user -u tamtam-again-population-research.service -n 40 --no-pager
```

`--prepare-only` ne fait aucune inférence. Il peut enregistrer des préparations et consommer des résultats locaux déjà autorisés. Les commandes de suivi ne doivent pas effacer les registres pour relancer un essai.

Pour revenir à l'ancien worker, arrêter seulement ce timer/service, réinstaller l'ancienne unité depuis Git puis recharger systemd. Conserver les tables nouvelles et les données ; ne pas restaurer toute SQLite et ne pas réarmer les anciens pilotes. Les autres collecteurs peuvent continuer.

## Preuves et limites de la livraison

La preuve opérationnelle compacte et les vérifications finales sont dans `CONTINUOUS-RESEARCH-PROOF-20261027.json`. Le parcours intégré sur base temporaire exerce réellement le moteur et ses coûts : comparaison rejetée → mémoire persistée → examen automatique d'un autre marché. Seuls le fournisseur et l'admission de cette recette sont simulés.

Un premier passage réel a étudié automatiquement `10f0/SOL` : 102 fills archivés, un appel abonnement valide, puis `needs_data`. La réponse n'établit aucune règle exploitable. L'absence de demande structurée a ensuite été classée en tâche technique avec passage au candidat suivant, sans réinterroger le modèle. Les réponses, décisions et usages restent dans la base opérationnelle.

Le service installé a ensuite traité `1e07/ETH` sans intervention sur la première tâche. Il a terminé avec `Result=success`, code 0 ; la réponse `unsupported_mechanism` est conservée et routée en travail technique. Le timer reste activé. Les deux appels enregistrent respectivement 13 451 / 1 894 et 14 428 / 2 042 tokens d'entrée / sortie. Le compteur partagé historique reste 11 pour son plafond inchangé de 8 ; ces nouvelles études ont leur propre enveloppe.

Vérifications finales : 195 tests ciblés réussis en 49,588 secondes sur l'intégration finale, puis vérification du service installé et rejeu des tâches réelles depuis une connexion SQLite en lecture seule. La recette économique complète reste synthétique ; aucune nouvelle stratégie réelle n'a passé une finale à ce checkpoint.

Capture reproductible du checkpoint, sans appel IA :

```sh
PYTHONPATH=src python3 scripts/verify_continuous_research.py --db data/tamtam.sqlite3 --output /tmp/continuous-research-proof.json
```

La livraison automatise les transitions prises en charge, les refus et la poursuite de la recherche. Elle ne démontre pas encore une stratégie réelle profitable ni une nouvelle finale prospective passée. Un mécanisme ou une source non implémenté exige toujours un travail technique ; cette limitation concerne le sujet, pas le fonctionnement des autres études. Les preuves de validation futures seront produites par les timers quand leurs données seront disponibles, sans inventer une mesure anticipée.
