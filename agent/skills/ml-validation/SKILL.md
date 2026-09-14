---
name: ml-validation
description: Design or audit ML evaluation before a baseline, when data or splits change, or when repeated tuning weakens a generalization claim. Covers prediction-time information, dependent observations, leakage and independent confirmation.
---

# Design a credible evaluation

Read the brief, project evaluation, protocol and prior search exposure. Establish
the prediction unit, target/horizon, information available at prediction time,
population of interest, metric and practically useful improvement. For tasks
without labels, define an appropriate independent evaluator and reference method.
Clarify only unknowns that materially change the design.

Separate the primary ranking metric from agreed feasibility constraints. When
metrics conflict, data sources differ, or evaluation needs revision, read
[metric and data contracts](references/metric-and-data-contract.md). Record
unmeasured constraints as unknown; the highest numeric score is not necessarily
the best feasible candidate. Keep a competition's official metric authoritative.

Inspect real data provenance/hashes, schema, label distribution, missingness,
duplicates, group/time dependence and plausible train-to-use differences.
Distinguish predicting new entities from new observations of known entities.
Group overlap is a diagnostic, not automatically leakage. Select temporal,
grouped, stratified or other partitions for the actual prediction population;
use sensitivity checks when a single design leaves important uncertainty.
For group aggregates, batch-dependent features or multiple evaluation regimes,
read [batch and regime validation](references/batch-and-regime-validation.md).
Keep primary evaluation separate from stress tests unless combination is justified.

Keep learned preprocessing, feature selection, resampling, calibration,
threshold selection and early stopping inside the appropriate training/inner
partitions. Audit future and post-outcome information. When labels generate
features, read [target-encoding checks](references/target-encoding.md).

Record actual row assignments, data identity and seeds, not only a split name.
Test partition disjointness, applicable time/group constraints, and preprocessing
isolation. Include a cheap reference/dummy and a simple fitted baseline on the
same partitions. Smoke-test the evaluator and exact primary metric key; a tiny
first recorded baseline may itself be the smoke.

Separate development selection from confirmation in `protocol.md`. Repeated
search on one CV design makes it development evidence. Repeated CV probes
sensitivity, but does not independently confirm a model selected using it.
A new split of previously examined data does not erase adaptive reuse.

For final generalization claims, freeze the choice before a previously untouched
holdout, or evaluate the selection procedure with appropriate nested validation.
Avoid blindly sacrificing scarce labels: justify the design and cost, or label
the result provisional if confirmation is infeasible within the agreed budget.
Fold SD is descriptive; overlapping CV training sets rule out naive independent
fold significance calculations.

Leave a concise protocol: prediction assumptions, data identity, split rationale
and artifact, reference baseline, practical criterion, development/confirmation
boundary, unresolved risks and next evidence needed. Keep current stage and risks
near the top. Explain any revision to a previously promised validation stage.

For Godel's artifact schema, read the relevant sections of
[the evidence contract](../../../docs/model-development.md).
Background: [scikit-learn validation design](https://scikit-learn.org/stable/modules/cross_validation.html)
and [nested selection](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).
