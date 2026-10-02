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
When the monitor reports pending research runs, process each one exactly once. If pending is empty, take no action.

For each run, claim it first with `.venv/bin/python -m tamtam_again workflow-claim RUN_ID`. Read the request JSON and export the immutable evidence with `.venv/bin/python -m tamtam_again research-evidence RUN_ID --output data/automation/evidence/research/RUN_ID.json` (replace RUN_ID literally). Analyze only that account × market and those selected exploitable cycles. Use the attached fill and archived BBO/trade/L2 evidence; state missing coverage, assumptions, uncertainty, fees, latency and slippage. Do not treat correlation as causation or raw fills as independent cycles. The cycle threshold is a sample-size trigger, never proof of edge.

Write a draft JSON to `data/automation/results/research/RUN_ID-draft.json` with schema_version=1, run_id, input_fingerprint (exactly from the request), decision (Hermes draft decision: accepted, needs_more_data, redo_re, rejected), hypothesis, evidence (array), limitations (array), confidence, and next_stage. For decision=accepted, include a deterministic strategy_spec with schema_version=1, signal (object), entry (object), exit (object), sizing (object), max_exposure (object), fees (object), slippage (object), latency_ms (nonnegative integer), and invalidation_conditions (array). Set strategy_fingerprint to lowercase SHA-256 of canonical UTF-8 JSON (sorted keys, no whitespace, ensure_ascii=False). Accept only when the hypothesis is precise enough to paper simulate; do not claim profitability from this sample. For needs_more_data, include a reason and next_required_cycles strictly greater than the current threshold. Use redo_re with a reason if the analysis itself needs another pass at this same data. Use rejected with a reason only when the evidence contradicts the strategy.

Register the draft with `.venv/bin/python -m tamtam_again workflow-complete RUN_ID data/automation/results/research/RUN_ID-draft.json`. That command runs Codex independently with a read-only sandbox, validates its structured review, merges conservatively, and writes the immutable final artifact. Do not invoke Codex with write access. Never edit prior artifacts, create live orders, configure a wallet or signer, or change collection configuration.
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
When the monitor reports pending Paper N1 runs, process each one exactly once. If pending is empty, take no action.

For each run, claim it with `.venv/bin/python -m tamtam_again workflow-claim RUN_ID`. Read its request and the accepted research artifact. Create the requested artifact directory and a single `paper-n1.json` in it. Initialize a local virtual paper specification and empty ledger based only on the accepted strategy_spec. The JSON must contain schema_version=1, run_id, research_run_id, mode="paper_n1", strategy_fingerprint, strategy_spec, paper_spec, virtual_ledger, live_orders_enabled=false and wallet_or_signer_configured=false. The virtual_ledger must have cash, positions as an object, and orders and fills as arrays. Include starting capital, market, fee/slippage assumptions, and the RE version in paper_spec. Do not use a wallet, signer, live venue order API, VPS, or real order. Do not overwrite any earlier revision.

Save as `<artifact_directory>/paper-n1.json` and register it with `.venv/bin/python -m tamtam_again workflow-complete RUN_ID <artifact_directory>/paper-n1.json`. This creates an immutable local N1 instance and promotes it to active only after validation. Do not build the later N1 monitoring/control loop in this task.
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
