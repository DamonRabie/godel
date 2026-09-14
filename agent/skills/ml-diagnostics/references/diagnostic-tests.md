# Choose a test that separates explanations

Read only the section needed for the current failure. Missing measurements stay
unknown; these are practical hypotheses, not a formal bias/variance decomposition.

## Fit, generalization and population mismatch

Record comparable errors for the frozen model: fitted training data, optional
held-out source-distribution data, and target-distribution development data. Note
sample sizes, metric, inference mode and population. Training augmentation,
dropout, weighting, different class mixtures or target-encoding representations
can make raw gaps misleading. Recompute comparable scores before diagnosing.

| Observation, after comparability checks | Useful next diagnostic/action |
| --- | --- |
| Training performance falls short of an evidenced attainable reference | Check optimization, features and label/input limitations; try a small capacity or regularization change |
| Training is good but held-out data from the same source are worse | Examine variance, leakage and duplicates; test regularization or additional representative data |
| Held-out source performance is good but target-development performance is worse | Investigate population, label-policy and difficulty differences before enlarging the model |
| Several gaps are material | Diagnose the consequential gap first; do not force one exclusive explanation |

A desired score is not an achievable reference. Human/expert performance is
useful only when measured on comparable inputs and labels; it is not a known
Bayes error floor. Godel's own answers, confidence or provider claims are not a
human benchmark. If the reference is unavailable, say so and use controlled
experiments rather than inventing an irreducible-error estimate. Inspect training
errors when fit is the concern; keep those diagnostics distinct from held-out work.

For a data-volume decision, use a few representative training sizes with a fixed
development evaluator and recorded sampling. Distinguish sample-size curves
from loss versus training-step curves. Count all diagnostic fits and their cost;
repeat only if noise obscures the decision. Preserve time/group boundaries and
fit transforms anew per subset. Do not extrapolate a guaranteed score or assume
monotonic empirical curves. Diagnose optimization/label changes before concluding
that more data cannot help. A smaller model may be valuable for iteration cost,
even when it does not maximize the current score.

## Scoring objective versus inference/search

Applicable when the system scores candidate outputs and approximately searches
for a maximizer/minimizer (decoding, retrieval/reranking or planning). This is not
a generic test that every classifier must run.

For an error with a demonstrably better feasible output, evaluate both outputs
using the **exact deployed scoring rule**, normalization, constraints and metric
direction. If the better output receives a strictly better internal score but
was not found, search missed a known better candidate. If the score prefers the
bad output, improving search alone need not fix the objective mismatch. Ties may
implicate tie-breaking or insufficient discrimination. The score ordering on one
pair neither proves global optimality nor excludes simultaneous problems.

Record example IDs and score comparisons across a bounded sample, then prioritize
the implicated mechanism. Do not compare differently normalized scores or an
infeasible reference, and do not use final-test answers as search candidates.

## Component interventions and lost information

For a multi-stage system, save intermediate outputs for a few development errors.
Replace one component's output with a trusted reference and rerun the downstream
portion with other settings fixed. Measure the final objective, not only a local
component metric. Such oracle substitutions are diagnostics only: isolate them
from trained features and deployable outputs, and label results accordingly.

A useful gain shows potential under that intervention, not a guaranteed fix or
unique culprit. Interactions, ordering and changed downstream distributions can
alter attribution; compare joint interventions only when that uncertainty matters.
If strong components still compose poorly, inspect interfaces for missing
prediction-time information and compare against a reference with the same inputs.
Do not blame a downstream component for information removed upstream.

Adaptation source: *Machine Learning Yearning*, chapters 20–35, 40–46, 53–57.
[Original book](https://home-wordpress.deeplearning.ai/wp-content/uploads/2022/03/andrew-ng-machine-learning-yearning.pdf).
