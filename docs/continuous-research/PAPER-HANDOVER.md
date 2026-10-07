# Surveillance et remplacement paper

Les nouveaux plans peuvent déclarer deux politiques optionnelles. Elles sont
incluses dans le fingerprint immuable du plan, avant comparaison et finale.
Les plans pilotes existants ne sont pas modifiés.

```json
{
  "paper_monitoring": {
    "version": "paper-loss-budget-v1",
    "max_net_loss_usdc": "5",
    "justification": "Exemple de budget choisi, à remplacer par une justification propre à l'expérience"
  },
  "paper_replacement": {
    "version": "suspended-flat-handover-v1",
    "predecessor_variant_id": "IDENTIFIANT_EXISTANT",
    "minimum_session_age_ms": 3600000,
    "justification": "Exemple de délai choisi et de relation entre versions"
  }
}
```

Ces nombres sont des exemples, pas des valeurs par défaut. Le prédécesseur doit
exister dans le même compte, marché, réseau et provenance réelle/synthétique.
La remplaçante doit passer sa propre validation, sur une nouvelle période finale
non consommée. Une ancienne période ne redevient pas vierge.

Le démarrage automatique par la pipeline ne retire que le prédécesseur désigné,
suspendu, suffisamment ancien, sans position ni ordre en attente. Un compte avec
une autre session non retirée bloque le transfert. Session active, position
ouverte, ordre pending et délai insuffisant restent des états d'attente.

Retrait, création et lien `paper_handovers` sont une seule transaction SQLite.
Un incident annule les trois opérations ; une reprise conserve l'ancienne
session ou retrouve la nouvelle session active. Le ledger et les positions ne
sont jamais déplacés, fusionnés ou effacés. Le capital de la nouvelle session
reste indépendant : ce transfert ne démontre pas la continuité du capital de
la procédure et ne permet pas d'additionner ses rendements sans comptabilité
supplémentaire. Le lien est exporté causalement dans la trace des registres.

La suspension conserve ses preuves dans `paper_suspensions`. Un résultat net
atteignant le budget de perte déclenche la suspension au tick ; ce contrôle ne
garantit pas une perte maximale entre ticks. Le drawdown de la stratégie reste
un garde distinct. Une suspension ne constitue pas une preuve statistique de
disparition d'avantage.

Le retour à une ancienne règle exige une nouvelle variante liée à un nouveau
plan prospectif, sa propre validation et une politique désignant la version
qu'elle remplace. Une version retirée ne se réactive pas automatiquement. La
CLI permet un retrait opérateur d'une session plate et un redémarrage explicite
avec motif ; celui-ci n'est pas une nouvelle validation de l'avantage.

Tests : `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.
La fixture vérifie cooldown, position ouverte, incident à l'insertion, rollback,
conservation de l'état et idempotence. Aucun paper réel activé par cette recette.
Retour arrière : code ciblé, préserver les tables additives et tous les états ;
ne pas restaurer toute la base ni effacer une position simulée.
