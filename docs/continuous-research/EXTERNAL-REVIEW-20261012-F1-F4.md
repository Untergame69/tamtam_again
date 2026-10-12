# Compte rendu externe — corrections F1–F4 et qualifications ciblées

Date : 12 octobre 2026. Cutoff du classement : `1791789394195` ms (`2026-10-12T07:16:34.195Z`). Aucun appel de recherche IA, aucune enveloppe budgétaire ajoutée, aucune collecte fournisseur déclenchée manuellement.

## Résultat livré

- Les anciens résultats restent conservés : le classement originel du 12 octobre et le dossier comptable du 9 octobre n’ont pas été remplacés.
- Nouveau classement reconstruit à cutoff identique dans [`historical-selection-20261012-f1-f4`](historical-selection-20261012-f1-f4/report.md) : 153 comptes analysés; 3 présélections, 9 PnL positifs en attente d’activité, 16 positifs concentrés/clairsemés, 97 insuffisamment documentés et 28 négatifs sur un horizon mesuré.
- Comparaison à l’ancien classement : mêmes 153 adresses, aucun ajout/retrait, aucune empreinte de compte modifiée, mêmes cinq effectifs de catégories. Les nouvelles métadonnées de population excluent maintenant le statut mutable de la file.
- Trois fiches économiques sont dans [`economic-qualification-cards-20261012.md`](economic-qualification-cards-20261012.md). Elles affichent les flux et résidus disponibles, mais laissent explicitement les trois comptes non qualifiés.
- Relecture du ledger F4 conservée dans [`ledger-recheck-20261012.json`](ledger-recheck-20261012.json).

## F1 — plafond sur les tentatives logiques

La file compte une tentative avant l’appel au fournisseur et borne la boucle sur les tentatives, quelle que soit l’issue. Les réponses invalides et erreurs comptent comme échecs; une exclusion détectée après retour compte comme tentative et est exposée séparément de l’exclusion avant appel. `portfolio_requests` reflète maintenant les appels logiques, `portfolio_saved` les observations persistées, et `logical_attempts` donne la limite appliquée. Les reprises HTTP internes restent comptabilisées et régulées par le limiteur REST partagé.

Régression synthétique : 80 adresses avec échec immédiat produisent quatre appels, quatre tentatives, zéro sauvegarde. Le mélange sauvegardes/exclusion après appel reste plafonné à quatre.

## F2 — reconstruction immuable au cutoff

L’éligibilité historique est calculée à partir des rapports de périmètre disponibles au cutoff ou d’un candidat dont une observation portfolio immuable était disponible au cutoff. `status`, `updated_ms` et l’avancement courant de la file n’interviennent plus. Le nombre de candidats registre est filtré par `added_at` au cutoff; les compteurs de statut de file mutable ont été retirés du rapport figé.

Régression synthétique : le passage `pending` → `fetched` après cutoff conserve la population, les statuts, les métriques et les empreintes du rapport reconstruit.

## F3 — fraîcheur, budget partagé et voie d’inventaire

La politique de file passe en `historical-curve-queue-v2`. Les nouvelles adresses et les rafraîchissements partagent toujours le même plafond de quatre tentatives par tick de 15 minutes, sans hausse de quota. Une observation portfolio se réexamine après 24 heures. Une réussite remet à zéro le compteur d’échecs consécutifs; six échecs consécutifs restent le maximum. Les candidats de courbe prioritaires sans `account_scope_reports` peuvent entrer dans `deepen`, sous le budget de slots déjà défini. Les contrôles et l’exploration conservent leurs slots.

Tests synthétiques : rafraîchissement après 24 heures, remise à zéro après succès, et candidat prioritaire sans scope routé vers `deepen`. Aucun test n’appelle l’API ou un modèle. Vérification d’exploitation : timer `tamtam-again-historical-queue.timer` actif et en attente (`systemd --user`); aucune exécution manuelle lancée pour ce rapport. La limite effective reste quatre tentatives/tick, soit 80 poids réservés au maximum par tick et 5,333 poids/minute en moyenne théorique à la cadence configurée. Les appels conservent le limiteur partagé comme autorité.

