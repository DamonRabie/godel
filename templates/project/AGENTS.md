# Project working conventions

- Read `brief.md`, `project.json`, and the current Godel checkpoint first.
- This is an independent ML repository. Keep implementation and dependencies here.
- Write the task solution independently. Use web research for concepts and docs;
  do not clone, copy, translate or adapt others' solution repos or notebooks.
  Standard libraries and authorized base models/data remain allowed. Cite ideas
  and disclose inherited solution reuse before building further on it.
- Put reusable data, feature, model, and evaluation logic in `src/ml_project/`.
  Introduce modules as needed; avoid a framework of empty abstractions.
- Keep `experiments/` entrypoints thin. Use this project's environment and lockfile.
- Establish a baseline and credible split before tuning. Fit preprocessing on
  training data only; do not select models using the final test set.
- Maintain `protocol.md`: validation rationale, current stage, diagnostics,
  experiment decisions and confirmation plan. Keep a shared evaluator and
  explicit feature/model configs so variants do not silently alter defaults.
- Save candidate/fold evidence and held-out predictions. Review evidence before
  further tuning; the highest development score does not prove generalization.
- Use Godel's recorded runner for scored experiments. Save numeric measurements
  to `$GODEL_RUN_DIR/metrics.json`, plus useful artifacts in that run directory.
- Record dataset/split identity, seeds, command, and relevant code/config sources.
  Do not compare runs with different evaluation definitions.
- Ask when missing information changes the objective, budget, access, or scope.
  Continue reversible work within the agreed scope without repeated permission.
- Keep a short report with measured findings, limitations, and the next step.
- Do not modify the Godel harness while solving this project unless requested.
