#!/bin/sh
set -eu

repo=/home/Untergame/tamtam_again
hermes=/home/Untergame/.local/bin/hermes
scripts=/home/Untergame/.hermes/scripts
mkdir -p "$scripts"
install -m 0755 "$repo/scripts/hermes-research-monitor.sh" "$scripts/tamtam-again-research-monitor.sh"
install -m 0755 "$repo/scripts/hermes-paper-monitor.sh" "$scripts/tamtam-again-paper-monitor.sh"

existing=$($hermes cron list --all 2>/dev/null || true)
research_prompt=$(cat <<'PROMPT'
The legacy tamtam_again research dispatch is suspended because this runtime can
read the collector raw database and reserved validation periods. If pending is
empty, do nothing. Do not bypass workflow-claim, read reserved data, regenerate
legacy v1 requests, or raise cycle thresholds to evade this suspension.
Report any unexpected pending task as an isolation/configuration incident.
See docs/AGENT-CONTRACTS.md and docs/VALIDATION-PIPELINE.md. The deterministic
validation engine is the sole source of profitability measurements/promotions.

PROMPT
)
research_id=$(printf '%s\n' "$existing" | grep -B1 'Name:      tamtam-again-research' | head -n1 | awk '{print $1}')
if [ -n "$research_id" ]; then
  "$hermes" cron edit "$research_id" --schedule '5m' --prompt "$research_prompt" \
    --name tamtam-again-research --deliver local \
    --monitor-script tamtam-again-research-monitor.sh --workdir "$repo"
else
  "$hermes" cron create '5m' "$research_prompt" --name tamtam-again-research --deliver local \
    --monitor-script tamtam-again-research-monitor.sh \
    --workdir "$repo"
fi

existing=$($hermes cron list --all 2>/dev/null || true)
paper_prompt=$(cat <<'PROMPT'
The legacy Hermes N1 ledger-initialization task is suspended. An empty virtual
ledger is not evidence of an out-of-sample edge. If pending is empty, do nothing.
Do not produce or promote a legacy paper-n1.json. Real N1/N2 progression belongs
to the deterministic validation/paper commands and pipeline-tick after a frozen
v2 strategy passes predefined real-data criteria. See docs/VALIDATION-PIPELINE.md.

PROMPT
)
paper_id=$(printf '%s\n' "$existing" | grep -B1 'Name:      tamtam-again-paper-n1' | head -n1 | awk '{print $1}')
if [ -n "$paper_id" ]; then
  "$hermes" cron edit "$paper_id" --schedule '5m' --prompt "$paper_prompt" \
    --name tamtam-again-paper-n1 --deliver local \
    --monitor-script tamtam-again-paper-monitor.sh --workdir "$repo"
else
  "$hermes" cron create '5m' "$paper_prompt" --name tamtam-again-paper-n1 --deliver local \
    --monitor-script tamtam-again-paper-monitor.sh \
    --workdir "$repo"
fi

installed=$($hermes cron list --all 2>/dev/null || true)
printf '%s' "$installed" | grep -q 'Name:      tamtam-again-research' || {
  printf '%s\n' 'Hermes research cron was not installed.' >&2
  exit 1
}
printf '%s' "$installed" | grep -q 'Name:      tamtam-again-paper-n1' || {
  printf '%s\n' 'Hermes paper N1 cron was not installed.' >&2
  exit 1
}
