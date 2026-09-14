# Agent behavior evaluations

`cases.json` is a starting rubric, not a claim that these model behaviors have
already passed. `make verify` checks software contracts without model inference.
The synthetic demo checks experiment execution, not ML agent competence.

For a real evaluation:

1. Choose concrete fixtures for development cases from your actual tasks. Keep
   separate holdout tasks the optimizer does not see. Do not feed holdout labels,
   expected answers or grading instructions to the solving agent.
2. Freeze the task fixture, evaluator, data/splits, model, harness revision,
   prompts and active-lesson snapshot. Use fresh project copies and sessions for
   baseline and candidate; keep their writable state separate.
3. Give both versions the same time/run/token budget. Token budget enforcement
   is a future capability; currently meter provider cost and stop trials manually.
4. Inspect produced artifacts and command outcomes first. Use human review for
   whether questions, decisions and scope handling were appropriate. Do not use
   the agent's own claim of success as the grader.
5. Record repeated trials, pass/fail reasons, cost, latency and interventions.
   Compare per-case regressions as well as average success. Rotate/add holdout
   tasks when repeated evaluation risks overfitting.
6. Adopt the candidate only when it improves useful outcomes without unacceptable
   regressions or cost. Keep the previous version and lesson snapshot for rollback.

Model changes, prompt changes, tool changes, lesson changes and trained-model
weight changes are different interventions. Change one at a time initially.
Save private evaluation artifacts under the ignored `artifacts/evals/` directory.

The added model-development cases target transferable failure modes: adaptive
selection, weak diagnostics, candidate-count confusion, target-encoding behavior,
split estimands, lost validation plans and changing model defaults. Instantiate
them across different domains (for example regression, forecasting and image
classification), rather than grading only the task that motivated a change.
They are behavior rubrics, not executed model evaluations. `tests/test_review.py`
executes the tool contracts separately, including a real synthetic experiment,
split mismatch/overlap, metric inconsistencies, budget accounting and context
refresh. Passing these tests does not imply passing the behavioral cases.

The ML Yearning cases additionally cover feasibility gates, sampled error
opportunities, unknown attainable performance, source/target differences,
inference objectives, label adjudication, idealized component interventions,
synthetic diversity and bounded learning curves. `tests/test_error_audit.py`
checks the helper's arithmetic, overlap handling and refusal to extrapolate
from targeted samples; model decisions still require the trials above.

Staged-search cases cover source-informed screening, budget reserves, matched
ablations, primary versus stress evaluation, batch-feature consistency, repeated
prediction denominators and appropriately narrow negative conclusions.
`tests/test_prediction_comparison.py` exercises the read-only paired CSV helper;
context tests verify that changing splits preserves dataset search exposure.
These software checks and retrospective session diagnostics do not establish
faster or better model development without controlled agent trials.
