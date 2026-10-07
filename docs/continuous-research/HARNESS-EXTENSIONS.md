# Contrat d'extension et référence multi-instruments

Le registre `harness_extensions.py` distingue exécutable, expérimental,
spécification invalide et unsupported_mechanism. Une capacité manquante n'est
pas un résultat économique défavorable. L'état unsupported_mechanism est admis
par les décisions de pipeline. Le moteur v2 refuse un moteur dédié au lieu
de traiter silencieusement son contrat comme une stratégie single-market.

## portfolio_reference_v1

Première extension minimale : deux perpétuels en USDC, cibles signées fixes,
démarrage/horizon/délais/budget de risque déclarés, exécutions IOC indépendantes.
La règle sert à vérifier le moteur et ne présume aucun arbitrage ni profit.

Chaque marché a session, santé, quote disponible et inventaire propres. Une
quote reçue au même instant ne peut exécuter une décision ; reconnexion ou
déconnexion invalide la quote précédente avant les tentatives d'exécution.
Les deux marchés doivent être observables avant création de l'intention.
Leurs disponibilités peuvent diverger pendant le délai d'exécution.

Une jambe peut ne pas être exécutée ou être partielle, sans fill fictif sur
l'autre. Une intention produit une tentative IOC par jambe ; les résidus ne
sont pas réessayés comme si de nouvelles liquidités étaient apparues. Après
timeout, le moteur halt la prise de risque et tente de fermer les **positions
effectives**. Une position impossible à fermer reste au ledger, jamais effacée.
Les closes inachevés peuvent produire de nouvelles tentatives après timeout ;
les positions et tous les coûts restent attribués au même journal.

Le calcul de fill partagé avec v2 conserve prix moyen, PnL réalisé et frais une
seule fois. Le portefeuille additionne les variations de cash perp, le funding
et le latent sur quotes de sortie. L'exposition brute additionne les valeurs
absolues des deux jambes ; les longs et shorts ne se compensent pas pour ce
contrôle. Une jambe détenue sans marché sain rend la valorisation inconnue.
Le drawdown mesuré aux événements déclenche la clôture selon le budget choisi.

Le funding est un paiement signé par unité de **notre** position, appliqué avant
les ordres dus au même instant. Une réception tardive exige un replay dans
l'ordre effectif et reste refusée dans le reducer ; aucun paiement de baleine
ou montant reçu tardivement n'est appliqué à une position actuelle arbitraire.

La sérialisation du state permet une reprise avec la même empreinte de spec.
Un événement déjà traité est idempotent, un doublon contradictoire est refusé,
et une nouvelle version ne peut reprendre silencieusement ce journal.

## Limites et validation

160 tests passent après ajout des cas portfolio : comptabilité round-trip,
funding signé, exposition brute, jambe manquante/partielle, reprise JSON,
version, causalité, déconnexion/reconnexion et risque agrégé.
La recette portfolio-recipe-20261007.json est exclusivement synthétique,
normal et coûts/liquidité dégradés ; real_strategy_validated=false.

L'extension n'a pas encore d'adaptateur de validation réelle ou N2. Elle
**ne peut pas promouvoir une stratégie paper réelle**. Lot/minimum, liquidation,
tiers de marge, FX, référence de hedge et collecte synchronisée complète sont
encore à intégrer. Le moteur legacy garde son parcours et ses pilotes.
Ces limites figurent dans le contrat ; elles ne deviennent pas des rejets de
rentabilité. La tâche 10 reste partielle jusqu'à intégration plus complète.

```sh
PYTHONPATH=src .venv/bin/python scripts/harness-replay.py \
  --spec reference.json --events evenements.json --output /tmp/replay.json
.venv/bin/python -m unittest discover -s tests -q
```

Retour arrière : arrêter les workers pipeline/recherche avant annulation ciblée
du commit, conserver les éventuels diagnostics unsupported_mechanism et journaux
expérimentaux. Aucun changement du collecteur, aucun nouvel ordre, aucune
migration destructive ou nouveau plan réel.
