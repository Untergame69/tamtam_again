# Compte rendu externe — G1 et G2

Date/cutoff d'analyse : 12 octobre 2026; classement au cutoff `1791789394195` (`2026-10-12T07:16:34.195Z`). Périmètre du lot : ordonnanceur de courbes et qualification historique de trois présélections. Aucun appel IA, aucune collecte API, aucun budget ni quota augmenté. L'ancien classement et la fiche antérieure sont conservés.

## G1 — progression équitable au quota existant

La politique de file est versionnée `historical-curve-queue-v3`; elle conserve au plus quatre tentatives logiques par tick, toutes les quinze minutes (plafond théorique inchangé : 384/tour de jour, 80 unités réservées/tick, 5,333 unités/minute en moyenne avant autres consommateurs et reprises HTTP internes). Elle répartit les créneaux en **1 première découverte + 1 reprise d'échec + 2 rafraîchissements**; tout créneau inutilisable est prêté aux voies qui ont des éléments éligibles. Les tentatives, y compris échecs et exclusions après appel, restent plafonnées. Les reprises d'échec sont comptées séparément.

La sélection avance par ancienneté plutôt que par un rang de hash fixe : candidats jamais observés/les moins récemment examinés d'abord; reprises par ancienneté de dernière tentative; refreshs par observation la plus ancienne. Une observation n'est éligible au refresh qu'après 24 h et que son `next_due_ms` est atteint. L'attente d'un refresh est calculée depuis `max(next_due_ms, observed_at + 24 h)`. Les deferrals protégés mettent à jour l'heure de dernière examination afin qu'un préfixe protégé ne consomme pas indéfiniment les 80 inspections par tick. Les autorisations/protections restent vérifiées avant et après l'appel, avec écriture interdite si la protection apparaît après l'appel.

La régression `tests/test_historical_curve_queue.py` exerce le vrai `tick()` avec SQLite mémoire, client simulé et horloge simulée : 500 candidats initiaux, 80 nouvelles adresses par jour, 288 ticks de 900 secondes sur trois jours, échecs transitoires et refreshs. Elle vérifie des tentatives dans chacune des voies (découverte, retry, refresh), de nouvelles adresses persistées chaque jour, des refreshs aux jours 2–3, la progression cumulative et au plus quatre appels par tick. Les agrégats de cette exécution sont enregistrés dans [`historical-queue-fairness-g1-20261012.json`](historical-queue-fairness-g1-20261012.json). Un autre cas place 100 adresses sous protection : 80 sont différées au premier tick; après levée de la protection au tick suivant, les quatre appels vont aux 20 comptes au-delà du préfixe.

