# Synthèses descriptives des candidats — 2026-10-14

## Résultat

Le préparateur réutilisable `population-descriptive-summary-v1` produit désormais, pour les trois candidats du pilote, un paquet déterministe depuis les archives SQLite locales. Il distingue couverture, activité, segments et ruptures de position, épisodes localement bornés, résultat de prix, frais signés et funding. Les paquets sont liés aux rapports de scope et aux réponses REST par identifiant et SHA-256. Le parcours courant n’a plus d’enrichissement spécial a880.

Aucune inférence, collecte, expérience paper, modification de quota ni ordre n’a été effectué. Les paquets et décisions historiques restent conservés. Le fichier machine lisible [POPULATION-DESCRIPTIVE-PACKETS-20261014.json](POPULATION-DESCRIPTIVE-PACKETS-20261014.json) contient les paquets complets et leurs références.

## Périmètre et règles d’accès

Le cutoff explicite du pilote est `2026-10-12T07:16:34.195Z` (`1791789394195` ms). Les trois comptes satisfont `authorized_account_history` à ce cutoff. La vérification d’autorisation et des périodes réservées précède le décodage des observations. Pour a880, les fenêtres réservées documentées commencent après ce cutoff ; elles ne sont donc pas lues ni intégrées. Les paquets n’utilisent que des rapports disponibles au cutoff et des observations d’archives dont `observed_at` et, lorsqu’elle existe, la fin de fenêtre ne dépassent pas le cutoff.

Les observations proviennent des réponses REST locales `userFills`, `userFillsByTime` et `userFunding`. Les réponses sont vérifiées contre leur SHA-256, dédupliquées par identité d’événement et gardées par référence. Les lignes de collecte ont `complete=false` : `pagination_exhausted` signifie que la pagination de cette requête s’est terminée, pas que l’historique de l’API ou celui du compte est complet. Les lignes `page_budget_exhausted` signalent en plus des requêtes interrompues au budget de pages. Aucune borne de rétention ni continuité globale n’est démontrée.

Les rapports de scope reflètent une analyse courte disponible à une heure donnée ; ils ne sont pas un décompte de toutes les archives du compte. Les observations d’un marché absent du rapport sont conservées, mais signalées comme hors du scope déclaré. Les prix de chaque marché restent en unités de cotation de ce marché et ne sont pas additionnés entre marchés. Les frais gardent leur signe et leur token d’origine. Le funding reste séparé, en USDC selon le champ archivé ; seule une attribution stricte à un épisode intérieur et à une position pré-événement exactement concordante est comptée. Les ruptures et épisodes ouverts ne sont jamais raccordés artificiellement.

## Rapport court contre archives disponibles

| Candidat | Ce que contenait le paquet IA du pilote | Archives locales autorisées au cutoff | Explication de l’écart |
|---|---|---|---|
| a880 | Rapport de scope `958142889a7442939dea2355040af6eb` : 2 020 fills observés, 17 marchés, fenêtre demandée d’environ 3 722,6 s ; paquet historique enrichi séparément avec l’analyse HYPE de 32 921 fills. | 171 observations fill, 180 589 lignes décodées, 178 438 TID uniques après déduplication, sur 18 marchés. Événements du 7 oct. 18:45:59 au 11 oct. 23:37:09 UTC ; observations reçues du 8 oct. 00:29:45 au 11 oct. 23:37:23. 106 pages au budget épuisé, 64 paginations terminées, 1 statut inconnu. | Les 2 020 sont le scan du rapport courant, pas tout l’archive. Les 32 921 sont uniquement HYPE et viennent de l’ancien calcul dédié. Le nouveau paquet relie désormais le profil au résumé générique multi-marchés sans remplacer l’ancien paquet. |
| 67f7 | Rapport de scope `5d932f97d1d34d4da2a1d023796fcbe9` : 150 fills ETH sur une fenêtre d’environ 3 672,5 s, disponible le 11 oct. à 23:29:44 UTC. Le paquet scellé à l’IA exposait ce rapport court, pas les pages account-fills archivées. | 57 observations, 25 614 lignes décodées, 25 601 TID uniques, 13 doublons exacts et aucune identité conflictuelle. Événements du 6 oct. 09:24:22 au 11 oct. 23:29:20 UTC ; réception du 7 oct. 09:24:32 au 11 oct. 23:29:32. 11 budgets de pages épuisés et 46 paginations terminées. Parmi les fills : 23 140 ETH et 2 461 `xyz:DRAM`. | `150` décrit un seul scan ETH d’environ une heure. `25 601` additionne les identités distinctes des requêtes account-fills archivées sur plusieurs jours : 23 140 ETH et 2 461 DRAM. L’ancienne sélection du scope ne déclarait que ETH ; DRAM est donc explicitement signalé comme observé hors du rapport, pas mélangé à ETH. Les pages étaient autorisées sous le même compte et dans la période du pilote, mais ne figuraient pas dans le paquet IA initial. |
| be504 | Rapport de scope `20cd767a68934219bc4a43a47ed8bad1` : 113 fills sur LIT et `xyz:XYZ100`, fenêtre d’environ 3 697,9 s, disponible le 11 oct. à 23:42:11 UTC. Le paquet historique exposait ce rapport court, pas tout l’archive account-fills. | 70 observations, 891 TID uniques sans doublon : événements du 7 oct. 01:25:09 au 11 oct. 23:31:48 UTC ; réception du 8 oct. 00:33:39 au 11 oct. 23:41:57. Les 70 paginations sont terminées, mais toutes les lignes restent `complete=false`. 522 LIT et 96 `xyz:XYZ100` (618 au total dans les deux marchés déclarés), plus 273 fills répartis sur neuf symboles non déclarés. | `113` est le rapport court de deux marchés sur environ une heure ; `891` est l’archive locale multi-fenêtres de plusieurs jours. L’écart de 778 comprend notamment les autres observations de LIT/XYZ100 et 273 fills hors des deux marchés déclarés. Les autres symboles et les funding sans fill sont conservés, mais ne sont pas agrégés aux deux marchés du rapport. |

