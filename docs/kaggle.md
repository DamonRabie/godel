# Kaggle access

## Agent-owned remote experiment tracking

Kaggle compute does not replace MLflow tracking. You (the project agent) must
record each authorized training job with `godel_remote_run`:

1. Freeze the actual dataset/split/metric contract in `project.json`. Prepare the
   remote script to save `metrics.json`, `metric-history.json`, `evaluation.json`
   (contracts in `docs/tracking.md`), logs, configuration and predictions. Keep
   validation, calibrated validation and leaderboard scores distinctly named.
2. Immediately after launch returns its job ID and immutable version, call
   `action: "register"`, `remote: {platform: "kaggle", jobId: "owner/slug",
   version: "<returned version>"}`, `hypothesis`, `sources`, `candidateCount`, and
   optional `parameters`/`parentRunId`. Snapshot the exact submitted code/config.
   This saves a RUNNING record, linked to this session, in the project's experiment.
   Save the returned Godel run ID and next monitoring step in a checkpoint.
3. Monitor and download that exact version yourself using the configured wrapper.
   A successful push is NOT a successful training run. Never assume a slug's latest
   output belongs to your version: verify version evidence before importing. If
   identity cannot be established, checkpoint the blocker; do not guess or relaunch.
4. Call `action: "finish"` with `runId`, the same `remote` identity, observed
   terminal `status` (`succeeded`, `failed`, `cancelled`, `timed_out`), `provenance`
   explaining the version/status evidence, and `files` mapping artifact basenames
   to downloaded project-relative paths, for example:
   `{"output.log":"results/v11/output.log","metrics.json":"results/v11/metrics.json",
   "submission.csv":"results/v11/submission.csv"}`. Include raw status/version
   evidence as an additional artifact. `output.log` is mandatory, even on failure.
   Legacy text-only output may be parsed into metrics only from observed values;
   include the raw log and parser source, never invent missing metrics.
5. Inspect measurement validity and `godel_review`. Check tracking status and actual
   MLflow metrics/artifacts before claiming delivery. Local recording works during
   an MLflow outage; the existing exporter retries without rerunning the remote job.

Registration retries return the same record for the same project/job/version and
metadata, including across sessions. Finishing retries accept the identical bundle;
conflicting terminal results are rejected. No automatic polling or GPU work is
performed by this tool. The agent owns resuming unfinished collection. Dates in the
record are registration/collection times, not inferred remote execution durations.
Import accepts up to 100 explicit files totaling 64 MiB, no symlinks or private
state paths. Review files for secrets before importing; use checksummed durable
references for larger model files. A matching identity is agent-attested provenance,
not independent verification by Godel. Save remote timestamps in the evidence.

The adapter registers this tool, but the current launcher's explicit tool list
does not activate it. Use the same API through the shell in new or existing sessions:
`python3 "$GODEL_HOME/bin/godel.py" api remote_run --project "$PWD"`, with JSON on
stdin: `{"sessionId":"<actual current session ID>","request":{...tool arguments...}}`.
Do not substitute a new session ID or manually backfill another session's results.

Use Godel's wrapper from any project, including an already-open Pi session:

Godel refreshes integration instructions in the project context before every
agent turn, including open sessions. Use the provided wrapper command. Direct
`kagglehub` calls or a bare `kaggle` command do not load Godel's private settings.
A generic HTTP 403 is not sufficient evidence that competition rules need to be
accepted; first reproduce it using the configured wrapper.

```bash
python3 "$GODEL_HOME/bin/kaggle.py" competitions files -c titanic
python3 "$GODEL_HOME/bin/kaggle.py" competitions download -c titanic -p data/
```

The second command downloads an archive; inspect and extract it into the project's
data directory. Keep raw data out of Git and record its source and hashes.
If Kaggle requires competition rules acceptance, ask the user to accept on Kaggle
and retry. Do not treat an authentication or rules error as permission to substitute
unofficial data.

The wrapper uses `.godel/tools/kaggle/` and a private `.godel/kaggle/access_token`
copied from the user-specified file during setup. It supplies the token only to
the Kaggle child process, with workspace-local configuration. No session restart
is needed, and global credential changes are not automatically imported.
Never read, print, or copy the token into prompts, project code, or history.

Reading competition information and downloading task data are within the current
task. Submitting predictions, publishing notebooks, and starting remote jobs need
authorization for those actions. The wrapper is a credential-loading convenience,
not an enforcement boundary for the CLI's capabilities.

To reinstall the CLI, create its local virtual environment with
`uv venv .godel/tools/kaggle --python python3`, then install the version recorded
in `requirements-kaggle.txt` using
`uv pip install --python .godel/tools/kaggle/bin/python -r requirements-kaggle.txt`.
Credential import/rotation is an explicit user-requested operation; use private
file permissions and never put token values in shell arguments.
