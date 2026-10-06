#!/usr/bin/env python3
"""Publish the authorized cohort panel without restarting shared services."""
import argparse
from pathlib import Path
import shutil
import datetime

parser = argparse.ArgumentParser()
parser.add_argument('--html-root', type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
root = args.html_root
page = root/'index.html'
source = page.read_text()
start = '<!-- TAMTAM_COHORT_START -->'
end = '<!-- TAMTAM_COHORT_END -->'
fragment = start+'\n'+(repo/'web/manhattam/cohort-section.html').read_text()+end+'\n'
if start in source:
    before, rest = source.split(start,1)
    _, after = rest.split(end,1)
    source = before+fragment+after
else:
    anchor = '      <section class="service-status-section"'
    if anchor not in source: raise SystemExit('Homepage insertion anchor missing')
    source = source.replace(anchor,fragment+'\n'+anchor,1)
source = source.replace('Archives Polymarket · infrastructure conservée · Hyperliquid à l’étude','Archives Polymarket · collecte Hyperliquid et recherche en cours')
source = source.replace('la prochaine piste étudiée est Hyperliquid.','la collecte Hyperliquid est en cours, avec les comptes présentés ci-dessous.')
script = '<script src="/assets/tamtam-cohort.js?v=1" defer></script>'
if script not in source: source = source.replace('</body>',script+'\n</body>',1)
backup = repo/'data/rollback'/('manhattam-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(page,backup/'index.html')
page.write_text(source)
shutil.copy2(repo/'web/manhattam/cohort.js',root/'assets/tamtam-cohort.js')
(root/'api').mkdir(exist_ok=True)
link = root/'api/tamtam-whales.json'
if not link.is_symlink() and link.exists(): raise SystemExit('Refusing to replace existing public cohort file')
if not link.exists(): link.symlink_to('../docs/tamtam-whales.json')
shutil.copy2(repo/'docs/recipes/account-review-20261006.json',root/'api/tamtam-account-review.json')
print('Published cohort panel; homepage backup:',backup/'index.html')
