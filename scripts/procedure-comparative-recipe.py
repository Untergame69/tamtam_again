#!/usr/bin/env python3
import argparse
from pathlib import Path
from tamtam_again.procedure_recipe import run_recipe
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
r=run_recipe(a.output);print(r['report']['status'])
