Experiment scripts call the reusable package and write metrics as JSON to
`Path(os.environ["GODEL_RUN_DIR"]) / "metrics.json"`.

Supply a request to `godel_run` with a hypothesis, argv command, timeoutSeconds,
and relevant source paths. `uv run python experiments/baseline.py` is a typical
command after creating this project's environment. `sources` should include
the entrypoint, imported project modules, configuration, and lockfile when available.
