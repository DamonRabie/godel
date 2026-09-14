# Model development protocol

Status: not established. Replace these prompts with evidence before tuning.
Keep this document short; put long tables and diagnostics in reports/.

## Current stage and next evidence

Current stage, selected baseline/run, unresolved risks, next diagnostic, and
stopping condition. Record why any previously planned stage changes.
State the leading explanation, alternative explanation, cheapest distinguishing
test and the result that would change the decision. Keep unknowns explicit.
Link the research/frontier report when present: supported ideas, rejected exact
configurations, untested alternatives and the next small batch with its reserve.

## Problem and data

Prediction unit, target/horizon, information available at prediction time,
population of interest, data provenance and hashes. Record missingness,
duplicates, group/time structure and implications for evaluation.

## Evaluation and confirmation

Metric and practical selection criterion; split rationale and saved row IDs;
fold-local learned transformations; dummy/reference and simple fitted baseline.
Separate development data from confirmation. Explain what remains untouched,
or why final generalization claims must remain provisional within this budget.
Distinguish the ranking metric from agreed feasibility constraints (units,
thresholds, measured status). Record data-source roles and which development
examples the agent has inspected. Version changes to metrics or label policies.
Name the primary prediction population and separate stress-test regimes. Justify
any combined weights/gates. Define aggregate-feature reference populations for
training, validation and final inference; retain search exposure across splits.

## Diagnostics and experiment decisions

Held-out errors/residuals, relevant slices and sample counts, potential leakage
and variance checks. Each proposed experiment: evidence, parent, change,
expected effect, rejection criterion, result and decision. Link full reports.
For an error audit, link sampled IDs, selection method, category counts and
denominators. Separate observations, suspected causes and conditional improvement
estimates. A desired score or agent judgment is not an expert reference.

## Budget and deliverable

Authorized candidates, run/runtime ceilings, capacity reserved for confirmation,
and source of authorization for changes. Final config, reproduction command,
artifact/run identity and remaining limitations.