Ces décomptes ne signifient pas que les données omises par le paquet IA initial auraient changé une conclusion ou rendu un signal rentable. Les rapports, autorisations et fenêtres diffèrent ; aucun signal refusé n’est réputé exécutable ou profitable.

## Synthèses comparables

Les chiffres ci-dessous sont des résultats descriptifs des paquets versionnés, pas une mesure exhaustive de performance. Une « rupture » sépare les chaînes locales ; les épisodes comptés sont uniquement les retours à zéro ou inversions intérieurement bornés, avec quantité et frais répartis au prorata à l’inversion.

| Candidat / marché | Activité archivée | Chaînes locales | Épisodes bornés et résultat de prix | Frais signés observés (token) | Funding observé ; strictement attribué |
|---|---:|---|---|---|---|
| a880 / HYPE | 32 921 fills : 31 383 `crossed=false`, 1 538 `crossed=true` | 2 segments, 1 rupture ; continuité inconnue | 652 épisodes (retours à zéro et inversions), résultat de prix `-6.13149` unités de cotation | archive `-524.607450 USDC`; parties d’épisodes bornés `-519.9376486858622549996058165 USDC` | 118 événements, somme archivée `+5.577480 USDC`; 82 attribués strictement, `+6.222528 USDC` |
| 67f7 / ETH | 23 140 fills : 19 279 `crossed=false`, 3 861 `crossed=true` | 2 segments, 1 rupture ; continuité inconnue | 1 609 épisodes bornés, résultat de prix `+1 666.92573` unités de cotation | archive `+517.031372 USDC`; parties bornées `+515.7141009502495024959373817 USDC` | 134 événements, `+1.110173 USDC`; 102 attribués strictement, `+0.298373 USDC` |
| 67f7 / xyz:DRAM | 2 461 fills, tous `crossed=false` | 1 segment, aucune rupture observée ; exhaustivité inconnue | 181 épisodes bornés, résultat de prix `-628.8184` unités de cotation | archive `-16.990350 USDC`; parties bornées `-16.99035000000000000000000001 USDC` | 18 événements, `-0.426683 USDC`; 10 attribués, `-0.246499 USDC` |
| be504 / LIT | 522 fills : 168 `crossed=false`, 354 `crossed=true` | 4 segments, 3 ruptures | 1 épisode borné, résultat de prix `-1 178.52760` unités de cotation | archive `+151.000036 USDC`; parties bornées `+48.453169 USDC` | 16 événements, `+8.340997 USDC`; aucun strictement attribué |
| be504 / xyz:XYZ100 | 96 fills : 94 `crossed=false`, 2 `crossed=true` | 2 segments, 1 rupture | 0 épisode borné | archive `+7.043678 USDC`; aucun frais ne peut être affecté à un épisode borné | 91 événements, `+120.161892 USDC`; aucun strictement attribué |

Les autres marchés be504 sont détaillés séparément dans le JSON ; plusieurs ont peu ou pas de fills, des ruptures et du funding non attribuable. Les valeurs signées ne sont pas converties en « coût » ou « revenu net » : leur convention économique reste une question distincte. La somme strictement attribuée de funding peut dépasser la somme nette de tous les événements observés quand les événements non attribués ont le signe opposé ; ces deux champs sont des sous-totaux différents, pas une identité comptable.

