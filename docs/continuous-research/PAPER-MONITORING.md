
## Diagnostic automatique après suspension

`paper_adaptation.py` inscrit un diagnostic scellé par session suspendue dans
`paper_adaptation_requests`. Le tick réel écrit état, suspension, snapshot paper
et demande dans la même transaction : une panne d'inscription annule l'ensemble
du tick, qui peut être rejoué sans perdre les preuves ni changer la version.
Le pipeline récupère aussi au plus huit suspensions sans diagnostic par tick,
avec reprise idempotente. Il lit uniquement la suspension et le snapshot paper
correspondant à l'empreinte de l'état, jamais l'archive ou les fenêtres réservées.
Une preuve absente/future/incohérente bloque la demande au lieu d'être inférée.

Routage déterministe :

| Diagnostic | Action suivante |
| --- | --- |
| Connexion/abonnement/heartbeat défaillant | Corriger collecte et réconcilier position, prouver état sain |
| Signal leader non reçu en direct | Revoir disponibilité causale ou modèle explicite de retard |
| Limite nette/drawdown atteinte avec collecte saine | Déclarer budget de diagnostic et nouvelle comparaison prospective |
| Durée maximale consommée | Conserver l'expérience et déclarer toute suivante |
| Code inconnu | Revue du diagnostic avant autorisation |

Une panne de collecte prend priorité sur l'attribution économique d'une perte.
Le franchissement de limite est un arrêt de sécurité, pas une preuve statistique
de disparition d'un avantage. La demande garde tous les déclencheurs, les preuves,
leurs disponibilités et metrics paper ; elle n'optimise aucun paramètre.
`model_calls_authorized=0`, `promotion_authorized=false`, `resume_authorized=false`.
Les positions, résultats et critères restent attribués à l'ancienne version.

Ce bloc automatise diagnostic et demande de travail. L'exécution d'une nouvelle
recherche exige encore une politique IA bornée explicite, puis des fenêtres
futures et le passage normal comparaison/finale/paper. Le budget population
initial n'est pas réarmé et une demande ne le contourne pas. La détection de
changements de comportement et le diagnostic statistique de performance restent
à compléter au-delà des limites de perte déjà préétablies. Les anciens états
sans snapshot cohérent nécessitent une correction explicite et peuvent rester
bloqués ; la récupération ne reconstruit pas de résultat absent.

Preuve réelle `paper-adaptation-control-20261008.json` : metadata uniquement,
aucune session réelle disponible pour démontrer le parcours. Les tests couvrent
panne+perte, disponibilité, divergence, positions préservées, replay et rollback
injecté pendant un tick réel simulé sans archive. Ces fixtures ne valident aucune
stratégie réelle.

Migration additive : table paper_adaptation_requests, aucune réécriture d'état.
Retour arrière : retirer l'appel de record dans paper_tick et recover dans le
pipeline avec le module ; conserver table, suspensions, snapshots et ledger.
Aucune reprise automatique d'une session suspendue ne doit accompagner le retour.

## Reprise équitable des preuves manquantes

Le registre additif `paper_adaptation_recovery` conserve, par session, le dernier
cutoff tenté et le nombre d'échecs de preuve. La sélection bornée traite d'abord
les dossiers les moins tentés : huit dossiers incomplets ne bloquent plus une
session suivante disposant de son snapshot. Un échec n'est pas retenté au même
cutoff. Une correction de preuve permet la création de la demande immuable au
passage suivant. Aucun retry de modèle, réarmement ou reprise paper n'en découle.
Le registre mutable de reprise n'est pas présenté comme un journal complet des
incidents ; le diagnostic scellé reste la preuve immuable.

`registry_trace` inscrit `paper_adaptation_diagnosed` à la date de création du
diagnostic, avec son identifiant et sa référence, sans exporter JSON diagnostic,
métriques paper ou contenu réservé. Une suspension antérieure ne rend pas un
diagnostic futur accessible rétrospectivement.

Tests synthétiques : huit dossiers sans preuve puis un dossier valide ; absence
de répétition au même cutoff ; arrivée d'une preuve ; visibilité chronologique.
Retour arrière : restaurer recovery/trace, conserver la nouvelle table sans la
supprimer. Aucun historique, position ou snapshot n'est modifié par ce rollback.
La proposition IA après diagnostic reste à raccorder sous politique bornée.

## Demande de recherche paper séparée de la population

`PYTHONPATH=src .venv/bin/python scripts/paper-research-seal.py --db data/tamtam.sqlite3 --adaptation-request-id ID --policy POLICY.json`

La commande scelle seulement une demande, sans appel IA. Politique explicite
`version=paper-adaptation-research-v1`, justification et budgets requis :
max_requests, max_packet_chars, minimum_interval_ms, timeout_seconds,
max_output_tokens, max_request_age_ms, model, call_reservation_usd ; éventuel
max_prompt_chars doit couvrir le paquet. Aucun nouveau défaut de budget ni timer
n'est activé. Le registre additif paper_research_jobs ne réarme pas les huit
jobs population : tous les essais paper scellés comptent, même si la politique
change, et une suspension conserve une seule demande.

Seul research_budget_required est éligible. Panne collecte/signal/budget ou
mapping inconnu conserve sa route existante. Le paquet contient la règle gelée,
le diagnostic/snapshot paper, identité et période de la session, preuves et
limites. Métadonnées compte/temps sont contrôlées avant lecture du diagnostic et
de la règle ; toute intersection avec comparaison/finale non libérée sur un
marché du même compte bloque. Aucune observation brute ni résultat réservé
n'est consulté. Les preuves doivent être disponibles, la règle gelée avant le
paper et le snapshot chronologiquement compatible. Pas de période économique
inventée ni de mutation ancienne règle/positions/session.

Scellement transactionnel et idempotent ; dépassement taille/budget reste
explicite. Trace metadata-only paper_research_sealed à created_ms. Les tests
synthétiques couvrent scellement/replay, budgets, causalité/réserves, dépassement
et routes non performance. Ce registre n'est **pas encore un worker IA ni une
comparaison prospective automatique** ; ces raccordements restent à terminer.
Aucune session réelle ne démontre ce parcours à ce stade. Rollback retire
commande/exports et garde table et preuves, sans relancer de job scellé.
