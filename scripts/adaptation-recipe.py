#!/usr/bin/env python3
"""Dedicated temporary DB only; no production DB or provider input."""
import argparse,json
from pathlib import Path
from tamtam_again.adaptation_recipe import run_recipe
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
print(json.dumps(run_recipe(a.output),indent=2))
