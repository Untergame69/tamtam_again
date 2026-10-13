# Rectificatif v2 — résolution locale v5, 2026-10-13

Ce rectificatif complète le rapport historique [V5-LOCAL-ARCHIVE-RESOLUTION-20261013.md](V5-LOCAL-ARCHIVE-RESOLUTION-20261013.md). Il ne le remplace pas : la résolution et le paquet v1, ainsi que leur enfant dormant, restent conservés tels quels.

## Correction du contrat d’exécution

Le paquet local exige maintenant deux phases de validation explicites. La préparation valide un enfant `budget_required` non activé. L’exécution revalide le même paquet après scellement : état `sealed`, horodatage d’activation identique à celui de l’appel runtime, disponibilité des données identique, identité du child dérivée du fingerprint du paquet, autorisation dédiée correspondante lorsqu’elle existe, période héritée autorisée et références d’archives intègres. Le runtime utilise uniquement la phase `execute`. Les schémas corrigés sont `paper-local-evidence-research-v2` et `paper-local-archive-bundle-v2` ; les fingerprints v1 ne sont pas réécrits.

Un test d’intégration sur SQLite temporaire parcourt parent `needs_data` → résolution des archives → enfant dormant → refus de scellement sans autorisation/budget disponible → autorisation simulée dédiée → scellement → runtime à inférence simulée → nouvelle décision persistée (`needs_data`). La reprise retourne `unchanged_no_inference` et le mock confirme un seul appel. La décision de routage est persistée et rejouée sans doublon.

## Fermeture v5 et borne observée

Le diagnostic de fermeture est corrigé : la session paper v5 suspendue ne sera pas fermée par une collecte Hyperliquid ultérieure, car une collecte de cotations ne modifie pas l’état de cette session virtuelle. Le paquet v2 classe la dernière demande comme `censored_endpoint_incomplete`, avec `observation_boundary=censored_open_position`, `terminal_result=incomplete_censored` et la position résiduelle observée `-0.61 HYPE`. L’ordre de réduction en attente et l’historique restent présents. Aucun fill de clôture, PnL final ou résultat terminal n’est inventé. Une étude d’une clôture exigerait une autre exécution paper explicitement autorisée ; ce n’est pas une condition d’attente pour cette résolution.

## Artefacts et preuve persistée

- Rapport antérieur conservé : résolution `93860ff0ee02d2a10fc8cd22408a9acadd2769ae63b340af0e3e2f3be16415ef`, enfant `e5d99a38dcf8b890ecb76aaf82ca84869024ce27d64ff885528dfe3ec53b3e2d`, paquet v1 fingerprint `98814ea21e62df67dadd968590003e618abbb20c1c80892cce648ce5dfca350f`.
- Rectification v2 : résolution `d61b5d26840e30e477783d18074fdd3394bdf6432cb44cb13487461677aa3aab`, enfant prêt `9dda3827e578bd17992a67dafd9849596a4a9b3119c8f3756d3468bd665f804a`, fingerprint `466cd04d8d5a33f5593fbfba455d23492db648cc83cf9655e92441b1899777d9`, 217 110 caractères sur la limite de 225 000.
- Une nouvelle connexion à `data/tamtam.sqlite3` a revalidé l’empreinte, le manifeste des observations et le paquet v2. L’enfant reste `budget_required`, sans activation ; sa route est `budget_required`. La résolution v1 demeure présente et inchangée.
- La commande reproductible reste `PYTHONPATH=src python scripts/resolve-paper-local-archives.py --db data/tamtam.sqlite3 --request-id 75c617af00435dab9bf1dd614aa5cbaddc26700446110affaaf7c781f0892746` ; elle retourne `unchanged` pour cette version du paquet.
- Vérification ciblée : `python -m unittest tests.test_paper_local_resolution tests.test_paper_followup tests.test_paper_research tests.test_paper_runtime tests.test_population_runtime -q` — 53 tests réussis.

Aucun appel IA réel, activation, reprise de session v5, lancement paper ou changement de service n’a eu lieu dans cette tranche. Le paquet v2 est prêt à analyser après une activation explicitement autorisée ; aucune analyse n’a été engagée ici.