## F4 — ledger complet des pages déjà archivées

Après vérification `protected=false` et historique libéré, les quatre références ledger ont été relues sur la fenêtre `(1791458734427,1791479504849]`, puis dédupliquées par identifiant normalisé :

| Référence | Événements dans la fenêtre | Flux externe USDC net |
|---|---:|---:|
| `raw_observations:12329687` | 1 | −2 111 |
| `raw_observations:12391150` | 298 | −1 179 234 |
| `raw_observations:12392055` | 105 | +3 882 464 |
| `raw_observations:12393256` | 162 | +1 746 631 |
| **Total dédupliqué** | **566** | **+4 447 750 USDC** |

Les références de funding correspondantes sont `12329355`, `12391149`, `12392054` et `12393255`. La variation native `perpAllTime.accountValueHistory` (+4 456 044) garde un écart de +8 294 face au changement comptable (+4 447 750). Les points de courbe sont proches des bornes mais non simultanés; `allTime`/`perpAllTime` ont des périmètres qui se recouvrent. Le rapprochement ledger ne résout donc pas l’écart et ne constitue pas une approbation économique.

## Qualification des trois présélections

La lecture locale de SQLite en mode lecture seule a été précédée d’un contrôle de protection/libération pour chaque compte. Les observations après le cutoff n’ont pas été utilisées. Les trois dossiers ont des historiques portfolio, fills, funding, ledger, états perp/spot et inventaire de compte archivés; ces quantités ne prouvent pas une couverture exhaustive.

| Compte | Fills / jours actifs (30 j) | PnL déclaré 30 / 90 / 180 j | Résidu mensuel / part brute | Décision économique |
|---|---:|---:|---:|---|
| `a880…4ee` | 178 438 / 5 | +16 094,87 / +56 403,54 / +128 249,47 | +10 563,78 / 8,24 % | en attente |
| `be504…77b` | 891 / 5 | +193 867,76 / +266 983,24 / +365 968,59 | +63 001,92 / 6,09 % | en attente |
| `67f7…9ba` | 25 601 / 6 | −79,75 / +9 210,55 / +36 304,35 | −1 253,40 / 3,23 % | en attente |

Les fiches distinguent fills, ordres inférés des fills, couverture requêtée, courbes déclarées, flux classés et funding de scope/devise inconnus. Elles nomment aussi l’insuffisance des valorisations, des fenêtres fill/ledger, de la consolidation du capital, des frais et des expositions externes. Au cutoff, les dernières valorisations perp avaient 7 h 40 min 06 s, 7 h 34 min 53 s et 7 h 47 min 05 s de retard, toutes au-delà de la limite d’une heure. Le tranche de qualification archivé du 9 octobre est lui aussi sans période choisie ni scope mesuré pour ces trois adresses. `economic_validation=false` reste la décision pour les trois.

## Vérifications

Les tests de régression ajoutés couvrent les 80 échecs immédiats, le mélange succès/échec, l’exclusion après appel, le rafraîchissement à 24 h et la remise à zéro des échecs, la reconstruction stable au cutoff et la route `deepen` sans scope. La suite complète passe : **460 tests**. Le classement corrigé a été reconstruit sans persister de nouvelles décisions : 61 030 payloads archivés lus, 0 appel fournisseur, 0 décision modifiée. Le timer périodique n’a pas été déclenché manuellement.

## Décision et suites

F1–F4 sont corrigés/documentés dans le périmètre borné. R5 est complété par la règle de fraîcheur et la voie `deepen`; le plafond inchangé est quatre tentatives par tick de quinze minutes. Les résultats antérieurs sont conservés. Les trois comptes demeurent des présélections descriptives, sans qualification économique ni autorisation de recherche IA.

Lacunes externes qui restent à fermer pour toute qualification : valorisations fraîches alignées sur six heures, périmètre de collatéral et DEX consolidé, couverture retenue des fills/ledger/funding, classification des flux et unités, frais/FX, comptes ou hedges hors plateforme, et attribution indépendante reproductible. Aucune de ces lacunes n’a déclenché de nouvelle collecte dans ce lot.