Les compteurs sont renvoyés par `tick()` (tentatives découvertes, retries, refreshs, files en attente, comptes jamais tentés, âges d'attente discovery/retry/refresh). `scripts/population-historical-queue-tick.py` sérialise déjà tout le retour en JSON; la prochaine exécution programmée inclura donc ces champs. La simulation périodique ci-dessus est la preuve fournie dans ce lot. **Le timer de production n'a pas été déclenché pour ce test**, car cela ferait des appels REST réels; l'exécution périodique réelle de la politique modifiée reste donc à observer dans son prochain journal planifié.

### Capacité et attente

À 384 tentatives/jour, la capacité totale ne promet pas un refresh quotidien d'un registre de 8 510 comptes. Le délai de 24 h est seulement l'âge après lequel une observation rejoint la file de refresh; il ne garantit pas que chaque adresse sera rafraîchie à cette échéance. Avec deux créneaux refresh réservés sur quatre (avant redistribution), la capacité réservée est 192 refreshs/jour en régime de files pleines, ce qui implique une attente de rotation qui peut atteindre plusieurs semaines pour des milliers de comptes. Les compteurs d'âge permettront d'observer cette attente; il n'y a pas d'engagement de fraîcheur générale.

## G2 — qualification historique

Les valeurs ci-dessous proviennent des séries archivées `allTime.pnlHistory` et `allTime.accountValueHistory` à des timestamps communs, avec l'écart entre séries explicitement affiché. Les deltas sont nominaux du fournisseur et ne sont pas des rendements nets. Les `accountValueHistory` ne sont pas un PnL ajusté. La règle six heures/début ±15 min/âge final ≤1 h est maintenue pour la validation comptable récente seulement; elle n'a pas bloqué l'analyse 30/90/180 jours. Les sources et pages sont détaillées dans [`economic-performance-archive-check-20261012.json`](economic-performance-archive-check-20261012.json); les fiches, avec les lacunes par compte, sont dans [`economic-qualification-cards-20261012-g2.md`](economic-qualification-cards-20261012-g2.md).

| Présélection | PnL déclaré 30 / 90 / 180 j | Valeur de compte 30 / 90 / 180 j | Baisse échantillonnée PnL (180 j) | Frais des pages fills archivées | Décision utile |
|---|---:|---:|---:|---:|---|
| `a880…4ee` | +16 094,87 / +56 403,54 / +128 249,47 | +109 518,37 / +118 032,39 / +101 776,99 | −5 860,76 | 279,079860 USDC | approfondir l'alignement des sources |
| `be504…77b` | +193 867,76 / +266 983,24 / +365 968,59 | +197 256,56 / +425 132,76 / +862 941,96 | −331 858,71 | 320,973957 USDC + 0,003779995 UZEC | approfondir priorité à risque/périmètre |
| `67f7…9ba` | −79,75 / +9 210,55 / +36 304,35 | +2 031,64 / −6 790,16 / −7 165,31 | −6 845,33 | 500,041022 USDC | garder le signal, ne pas prioriser avant rapprochement |

Fenêtres réellement observées : environ 32/95/186 jours, sans interpolation. Les écarts `accountValueHistory − pnlHistory` valent pour a880 +93 423,50 / +61 628,85 / −26 472,48; be504 +3 388,80 / +158 149,52 / +496 973,37; 67f7 +2 111,39 / −16 000,71 / −43 469,66. Ils ne sont pas attribués aux flux. Les pertes intermédiaires sont des bornes échantillonnées; elles ne démontrent pas la perte maximale intra-période.

Pages fills disponibles : 3,504/4,964/4,661 jours contigus sur la requête cible 30 jours, donc les frais indiqués ne sont pas des coûts complets de ces fenêtres et n'ont pas été extrapolés ou déduits des horizons historiques. Flux/funding normalisés sont eux aussi limités aux pages répertoriées, parfois d'un scope/devise incertains; l'audit garde les références exactes et les comptes dédupliqués. Les historiques de capital, exposition/levier, collateral, intégralité des événements, conversion des monnaies, fees complètes, couverture spot/vaults/HIP-3 et hedges externes ne sont pas établis. Aucune absence dans les pages ne vaut zéro et aucun compte n'est déclaré globalement rentable ou non rentable.

## Action minimale / statut

- **a880…4ee :** un intervalle historique borné avec deux snapshots portfolio alignés et ses pages complètes de fills/fees/funding/ledger, pour expliquer l'écart valeur/PnL et les −23 000 USDC observés.
- **be504…77b :** le même rapprochement sur une fenêtre unique après délimitation documentée de l'account portfolio-margin, du sous-compte et des DEX; établir quelles equities peuvent être consolidées et séparer les devises.
- **67f7…9ba :** commencer par tenter de résoudre depuis les pages déjà archivées la divergence entre PnL positif 90/180 j et valeur de compte négative; si les pages ne couvrent pas les bornes, n'envisager qu'une collecte bornée ultérieure et distincte.

Ces actions sont des besoins de preuve pour une revue future, pas des ordres lancés dans ce lot. Les trois décisions restent descriptives; aucune n'autorise automatiquement une recherche IA, une RE ou un budget additionnel. La dernière valorisation disponible demeure trop ancienne pour une attestation comptable récente selon la règle en vigueur; cette limite n'invalide pas les signaux historiques exposés.

## Vérifications et limites

- Vérification : suite complète **462 tests réussie avant le changement de seul identifiant de version v2→v3**, puis les **9 tests ciblés de la file réussis après ce changement**; `git diff --check` et JSON valides. Scénarios couverts : quotas, échecs/transitoires, progression des trois voies, plafond quatre et préfixe protégé de 80 comptes.
- La sortie tick est imprimée en JSON par le script d'exploitation; aucune exécution réelle du timer n'a été déclenchée, de sorte que la preuve périodique de ce lot est une simulation déterministe, pas un journal du service mis à jour.
- L'audit économique est un artefact dérivé des archives locales en mode lecture seule et vérifiées au cutoff; il ne couvre pas des sources externes.
- Aucun appel IA de recherche, collecte REST réelle ni changement de budget n'est fait dans cette reprise. Les livrables locaux sont publiés dans Git après ces vérifications.
