# Profils descriptifs de population

`behavior.py` mesure les observations disponibles sur une période explicite :
activité par marché, maker/taker/inconnu, tailles, notionnels dans la devise du
marché, intervalles, ordres produisant plusieurs fills et concentration des
notionnels sur cinq fills. La médiane est le quantile inférieur de l'échantillon.
Les moitiés de période montrent des comptes de fills, sans correction supposée
d'une couverture incomplète.

Les positions après fill sont reconstruites uniquement lorsque startPosition,
side, taille et prix sont disponibles. Les expositions sont des échantillons au
prix d'exécution, pas une trajectoire de risque valorisée continuellement.
Aucun notionnel de devises différentes n'est additionné.

Le reducer de cycles existant expose, via une option explicite, les excursions
descriptives non exploitables ; son comportement par défaut pour les pilotes
reste inchangé. Les profils n'exportent pas de PnL ou frais de ces excursions.
Les flags de couverture restent faux sans preuve. Un retour à l'inventaire de
fond ne représente pas sa clôture ni la durée de détention de toute la position.

Les groupes multi-marchés utilisent un découpage temporel configurable de
1000 ms, paramètre exploratoire, pas une preuve de coordination. Des événements
proches séparés par une borne peuvent apparaître dans des groupes différents.
Les questions proposées exigent encore continuité d'inventaire, cycle de vie
des ordres, références de marché et modèles d'exécution. Elles ne qualifient
aucune règle ou compte économiquement.

Une même identité coin/time/tid ne compte qu'une fois. Les identités financières
contradictoires sont exclues du descriptif et signalées ; aucune dernière valeur
ne remplace silencieusement une première. Événements futurs ou disponibles après
as-of sont refusés. Le script lit exclusivement la source population REST et
refuse les adresses réservées avant lecture des observations.

## Exécution et preuve réelle

Chaque nouveau passage population conserve le profil de ses pages courantes
dans le rapport d'inventaire. Il ne prétend pas couvrir toute la période.
Le script produit un profil de toutes les pages population archivées :

```sh
PYTHONPATH=src .venv/bin/python scripts/population-behavior-report.py \
  --db data/tamtam.sqlite3 --start-ms 1791278383600 \
  --end-ms 1791364783600 --output /tmp/behavior.json
.venv/bin/python -m unittest discover -s tests -q
```

Contrôle réel résumé : behavior-control-20261007.json ; 19 comptes et 9428 fills
observés, 999 excursions descriptives non déclarées exploitables. Les nombres
peuvent évoluer avec les nouvelles réceptions historiques ; l'as-of et le
fingerprint de ce rapport sont conservés. Aucun compte rentable déclaré.

Retour arrière : arrêter uniquement le worker population pour annuler le commit,
conserver les anciens rapports. Les pilotes gardent l'option par défaut du
reducer. Aucune migration destructive et aucun abonnement supplémentaire.

La tâche de préétude reste partielle : trajectoire consolidée, interprétation des
changements et fiches des mécanismes/précisions de chaque marché restent à livrer.
