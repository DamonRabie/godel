---
name: ml-experiment-design
description: Research relevant methods, plan informative ML comparisons or staged model searches, allocate candidate and compute budgets, and decide what results justify next.
---

# Spend experiments to answer questions

Read `protocol.md`, current candidate exposure and recent hypotheses/results.
If the baseline or validation design is missing, use `ml-validation` first.
For a familiar task, plateau or new budget, read
[research and staged screening](references/research-and-screening.md). Use local
error evidence or relevant prior work to justify a comparison; use
`ml-diagnostics` when the proposed search has neither. Load only what is needed.

Start a new task with the smallest credible executable baseline quickly. Do not
turn protocol writing into an extended planning phase. After that first result,
prefer the cheapest test that can distinguish the leading explanations; spend
model runs when they answer a question or offer justified practical improvement.

Specify the parent/reference run, observed problem, one coherent change,
expected effect, practical selection criterion and rejection/stopping condition.
Model-family screening can be useful; describe it as screening. Simultaneous
feature/model changes cannot establish which component helped; plan an ablation
if that attribution matters. Do not spend the entire budget on arbitrary variants.

Compare rough opportunity, confidence, fixability and total cost before choosing.
Keep an estimated ceiling distinct from a predicted gain and a measured result.
Include implementation, diagnostic fits, inference and user attention in the
cost assessment. Stop or change direction when the expected useful information
is exhausted; do not keep a weak branch alive merely because budget remains.
For source mixing, augmentation or architecture changes, read
[data and architecture decisions](references/data-and-architecture.md).

Treat candidate allowances as ceilings, not a requirement to fill one batch.
Reserve capacity for feedback-driven follow-ups, confirmation and reproduction. Honor the protocol's next
validation stage, or explain a reason to revise it before substituting a search.
Do not retrospectively treat a selected development result as untouched evidence.

Use `godel_run` with hypothesis, explicit argv, relevant imported source/config/
lockfiles, timeout and `parentRunId` when applicable. Declare `candidateCount`
for every evaluated configuration, including a re-evaluated reference. Folds
are fits, not new candidates; record repeats/seeds and total compute separately.
`maxRunsPerSession` and optional `maxCandidatesPerSession` are different ceilings.
An extension adds to previously used capacity; ten models does not authorize ten
arbitrary sweeps. Failed attempts consume declared allocations. Never evade a
ceiling using shell training, new sessions or unapproved configuration edits.

When implementing an evaluator or batch, read
[the evidence contract](../../../docs/model-development.md) and use the existing
[synthetic example](../../../examples/tiny_regression.py) as an artifact-format
reference, not a task-specific modeling recipe. Record all candidates and their
fold scores, held-out predictions, resolved parameters and split membership.
Check a batch's planned count against `GODEL_CANDIDATE_COUNT` when available.

After execution, inspect status, metrics and review findings. Diagnose failed
runs before retrying; retain failed/rejected attempts and their evidence. Decide
whether to continue, revise or stop using the predeclared question, uncertainty,
cost and remaining budget. Record the decision and next evidence needed in the
protocol and checkpoint. A larger metric does not automatically authorize
promotion, more compute or an external action.
