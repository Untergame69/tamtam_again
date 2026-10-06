'use strict';
(async () => {
  const root = document.getElementById('hyperliquid-cohort');
  const reviewRoot = document.getElementById('hyperliquid-review');
  const date = value => new Date(value).toLocaleString('fr-FR', {timeZone:'Europe/Paris'});
  const el = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  let accounts = [];
  try {
    const response = await fetch('/api/tamtam-whales.json', {cache:'no-store'});
    if (!response.ok) throw new Error('cohort unavailable');
    const data = await response.json(); accounts = data.accounts;
    const heading = el('p', `${data.count} comptes · cohorte actualisée le ${date(data.updated_at)} (Paris)`);
    if (Date.now()-Date.parse(data.updated_at)>3600000) heading.append(el('strong', ' · relevé ancien, état actuel à confirmer'));
    const list = el('ul', ''); list.className = 'hl-accounts';
    for (const account of accounts) {
      if (!/^0x[0-9a-f]{40}$/i.test(account.address)) continue;
      const item = el('li', '');
      const link = el('a', account.label); link.href = 'https://hypurrscan.io/address/' + account.address;
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      item.append(link, el('p', 'Informations et activité publiques ↗'), el('code', account.address));
      item.append(el('p', 'Qualification complète : non vérifiée'));
      const ranks = (account.selection_evidence || []).filter(r => ['day','week'].includes(r.window));
      item.append(el('p', ranks.length ? 'Classement PnL actuel : '+ranks.map(r => `${r.window==='day'?'jour':'semaine'} #${r.rank}`).join(' · ') : 'Absent du classement récent exporté ; conservation du suivi, historique préservé.'));
      list.append(item);
    }
    root.replaceChildren(heading, list);
  } catch (_) { root.replaceChildren(el('p', 'Liste indisponible. Consulte la page de suivi ou réessaie.')); }
  try {
    const response = await fetch('/api/tamtam-account-review.json', {cache:'no-store'});
    if (!response.ok) throw new Error('review unavailable');
    const report = await response.json();
    const heading = el('p', 'Revue ponctuelle du '+date(report.updated_at)+' (Paris), indépendante du rafraîchissement de la cohorte.');
    const scope = el('p', report.scope);
    const filters = el('ul',''); for (const [name,value] of Object.entries(report.filters)) filters.append(el('li',name+' : '+value));
    const wrap = el('div',''); wrap.className = 'hl-review-table'; const table = el('table','');
    const head = el('tr',''); for (const text of ['Compte','Fills archivés','PnL latent standard (USD)','Levier standard','Filtres complets']) head.append(el('th',text));
    const thead = el('thead',''); thead.append(head); table.append(thead); const body = el('tbody','');
    const money = value => value===null ? 'Inconnu' : Number(value).toLocaleString('fr-FR',{maximumFractionDigits:0});
    for (const account of accounts) {
      const review = report.accounts.find(x=>x.address===account.address); const row = el('tr',''); row.append(el('td',account.label));
      if (review) {
        const metrics = review.performance.observed;
        row.append(el('td',money(review.observability.fills)),el('td',money(metrics.unrealized_pnl)),el('td',metrics.leverage===null?'Inconnu':Number(metrics.leverage).toFixed(1)+'×'));
      } else row.append(el('td','Non revu'),el('td','Inconnu'),el('td','Inconnu'));
      row.append(el('td','Non validés')); body.append(row);
    }
    table.append(body); wrap.append(table); reviewRoot.replaceChildren(heading,scope,filters,wrap);
  } catch (_) { reviewRoot.replaceChildren(el('p','Revue indisponible ; aucun statut de validation ne peut être déduit.')); }
})();
