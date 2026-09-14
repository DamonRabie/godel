# Define what a better result means

Use this reference when objectives compete, evaluation data differ from training,
or the current score rewards behavior the user does not want.

## Selection rule

Record one primary ranking metric and direction, plus any agreed acceptance
constraints (for example latency, memory, recall on a critical slice). Record
units, thresholds, measurement conditions and missing measurements explicitly.
Do not silently invent a weighted utility function or convert a constraint into
a weak preference. Rank feasible candidates; if a constraint is unmeasured,
mark feasibility unknown. A high primary score does not override a failed gate.
Godel's highest-score context is only a numeric ranking: the agent must check
these project-specific gates before recommending a deliverable.

For a competition, retain the official scoring rule. Useful local diagnostics
do not replace it. If a business task has unresolved tradeoffs, ask a focused
question with the measured consequence; otherwise use the confirmed brief.

Choose validation size for the decisions being made, available independent
entities, class/event counts and uncertainty. No fixed percentage or example
count guarantees detecting a small gain. Avoid ranking tiny differences beyond
the evaluator's resolution, and avoid demanding a full significance study for
every reversible screening experiment.

## Data roles and exposure

Describe each subset's source/population, available labels, intended use and
whether the agent has inspected individual examples or only aggregate scores.
Prefer development and final evaluation representative of the intended use;
do not shuffle away a required temporal/group boundary to force matching data.
Official benchmark splits may be immutable or mismatched; record that limit.

When training sources differ from the target population and the distinction
would change the next action, consider a held-out source-distribution diagnostic
set in addition to target-distribution development data. Call it `source_dev`
or clearly define `train_dev`: it must not be fitted on. Use the same frozen
model and comparable metric to separate within-source generalization from
source-to-target performance differences. This is optional, not four mandatory
partitions for every small dataset; retain ordinary CV when justified.

If enough development data exist, reserve an inspection subset and keep the
remaining development examples out of conversational inspection. Log sampled
IDs and which portion was examined. Aggregate-only development scores are still
selection feedback, so that subset is not an untouched final test. On small
data, reuse may be necessary: record exposure and keep claims provisional rather
than fragmenting the dataset into unusable pieces.

## Evaluation changes

If the metric disagrees with the agreed objective, distinguish a faulty evaluator,
a nonrepresentative population and an actual objective change. Document the
evidence and resolve material user tradeoffs before changing the objective.
Version dataset, label policy, metric, weights/thresholds and split artifacts.
Re-evaluate relevant baselines under the new contract within budget; old and new
scores are not a continuous improvement series. Previously inspected data stay
exposed. A new session or renamed split cannot make them untouched again.

For label corrections, use the audit procedure in
[error analysis](../../ml-diagnostics/references/error-analysis.md).

Adaptation source: Andrew Ng, *Machine Learning Yearning*, chapters 5–12, 17–18,
36–41. [Original book](https://home-wordpress.deeplearning.ai/wp-content/uploads/2022/03/andrew-ng-machine-learning-yearning.pdf).
