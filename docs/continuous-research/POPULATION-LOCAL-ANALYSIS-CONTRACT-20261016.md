# Contrat générique d’analyse locale des archives — 2026-10-16

## Résultat

Le parcours local de résolution est maintenant piloté par un contrat scellé `population-local-analysis-contract-v1`, pas par un compte, une tâche ou une date codés dans l’exécuteur. Le profil est volontairement fini : effet de position depuis `startPosition`, prédécesseurs BBO/l2Book strictement antérieurs, markouts événement/réception déjà archivés, regroupements ordre/temps et sensibilité aux conditions/fraîcheur.

Le contrat lie l’identité réseau/compte/marché, la fenêtre semi-ouverte, le rapport et son empreinte sémantique, les empreintes des inventaires exacts de pages/lots, les sources permises, le cutoff `finalised_ms`, les paramètres de calcul et l’autorisation archive seule (zéro collecte, zéro appel modèle). Le constructeur `contract_for_report` tire les références et empreintes du rapport archivé. Des opérations, sources ou paramètres supplémentaires échouent avec un diagnostic de champ et de limite ; le texte `required_data` reste informatif et n’est jamais interprété comme une commande.

Le routeur vérifie le contrat et la provenance à partir du rapport conservé. Le scheduler exécute les calculs locaux sans dépendre du budget IA. Les lecteurs n’utilisent que les pages/lots référencés et dont le SHA-256 correspond ; ils rendent aussi visibles les références absentes, les empreintes discordantes et les observations présentes en archive mais non référencées, sans les mélanger aux preuves scellées. Les fills du rapport qui n’ont pas de page raw joinable restent calculés avec un `order_id` inconnu. Les résultats `available_and_joined`, `partially_covered_exploitable`, `absent` et `technical_required` sont distingués. Une opération hors profil reçoit `calculation_set_unsupported`.

Les résultats ont leur propre table/version et leur namespace `local_archive_resolutions_v1`; le champ historique 67f7 reste inchangé. Le rejeu relit l’artefact vérifié sans rappeler les lecteurs ni recalculer les agrégats. Un échec local n’utilise pas la place d’exécution des tâches suivantes.

## Vérifications

Les tests utilisent deux comptes, deux marchés et deux fenêtres; ils couvrent le chemin scheduler, l’idempotence, le retour sans recalcul, la couverture partielle avec fills report-only, les cotations absentes, les lots allowlistés, les SHA, le cutoff, les événements hors fenêtre, le diagnostic d’opération inconnue et l’absence d’autorisation pilote. Un échec sur la première tâche ne bloque pas la suivante.

Le rapport final réel 67f7/ETH a aussi été validé en lecture seule avec le constructeur générique : fenêtre scellée, cutoff finalisé, 283 références de pages fills et 437 258 références de lots BBO/l2Book. La route et l’artefact historiques n’ont pas été rejoués ni écrits : `local_eth_existing_window_resolution.artifact_fingerprint` reste `697a4b00d599d15fabbfa2ab530efd7fdfb24dfb162a49b6e3f7bc9440e65da1`.

Commande de test ciblé :

```sh
PYTHONPATH=src python -m unittest \
  tests.test_population_local_archive_resolution \
  tests.test_eth_existing_window_resolution \
  tests.test_population_pilot \
  tests.test_research_work_queue -v
```

Aucun appel IA, collecte, paper ou ordre réel n’a été effectué. Aucun budget ou service n’a été modifié.

## Limites restantes

Le profil accepte uniquement les rapports d’observation Hyperliquid de ce schéma et ces deux sources d’archives. Il ne reconstitue pas les décisions de placement, la disponibilité exacte d’une cotation à un instant de décision absent, ni l’intention du trader. Un futur calcul exige un nouveau profil versionné, et une collecte exige une autorisation distincte. La création du contrat doit être faite par l’étape de préparation à partir du rapport immuable ; aucune requête IA libre ne peut l’ajouter après scellement.

## Raccordement opérationnel vérifié

`seal_final_eth_observation` vérifie d’abord l’autorisation v2 existante, l’identité du protocole et l’égalité entre le rapport fourni et la ligne persistée. Il remet ensuite ce rapport et le protocole finalisé à `prepare_pilot_packet`. Cette préparation ajoute la projection compacte, la référence exacte du rapport et `local_analysis_contract_v1`, puis calcule `research_input_fingerprint` et le fingerprint du paquet. Le contrôle de taille du paquet et du prompt intervient avant le scellement. Si le rapport contient une fenêtre, elle doit correspondre au protocole. Le rapport réel ne contient pas de champ `window` ; son périmètre vient donc du `protocol_json` persisté, sans ajouter ni inventer de champ dans le rapport.

Le parcours complet simulé part d’un rapport persisté, passe par la préparation et le scellement v2, transmet le contrat au runtime à réponses fournisseur simulées, obtient une décision `needs_data`, puis passe par la route et la résolution générique. La résolution partielle est enregistrée et le rejeu retrouve l’artefact sans recalcul. Le JSON du paquet et l’empreinte du contrat sont identiques avant et après le runtime. Un test distinct prépare des tâches de deux identités depuis le chemin ordinaire `prepare_pilot_packet`, sans construire le contrat manuellement, puis couvre les refus de marché hors périmètre, les archives partielles et le rejeu du scheduler.

Contrôle réel en lecture seule, sans appeler le scellement ni modifier l’ancienne tâche : le rapport `final_24h` a l’empreinte sémantique `47d0c3c3c3c9d4303d76c7d762c97530962c1de4ea8e42ed59b40ec8e52cf91f`. La préparation a produit le contrat `b3aef342cd0c8a8bb71434f6dd14545eeccef0e4909b7cd3f1b9791861f0c4ae` ; paquet complet **122 682** caractères et prompt **127 128**, sous les limites inchangées de **225 000 / 260 000**. La tâche historique `501c352c…` reste `hypothesis_recorded`, son paquet reste valide au fingerprint `612fd31d3a569ccb6305ff5739c0983199b75a1b7c57bc0aa2505961bbdc4a17`, et aucune mise à jour de son résultat n’a eu lieu. Au contrôle, la base contient 14 tâches et 6 autorisations pilote.

Les parcours d’intégration simulés couvrent le scellement et le runtime jusqu’à la résolution persistante, puis deux identités et marchés, le refus hors périmètre, les inventaires partiels, et le rejeu sans recalcul. Bilan ciblé : 37 tests réussis avec :

```sh
PYTHONPATH=src python -m unittest \
  tests.test_population_local_archive_resolution \
  tests.test_eth_existing_window_resolution \
  tests.test_population_pilot \
  tests.test_research_work_queue -v
```

Aucune tâche opérationnelle n’a été ajoutée ou réactivée. La prochaine analyse attend un nouveau rapport compatible traité par la file dans l’autorisation déjà existante ; le travail courant s’arrête à la vérification en lecture seule et aux parcours simulés.
