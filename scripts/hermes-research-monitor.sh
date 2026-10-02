#!/bin/sh
set -eu
cd /home/Untergame/tamtam_again
exec .venv/bin/python -m tamtam_again workflow-tick --stage research
