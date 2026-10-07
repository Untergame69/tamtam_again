#!/usr/bin/env python3
"""Always use a fresh temporary synthetic DB; never accepts a production DB."""
import argparse,json
from pathlib import Path
from tamtam_again.population_recipe import run_recipe
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
a=p.parse_args();print(json.dumps(run_recipe(a.output),indent=2))
