# Continuous descriptive subscription allowance

`config/continuous-research-policy.json` supplies a separate immutable policy for
continuous descriptive research. It does not modify historical pilot allowances,
shared historical attempt counters, economic validation, paper eligibility, or
real-order permissions.

The conservative default UTC daily envelope permits at most three tasks, six
model calls, 480,000 reserved input tokens, 30,000 reserved output tokens and
720,000 ms of reserved model time. These are ceilings, not a target cadence.
Each task retains the existing two-call, 80,000 input tokens / 5,000 output tokens
/ 120-second per-call runtime. Subscription accounting records usage even when
provider cost is included rather than billed per token.

The policy id is permanently bound to the canonical policy fingerprint in
`continuous_research_allowances`. Changing a ceiling requires a new explicit
policy id; mutating an existing policy is refused. UTC period boundaries renew
the available envelope without deleting any previous task or call. Tasks sealed
in an earlier daily period cannot dispatch calls in a later period.

`continuous_research_tasks` records every admitted task. Permanent semantic
evidence identity is scoped by network, address and market, independent of day
and policy id. The orchestration layer computes that identity from actual
observations and the descriptive question: a new receipt timestamp, packet
serialization, schema version or policy id is not new evidence. Historical
pilot evidence must also be compared before admission.

`continuous_research_calls` consumes worst-case call/token/time reservations in
one immediate SQLite transaction before provider entry. Failed, interrupted,
unknown-usage and rejected attempts remain consumed. Actual usage is retained
for audit; it never refunds the reservation. A critique requires the preceding
proposal call to have passed result validation.

Admission uses every qualified row from `descriptive_admission` rather than its
short display queue. A single-market account requires the existing descriptive
10-fill / 2-active-day minimum. Each market of a multi-market account requires
its own observed counts, UTC active days, exact source window, coverage metadata
and evidence reference. Account PnL and aggregate account activity never qualify
an individual market. Prefixes such as `xyz:` remain part of instrument identity.
The orchestration layer must verify protected accounts and reserved periods
before reading evidence or preparing packets; this allowance grants no access
to protected evidence and does not release reservations.

The same `population_runtime` executes historical pilot and continuous tasks,
selecting the persisted allowance backend by task membership. Tool isolation,
response validation and bounded provider execution stay shared. No live model
call or production database mutation is required to validate this integration;
the tests use temporary databases and a mocked provider.
