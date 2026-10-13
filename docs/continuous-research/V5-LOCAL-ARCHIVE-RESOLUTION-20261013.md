# Résolution locale du `needs_data` v5 — 2026-10-13

## Décision et limites

La tâche v5 `75c617af00435dab9bf1dd614aa5cbaddc26700446110affaaf7c781f0892746` avait déjà été activée et consommée avant cette tranche. Le registre conserve deux appels, état final `needs_data`; cette tranche n’a effectué aucun appel IA, lancement paper, ordre réel ni collecte réseau.

| Appel enregistré | Usage | Coût déclaré |
| --- | --- | --- |
| Proposition | 72 143 tokens entrée, 1 698 sortie, 63,705 s | `included`, 0,00 USD |
| Critique | 72 942 tokens entrée, 565 sortie, 23,961 s | `included`, 0,00 USD |

Total déclaré : 145 085 tokens entrée, 2 263 sortie, 87,666 s; 2/2 appels, 0,00 USD facturé déclaré. L’autorisation dédiée est `completed`, `calls_started=2`, et le runtime en reprise retourne `unchanged_no_inference`. Les huit essais historiques sont préservés; le compteur engagé reste à 9 avant et après la préparation locale. Aucun essai n’a été réarmé.

La proposition décrit un mécanisme plausible d’hystérésis d’inventaire : seuil minimum, arrondi, indisponibilité de cotation et exécution partielle peuvent empêcher un ajustement voulu. La critique conclut que les données ne permettent pas l’attribution causale par tentative. Ce résultat n’établit ni rentabilité ni avantage prédictif.

## Couverture locale

La fenêtre paper archivée couvre `1791875646458` à `1791877446807` (30 min et 349 ms). Le paquet conserve 521 occasions, 11 707 événements BBO, 3 323 l2Book, 60 heartbeats, 30 événements d’abonnement et 234 fills source. Il déduplique 449 contenus de cotation et référence 386 observations brutes avec SHA-256, disponibilité d’archive et index d’événement.

| Demande v5 | Classement fondé sur les archives |
| --- | --- |
| Enregistrements canoniques par tentative | Partiel : 521 occasions exportées, mais zéro identifiant d’essai, décision, événement source, quote ID, fill ID, cible ou ajustement brut/arrondi; 29 lignes ont un état après exécution. Les tailles et notionnels ne sont présents que sur 77 lignes. |
| Prix, profondeur et santé de flux | Présents avec ambiguïtés : les instantanés BBO/l2Book et les événements de santé sont exportés. 434/521 reçus de cotation ont un âge enregistré ≤1 s. L’archive indique une disponibilité antérieure à la décision pour 521/521, alors que le champ de disponibilité mémorisé le fait pour 169/521; les deux timestamps concordent pour 0/521. Plusieurs contenus peuvent correspondre à une même occasion. Ces candidats rétrospectifs ne certifient pas la cotation sélectionnée par le moteur. |
| Événement source → décision | Lien historique absent et irrécupérable à partir des champs conservés : aucune clé causale ni payload ordonné par décision. Des candidats temporels ne remplacent pas une relation exacte. |
| Inventaire après la borne et fermeture | Observation future nécessaire : l’endpoint conserve `-0.61 HYPE` et une réduction en attente vers `-0.32702`. Aucun état ultérieur n’établit la fermeture; 0 événement de funding archivé ne prouve pas l’absence de funding. La session n’a pas été reprise et aucune clôture n’a été inventée. |

## Raccordement et paquet prêt

Résolution locale persistée : `93860ff0ee02d2a10fc8cd22408a9acadd2769ae63b340af0e3e2f3be16415ef`. Paquet `paper-local-evidence-research-v1`, empreinte `98814ea21e62df67dadd968590003e618abbb20c1c80892cce648ce5dfca350f`, 216 726 caractères sur 225 000 autorisés. Child prêt : `e5d99a38dcf8b890ecb76aaf82ca84869024ce27d64ff885528dfe3ec53b3e2d`, état `budget_required`, `activated_ms=NULL`.

Une nouvelle connexion SQLite a revalidé le paquet et ses observations archivées. Une présentation identique retourne `unchanged`; les identifiants de résolution et child restent identiques, sans doublon ni appel. Une modification du contenu de cotation produit un nouveau fingerprint et un nouveau child. Le scheduler paper exécute maintenant cette résolution locale sur les tâches `needs_data`; 52 tests ciblés confirment le parcours, le contrôle des réserves et l’absence d’inférence.

La route historique de la tâche v5 est conservée. Son résultat validé alimente une nouvelle route `needs_data`; la route du child reste `budget_required` et attend une activation explicite. Cette tranche n’autorise pas cette activation.

## Limites d’usage et action suivante

Le contrat `paper-adaptation-research-v1` passe en mode `subscription` : au plus 2 appels, 80 000 tokens d’entrée par appel, 160 000 au total, 5 000 tokens de sortie par appel, 10 000 au total, 120 s par appel et 240 s cumulées. Les USD ne sont plus réservés fictivement. L’usage inclus et les coûts connus/estimés sont enregistrés séparément; le mode `pay_as_you_go` garde son plafond monétaire. Les autorisations historiques ne sont pas réécrites. Aucun fournisseur ni budget global n’a changé.

**Prochaine action automatique :** au prochain tick paper, le scheduler revoit les archives et retourne `unchanged` si elles n’ont pas changé; une preuve réellement nouvelle peut préparer un paquet distinct. Le child actuel reste en attente. **Action manuelle restante :** toute activation de ce child nécessite une nouvelle autorisation dédiée, bornée aux plafonds ci-dessus; l’observation de la fermeture HYPE requiert une future collecte ou un endpoint observé, sans reprendre cette session.

## Reproduction

```sh
python scripts/resolve-paper-local-archives.py \
  --db data/tamtam.sqlite3 \
  --request-id 75c617af00435dab9bf1dd614aa5cbaddc26700446110affaaf7c781f0892746
```

La commande ne fait que lire les archives déjà autorisées et préparer de façon idempotente un child `budget_required`. Elle n’appelle aucun modèle et ne démarre pas de session.
