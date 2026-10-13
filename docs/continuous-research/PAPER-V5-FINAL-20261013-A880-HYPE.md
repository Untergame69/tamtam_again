# Bilan final paper HYPE v5 — sélection d'ordre pré-exécution

**Question figée :** sélectionner une instruction complète admissible avant simulation rend-il la taille choisie, le fill partiel réel et le reliquat mécaniquement interprétables, sans réécrire le fill après observation de la profondeur ? Cette session n'évalue pas une rentabilité.

## Résultat opérationnel

- Hypothèse `a880-hype-live-delta-follow-v5-closeable-order-selection`, spec SHA-256 `2db7cc5bcb82e5e2716019f338b9ed7dea18f48a243911ac34d1df9bc3d0219a`.
- Session indépendante `37116951b6654b5c9ab3f116e44b44b4`, démarrée le 13 octobre à 07:14:06 UTC et arrêtée automatiquement à 07:44:06 UTC, après 30 minutes. Six bilans automatiques; le dernier est `bbbb582df100145fb3ee58b3d336e6c2683da023594b39ed71edbb5e81a2f0a9` et recommande `propose_new_version` après fin de fenêtre.
- 234 signaux live, 29 fills, dont 4 partiels, et 97 occasions manquées. Motifs : 24 sous minimum d'ordre, 20 cotations trop anciennes, 18 cotations indisponibles au point de décision, 9 ajustements reduce-only sous minimum, 10 arrondis reduce-only à zéro, 15 ajustements généraux arrondis à zéro et 1 signal reçu après le début d'une sortie par horizon.
- La règle v5 a été activée une fois : l'instruction complète `−0,17 HYPE` (notionnel 14,0556 USDC) a été choisie avant simulation et remplie intégralement; la position `+0,17` est passée à zéro. La cotation BBO avait 723 ms à la décision. Cette fenêtre n'a donc pas produit de fill partiel après sélection; le test ciblé couvre ce cas : instruction `−0,29`, profondeur permettant `−0,20`, position réellement restante `+0,09`, sans plafonnement du fill.
- À la suspension de durée, la position paper reste `−0,61 HYPE`; un ordre reduce-only paper visait `−0,32702 HYPE`, avec échéance après le dernier tick du moteur. Il n'a pas été exécuté par le rapport final. Le bilan de fenêtre est terminé, mais la liquidation et le résultat du dernier aller-retour demeurent inconnus. Aucun fill de clôture n'a été ajouté. La session v5 n'est pas relancée.

## Coûts observés

Le snapshot final rapporte un PnL net marqué de `−0,5240812203805 USDC`, un réalisé de `−0,308294375`, un latent de `+0,040560895`, des frais de `0,2563477403805` et un drawdown de `0,5932020011175 USDC`. Aucun funding n'a été observé; son absence ne signifie pas un financement nul. Le seuil de perte préétabli de 10 USDC n'a pas été atteint. Ces nombres décrivent cette courte session paper et ne servent pas à conclure sur une rentabilité.

Le tick réel avait une cible de 600 ms; le maximum observé final était 806 ms, avec un maximum de traitement de 637,563 ms. La limite de fraîcheur d'une seconde est restée fixe et chaque exécution enregistrée garde sa cotation causale et son âge.

## Chaîne de preuve

Voir le [bilan final structuré](PAPER-V5-FINAL-20261013-A880-HYPE.json). Le registre `execution_correction_requests` a consommé la demande `a880-hype-v4-closeable-reduction-20261013-v2` par la route déterministe « correction d'exécution », sans insertion dans la file de recherche IA. Il lie le diagnostic v4 `priority_exit_unresolved_position`, le correctif moteur, la variante v5 `07ec042fd7ef433cf581668557ac1d3d23238f70030ed73b27ebcf1e67390b06`, la session ci-dessus et son rapport final `bbbb582d…`.

La v4 précédente reste conservée : son rapport #5 n'est pas réécrit; l'ordre virtuel expiré a reçu une trace d'annulation administrative `e71782aaf2f7dfdb8d434058e3392eeef04ec258c64df62aedf573113b3ac246`. Son bilan indique toujours `+0,05 HYPE`, sans fill de clôture, avec résultat final inconnu. Le rectificatif lié est `5c3ee0818673ff271d42d039a6c254af005a4d3938b271524e608619928fc2f7`.

La session v5 n'entraîne aucune suite automatique. Toute nouvelle expérience exigerait une nouvelle question et une autorisation distincte. Aucun ordre réel ni appel IA n'a été émis.