La qualité de reconstruction varie nettement : a880/HYPE et 67f7/ETH ont davantage d’épisodes observés, mais chacun conserve une rupture ; be504/LIT a trois ruptures pour un épisode borné. Ni le nombre d’épisodes ni les chaînes sans rupture locale ne prouvent indépendance, continuité complète ou rentabilité. Le paquet garde les exemples, les empreintes complètes de ruptures et d’épisodes, les taux maker/taker et les motifs de non-attribution.

## Échec de la critique 67f7

Les traces du job `6f54cef055874db260d88d96c8f7021474b65cc5ce38f1a3121ed43b6805497a` montrent : appel 2 réservé puis engagé, réponse fournisseur reçue, aucun horodatage de validation de réponse ni de résultat ; état `rejected`. Les métadonnées enregistrent 11 131 ms, `failed=true`, `exit_code=0`, `error_type=null`, `missing_module=null`, et zéro token avec statut d’usage inconnu. Le diagnostic persistant est `stage=provider_execution`, `code=isolated_inference_failed`, champ `failed`, valeur observée `{failed:true, exit_code:0, error_type:null}`, limite « successful isolated provider response ».

Cela établit un échec de l’enveloppe d’exécution isolée avant validation, mais pas sa cause interne. Les traces conservées ne permettent pas de distinguer panne fournisseur, réponse interne de l’isolation ou autre sortie d’exécution. Aucun défaut de schéma particulier n’est démontré ; aucun correctif de cause ou retry n’est donc appliqué. La tentative reste rejetée et consommée, sans nouvelle inférence.

## Reproductibilité et preuves

Commande reproductible (ouvre la base en lecture seule, n’utilise que le cutoff de la politique) :

```sh
PYTHONPATH=src python scripts/prepare_population_descriptive_packets.py \
  --db data/tamtam.sqlite3 \
  --policy config/research-loop-pilot-v1.json \
  --output docs/continuous-research/POPULATION-DESCRIPTIVE-PACKETS-20261014.json
```

Deux exécutions successives ont produit le même SHA-256 fichier `e8d4fb0590cda0d5d0fee2734298059d23208bd6d924997b15910e82afc97d95` et le même fingerprint d’ensemble `103a463bf858dce65ff7e49fa81e382d704ef3e42b5efbcdba09dc0c1b3fb3a0`. Les trois candidats ont `packet_ready`. Leurs fingerprints paquet / synthèse sont :

- a880 : `6149bd429a85a1aed09d38271677eeeeb1ad2c13a332cb2e210f78bc5f31125e` / `3c765e796885b64241992e49158e17b853b095b841a1e6d5e5a7cbf86230294a` ; 197 815 caractères.
- 67f7 : `0a8670daf0a2f0765be7cb2a0ebdf77b1dffa624f0e7f0984344630d5d5035f5` / `268a7df0e6360057ea6d3652db79981d1ba75880f1f6e1e82cceba6e1bc935d7` ; 40 969 caractères.
- be504 : `12067f316095a9d15a15992ac223379a74be8ee9ced133be387e5c25f791cd98` / `c370ad03cd60fbc80ef9e7eaf5227f3ff17e65f7e93084991151c3bf1649638d` ; 69 143 caractères.

Les tests ciblés passent : `tests.test_population_descriptive`, `test_population_pilot`, `test_population_packet`, `test_population_runtime` et `test_population_research` — 40 tests. Ils vérifient l’empreinte stable, les doublons et TID conflictuels, la coupure temporelle, la protection des périodes réservées avant décodage, les références uniques, la conservation du paquet original, le scellement générique et l’absence de nouvelle tâche sur contenu inchangé.

## Décision de recherche

Priorité unique : **67f7, ETH seulement**, pour une prochaine analyse descriptive fondée sur son paquet élargi et non sur le seul instantané de 150 fills. C’est le plus grand écart vérifiable entre l’archive autorisée et la preuve initialement fournie ; l’archive ETH permet de mieux examiner les exécutions et segments disponibles, tout en gardant DRAM séparé. La question utile est de préciser ce que les observations ETH étayent sur les exécutions maker et le comportement d’inventaire, et quelles variables observables seraient indispensables à un test prospectif. Le paquet ne prouve ni une règle d’inventaire ni sa performance, et la panne d’exécution de critique 67f7 n’est pas résolue par ces données.

Cette priorité est une recommandation de recherche, pas une activation. L’enveloppe pilote existante a consommé ses trois tâches autorisées ; aucune nouvelle tâche IA ne peut être engagée dans cette tranche sans autorisation distincte. Le prochain travail peut commencer par une lecture locale du paquet et un diagnostic manuel du runtime. Aucune collecte prospective ni expérience paper n’est justifiée par le seul volume de fills. La compatibilité avec le moteur actuel demeure indéterminée pour 67f7 ; elle reste distincte de l’intérêt et de l’observabilité de la recherche.
