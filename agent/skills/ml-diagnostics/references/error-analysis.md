# Turn inspected errors into evidence

Use this when prioritizing error categories or investigating labels. Produce a
small project-owned audit, not a transcript full of examples or an unverified
narrative. The sample size should resolve a decision within the budget; there is
no mandatory quota of 100 examples.

1. Identify the frozen run, evaluator, data subset, prediction artifact and error
   definition. Obtain held-out predictions; do not substitute training predictions.
2. Select errors reproducibly, recording stable IDs, seed, population counts and
   selection method. Uniform sampling supports prevalence estimates; selecting
   dramatic examples or only a specific slice does not. Keep targeted and uniform
   inspections distinguishable. Repeated OOF predictions are not independent rows.
3. For each inspected row, retain its ID, observed outcome, categories and a short
   evidence reference. Multiple categories may overlap; retain uncertain or
   unclassified cases in the denominator. Separate an observable feature (missing
   sensor value) from a hypothesized cause (imputation caused this prediction).
4. Record category counts, denominators and uncertainty. Compare plausible impact,
   fixability, regression risk and implementation/compute cost. Do not pick an
   intervention solely because its examples are easy to describe.

For ordinary unweighted classification error, if a representative share `q` of
errors belongs to a category and overall error is `e`, then `100 * e * q` is an
estimated percentage-point opportunity **assuming all those errors are fixed and
no new errors are introduced**. It is not a predicted gain. With exhaustive
categories it is a conditional ceiling; with a sample it has sampling and
annotation uncertainty. Overlapping category opportunities cannot be added.
For weighted loss, regression, F1, ranking or other non-additive metrics, use
actual held-out contributions or a justified counterfactual metric recomputation;
do not reuse that classification formula blindly.

## Deterministic summary helper

Save an audit such as `reports/error-audit.json` in the project. Format:

```json
{
  "schemaVersion": 1,
  "runId": "the-reviewed-run",
  "population": {"examples": 2000, "errors": 100},
  "sampling": "uniform_errors",
  "records": [
    {"id": "row-17", "categories": ["missing-sensor"], "evidence": "OOF artifact row 17; sensor field absent"},
    {"id": "row-81", "categories": [], "evidence": "OOF artifact row 81; cause remains unknown"}
  ]
}
```

Run `python3 "$GODEL_HOME/agent/skills/ml-diagnostics/scripts/summarize_errors.py"
reports/error-audit.json` from the project. Choose `all_errors` only for an
exhaustive audit, `uniform_errors` for a uniformly sampled set of errors, or
`purposive_errors` for targeted inspection. The helper validates counts and IDs,
handles category overlap, and withholds population headroom for targeted samples.
It does not inspect raw data, verify sampling, certify categories or choose the
next experiment. Predictions and audit records remain the source of evidence.

## Label integrity and judging limits

Mark disputed labels as suspected, with supporting evidence and potential impact.
Agent confidence, plausible explanations and model disagreement are not ground
truth. Seek an authoritative source or user/domain adjudication when needed;
never silently replace labels with predictions or edit an official benchmark.

Where relabeling is appropriate and authorized, preserve originals and correction
provenance. Audit some apparently correct predictions as well as failures to avoid
cherry-picking label changes that favor the current model. Use a consistent policy
across evaluation subsets through the authorized data owner; this does not permit
the solving agent to inspect held-out final-test labels. Revised evaluation and
baseline comparison must use the corrected dataset identity.

Adaptation source: *Machine Learning Yearning*, chapters 14–19, 26, 33–35.
[Original book](https://home-wordpress.deeplearning.ai/wp-content/uploads/2022/03/andrew-ng-machine-learning-yearning.pdf).
