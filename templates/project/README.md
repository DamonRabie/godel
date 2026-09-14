# __PROJECT_NAME__

An independent Python ML project managed by Godel. Start with `brief.md` and
`project.json`. This repository owns its code, tests, dependencies, and reports.

Use `src/ml_project/` for reusable Python modules, `experiments/` for thin
executable entrypoints, and `tests/` for meaningful correctness checks.
Keep notebooks exploratory; move reusable transformations and model code into
the package. Put local data in `data/`, generated outputs in `artifacts/`, and
human-readable findings in `reports/`.

Create a separate environment here with `uv sync`; declare only needed
dependencies in `pyproject.toml` and commit the resulting `uv.lock`.
Run `uv run python -m unittest discover -s tests` for stdlib tests, or choose
a project test framework when useful. Experiment entrypoints should use
`uv run python experiments/<script>.py` so they use this project's environment.

Godel saves logs, source snapshots, metrics, and session history in `.godel/`.
An experiment writes its numeric measurements to `$GODEL_RUN_DIR/metrics.json`.
Commit project code and conclusions; keep data, credentials, and generated runs
out of Git. No remote or initial commit is created automatically.
