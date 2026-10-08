#!/usr/bin/env python3
"""Dedicated temporary DB only; no production DB or provider input."""
import argparse,json
from pathlib import Path
from tamtam_again.adaptation_recipe import run_recipe
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--observation-followup',action='store_true',help='Include missing observations, public fixture acquisition and paper reassessment')
a=p.parse_args()
print(json.dumps(run_recipe(a.output,observation_followup=a.observation_followup),indent=2))
