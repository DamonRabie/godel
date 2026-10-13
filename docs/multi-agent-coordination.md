# Bounded multi-agent coordination

Status: design candidate, disabled by default.

Godel has a useful foundation for coordinating independent work: Pi owns the
conversation loop, Python owns durable project state, runs already have parent
links, and the project has explicit run and candidate budgets. The evaluator
has not yet shown that concurrent agents improve task outcomes, so this design
does not add an always-on agent pool or treat parallel output as evidence of
quality.

## Proposed first slice

An explicit coordinator may run a small, fixed set of independent analyst
roles and then ask the parent session to synthesize their bounded reports. A
role is a task contract, not an unrestricted child agent:

- `teamId` and `taskId` identify the coordination attempt and each role.
- The parent session supplies an immutable prompt and a read-only input
  snapshot. Roles do not share a writable working tree.
- Each role has an explicit model, timeout, output-size limit and token/cost
  allowance. The coordinator rejects a plan whose sum exceeds the parent
  budget and reserves capacity for synthesis.
- A role writes a bounded report with its source references, status and
  observed limitations. It cannot approve code, publish a branch, change a
  lesson, launch a remote job or mutate project state.
- Synthesis starts only after every role reaches a terminal receipt. Missing,
  failed and contradictory reports remain visible; the coordinator never
  turns an unavailable role into a pass.

The initial useful roles for ML work are deliberately narrow: data-contract
review, validation/leakage review, experiment design, and engineering-risk
review. The parent agent decides which roles are relevant and may choose the
existing single-agent path when decomposition is not justified.

## Durable contract

Each coordination attempt should have an immutable manifest containing the
parent session, source revision, project/evaluation identity, role prompts,
model identities, budgets, input hashes and synthesis policy. Every role gets
an intent record before dispatch and a receipt after completion. A retry must
reuse the same `teamId`/`taskId` idempotency key and first reconcile an unknown
receipt. Reports link to the parent session and, when a role runs an allowed
experiment, to the existing Godel run and `parentRunId` fields.

This keeps multi-agent work inside Godel's existing evidence and recovery
model. It does not create a second history store, bypass the project lock, or
make simultaneous writes safe. Code changes, lesson activation, remote work
and adoption remain parent-session/operator actions under their existing
approval rules.

## Evaluation gate before enabling it

The evaluator should compare the current single-agent workflow with this
coordinator on fresh disposable tasks. The frozen suite must include an
independent decomposition task, a task where decomposition is harmful, a
role failure/timeout, contradictory role reports and a no-op plan. Repeat each
arm with the same model and input budget. Enable the feature only if:

1. task-level completion and artifact checks do not regress;
2. the harmful and failed-role cases preserve explicit uncertainty and do not
   claim unsupported success;
3. total model usage and elapsed time stay within the declared budget policy;
4. every report and synthesis is traceable to immutable role receipts; and
5. a holdout task confirms the result outside the development cases.

Until that gate passes, this document is a proposal for a measured candidate,
not permission to run agents concurrently or to adopt code automatically.
