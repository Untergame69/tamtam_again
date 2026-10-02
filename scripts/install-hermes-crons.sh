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

For each run, claim it first with `.venv/bin/python -m tamtam_again workflow-claim RUN_ID`. Read the request JSON and export the immutable evidence with `.venv/bin/python -m tamtam_again research-evidence RUN_ID --output data/automation/evidence/research/RUN_ID.json` (replace RUN_ID literally). Analyze only that account × market and those selected exploitable cycles. A cycle is a complete perp position excursion: flat-to-flat, or an opening excursion from the observed pre-open net position that later returns to that baseline. A reduction of inventory that predates the observed excursion is not a complete cycle. Use the cycle_kind, baseline_position, and ending_position fields; confirm that every selected cycle returns exactly to its baseline. When partial_fill_allocations lists a fill, use only its allocated_size, allocated_fee, and allocated_realized_pnl for that cycle. Never add the raw fill's full size, fee, or PnL and the allocated portion together. If one flip fill is split between adjacent cycles, verify the allocated portions are disjoint and sum to no more than the original fill. Reconcile every aggregate against the selected fills and allocations before stating totals. Use the attached fill and archived BBO/trade/L2 evidence; state missing coverage, assumptions, uncertainty, fees, latency and slippage. Do not treat correlation as causation or raw fills as independent cycles. The cycle threshold is a sample-size trigger, never proof of edge.

For follower-copy feasibility, distinguish the leader's exchange execution time from the local live `userFills` WebSocket signal receipt. Exclude messages tagged `isSnapshot=true` because they are historical snapshots, not live signals. Compare each market event's `received_at` with that signal time. A quote received after leader execution but strictly before the follower's signal may have been available to the follower; it was not available to the leader before execution. Equal-millisecond ordering is ambiguous. Never assume a follower can fill at the observed quote: model extra reaction latency, fees, slippage, and adverse selection.

Audit the `signal_event_provenance` section of the evidence. For each selected fill, confirm the signal came from the `hyperliquid-websocket-v1` `userFills` endpoint, `is_snapshot` is false, and the listed raw observation id and `raw_observations.requested_at` receipt time match `signal_received_at`. Report the snapshot-exclusion counters accurately; zero snapshot fills in the sample means none of the selected fills were snapshots, not that a snapshot was treated as live.

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

For each run, claim it with `.venv/bin/python -m tamtam_again workflow-claim RUN_ID`. Read its request and the accepted research artifact. Create the requested artifact directory and a single `paper-n1.json` in it. Initialize a local virtual paper specification and empty ledger based only on the accepted strategy_spec. The JSON must contain schema_version=1, run_id, research_run_id, mode="paper_n1", strategy_fingerprint, strategy_spec, paper_spec, virtual_ledger, live_orders_enabled=false and wallet_or_signer_configured=false. The paper_spec must contain starting_capital_usdc (a positive number), market (exact request coin), fee_assumptions (non-empty object), slippage_assumptions (non-empty object), research_run_id (exact request RE id), and revision (exact requested revision). The virtual_ledger must contain cash equal to starting_capital_usdc, positions={} and empty orders and fills arrays. Do not use a wallet, signer, live venue order API, VPS, or real order. Do not overwrite any earlier revision.

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
