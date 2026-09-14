---
name: ml-reproducibility
description: Structure reusable ML experiment code and verify a selected model or deliverable can be reproduced, especially when variants change shared features, defaults or dependencies.
---

# Preserve the identity of the selected model

Keep reusable data, features, models and evaluation logic in the project's
`src/ml_project/`. Use one shared evaluator and explicit per-run feature/model
configuration, with thin entrypoints in `experiments/`. Add modules when needed;
avoid empty framework abstractions. Notebooks may explain exploration but must
not be the only way to reproduce the selected result.

Experiments must not silently change shared defaults used by an earlier model.
Record resolved configuration, data/split identity, seeds, interpreter,
dependencies and relevant imported source files with each run. Godel snapshots
only listed sources: include imported modules and config/lockfiles. Preserve
the selected snapshot even when current code evolves.
Export actual resolved estimator/transform parameters (including nested models),
not only hand-written candidate descriptions. Before attributing an ablation,
compare those configurations: a changed default can invalidate the explanation
even when the candidate score is correctly measured.

Before replacing a deliverable, review the chosen run and its selection evidence.
Write a stable final training/prediction command pinned to the selected config.
Fit final preprocessing/model on the permitted training data after selection;
do not silently retune thresholds, features or parameters on confirmation data.

Keep label corrections, evaluation-contract changes, synthetic data and oracle
component outputs separately versioned and identified. Diagnostic use of trusted
answers must not leak into deployable features or the selected artifact. Verify
agreed feasibility constraints on the same candidate/config before recommending
it; missing evidence remains unknown, regardless of its primary metric rank.

Verify current commands reproduce the selected predictions or explain measured
numeric tolerance/stochastic variation. If expensive retraining is outside the
remaining budget, retain the verified run artifact and report that limitation
instead of claiming current-source reproduction. Verify artifact/run identity,
schema, IDs/order, expected coverage and task-appropriate prediction semantics.
Output format alone does not establish that the correct model produced it.

Tests should protect consequential semantics: split membership, fold-local
transformations, unseen/missing inputs, prediction coverage and metric
recomputation. Choose checks appropriate to the task rather than asserting only
shapes or mirroring implementation details.

Report development score, confirmation evidence or its absence, total search
exposure, uncertainty, diagnostic findings, cost, reproduction command and
remaining limitations separately. Mark a chosen deliverable as provisional when
the evidence warrants it. An external submission or deployment still needs
authorization for that action.

Checkpoint decisions and unresolved work. Propose reusable lessons with evidence
and applicability; one dataset does not establish a universal ML rule. Preserve
original history, runs and rejected configurations for future analysis.
