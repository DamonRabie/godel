# Compare saved predictions before more fitting

For hard-label classification, run the read-only stdlib helper on an incumbent
and candidate's saved held-out CSVs:

```bash
python3 "$GODEL_HOME/agent/skills/ml-diagnostics/scripts/compare_predictions.py" \
  reference.csv candidate.csv --id-column row_id
```

Required columns default to `row_id,target,prediction`; override their names with
`--id-column`, `--target-column`, `--prediction-column`. Use identical string
label encodings. Include `repeat`, `fold`, and `regime` when applicable: the helper
aligns on ID plus these dimensions, rejects duplicate/missing keys or conflicting
targets, and recomputes correctness instead of trusting a saved `correct` column.
IDs must identify the observation, not an entity with multiple different targets.
Both files must have matching dimensions. Limits: 16 MiB/100,000 rows per file,
32 regimes and 100 repeats per regime. Redirect stdout to a new report artifact
if useful; input files are never changed.

It reports corrections, regressions, changed predictions and unique observations
per regime and repeat, plus file hashes. Repeated predictions are not independent
examples. The same row may improve in one repeat and regress in another; those
unique-row counts can overlap. Accuracy is pooled by prediction occasion within
each regime, not an unweighted mean of fold scores. Different regimes are never
silently combined. No significance, causal attribution or promotion is inferred.

Before interpreting, use `godel_review` and inspect split/source artifacts to
establish that these really are out-of-fold predictions with matching fitted
partitions. Matching CSV keys cannot prove that. For regression, ranking,
probability calibration or weighted metrics, use the task's evaluator instead;
do not convert their errors into this helper's classification counts.

Use the comparison to choose a small number of motivated slice investigations
or an ablation. Save detailed row evidence in the project report, with both
unique-row and prediction-occasion denominators. Explain modest gains in absolute
points and corrected/regressed decisions; do not infer a remaining-performance
ceiling from their size.
