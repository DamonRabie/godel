# Local history and MLflow

MLflow session traces are the authoritative conversation history. SQLite retains
operational state (budgets, checkpoints, accepted lessons, execution metadata),
evidence IDs and a temporary delivery queue. It is not a second history backend.

## Start, migrate and inspect

```bash
make setup-tracking
python3 bin/godel.py tracking start
python3 bin/godel.py tracking migrate-history  # Upgrade existing histories
python3 bin/godel.py tracking status
python3 bin/godel.py tracking sync             # Retry queued ML run exports
python3 bin/godel.py tracking stop
```

Chat starts the service automatically. The UI is at http://127.0.0.1:5050.
Each project has one readable `godel / <project-name>` experiment. Use
**GenAI → Sessions** for conversations and **Model training** for ML runs in
that same experiment. Stable project IDs remain tags. `/history` returns the session
link; `/tracking` reports run and history delivery counts/errors. `make mlflow`
runs the service in the foreground. Both deployment and data stay in this repo.
Set `{"port":5051}` in `.godel/tracking.json` while stopped to change the port.
No global MLflow URI or Pi configuration is inherited.

Migration first makes private SQLite and journal backups in `.godel/backups/`,
then uploads legacy events and native Pi snapshots. Each queued payload is
read back from MLflow and hash checked before deletion. Fully verified, unchanged
journals are removed from their old active location; malformed originals remain
with warnings. Repeating migration is safe. The result is recorded in
`.godel/history-migration.json`. Backups are recovery archives, not queried stores.

## Storage and delivery

| Location | Responsibility |
| --- | --- |
| `mlflow/mlflow.db` | Authoritative trace bodies, sessions, experiment metrics/tags |
| `mlflow/artifacts/` | Local experiment artifact copies |
| `.godel/state.sqlite3` | Operational state, event IDs/hashes/ordering, evidence links, pending delivery |
| `.godel/api.sock` | Private persistent Python API bridge |
| `projects/<name>/.godel/sessions/` | Rebuildable native Pi resume cache |
| `projects/<name>/.godel/runs/` | Original execution output, snapshots and artifacts |

All are ignored by Git. No new `.godel/history/*.jsonl` files are written.
The bridge acknowledges a durable queue write without waiting for MLflow and
exports asynchronously. Deterministic trace/span IDs make retries idempotent;
queued bodies are removed only after exact read-back verification. The worker
retries failures with backoff up to 30 seconds. Pending events are readable by
the agent. A 32 MiB in-memory cache accelerates repeated retrieval.

Each input starts a trace; completed model/tool events become spans; `agent_end`
closes its root. Session activity and native snapshots also have traces grouped
by the same Pi session ID. Reported token usage remains in `godel.usage` and the
original event; it is not fed into MLflow's incremental counters. This preserves
the retry behavior established with the original tracking implementation.
Interrupted requests can remain
IN_PROGRESS when no closing event was recorded; this does not imply a live process.

The pinned Pi runtime needs native JSONL files for branching, compaction and resume. Exact
snapshots are persisted in MLflow at turn/lifecycle boundaries. Chat restores
missing cache files; it never overwrites existing ones. A hard crash before a
snapshot may leave newer state only in the cache; migration snapshots it again.
Events before Pi's first assistant response are independently preserved as spans.

Back up the entire workspace with processes stopped, including ignored state,
MLflow data, Pi credentials/cache and original artifacts. Git is not a backup.
Do not delete the MLflow DB while retaining its local ID mappings. Migration
preserves checkpoints, accepted lessons and execution rules unchanged.

## Agent retrieval and evidence

```bash
python3 bin/godel.py history example --query baseline --limit 10
python3 bin/godel.py history example --type decision
python3 bin/godel.py history example --session <session-id> --after 42
python3 bin/godel.py evidence example <run-or-event-or-lesson-id>
```

`godel_history` provides project/session/type/text filters and sequence cursors.
MLflow narrows traces with a safe ASCII text fragment; Python applies exact
substring matching to decoded events (including Unicode and punctuation).
`godel_history_event` reads full large payloads in bounded chunks.
`godel_evidence` follows direct links between events, runs, lessons and checkpoints.
History is retrieved deliberately, not loaded wholesale into model context.
When MLflow cannot be reached, retrieval reports unavailable, never a misleading
empty history. Execution and context/lesson selection still work locally.

`godel_decision` records a summary, rationale and optional `evidenceRefs` such as
`[{"type":"run","id":"<run-id>"}]`. Checkpoints and lesson proposals accept
the same references. They must identify an existing current-project run/event.
A decision returns an event ID usable by a lesson. Context events identify the
lessons selected on that turn. Decisions do not certify results or accept lessons.

## Experiment metadata and curves

`godel_run` accepts optional scalar `parameters`, for example
`{"seed":17,"learning_rate":0.01,"model":"linear"}`. These become MLflow parameters
alongside the declared dataset, split, primary metric and direction. Existing
`metrics.json` remains the contract for scored results.

For step/epoch curves, write an optional `metric-history.json` in `GODEL_RUN_DIR`:

```json
[
  {"step": 1, "metrics": {"train_loss": 0.8, "validation_loss": 0.9}},
  {"step": 2, "metrics": {"train_loss": 0.5, "validation_loss": 0.7}}
]
```

Points need unique metric/step pairs, nonnegative integer steps and finite values.
Names may contain letters, numbers, underscores, spaces, dots, slashes and hyphens,
with no `..`. The file is capped at 4 MiB, 10,000 points and 32 metrics per point.
Curves are exported after completion; they are not live streaming telemetry.
Invalid curve data produces tracking warnings and remains an artifact; it does
not change primary-metric validity. Unsupported primary metric names remain
recorded but cannot be plotted in MLflow. Use different curve names from final
summary metrics when they have different meanings.
When names coincide, the final summary is logged one step after the last curve
point so MLflow's latest-value table shows the scored result.

Each Godel project maps to one MLflow experiment with its name and goal displayed
and its stable project ID in tags. Runs carry stable Godel run/session/parent/tool-call IDs, hypothesis,
model identity and separate process, measurement and evidence-review tags.
A failed process stays `FAILED`, cancellation/timeout is `KILLED`, and process
success is `FINISHED` even if its measurements are missing or invalid. Godel's
comparison rules remain authoritative; MLflow sorting alone is not model selection.
Conversation sessions and training runs share the same experiment ID. Sessions
can contain many turns; a training run links to the session and tool call that
launched it. Creating another session does not create another experiment.

The single exporter recovers a lost run-create reply by searching the stable
Godel run tag. Repeated exports reuse the remote ID and exact metric timestamps
and steps. A newer local revision remains pending if an older export finishes.
It does not rerun experiments after crashes: a SIGKILL can leave a run `running`
until an operator checks its original process and artifacts.

## Verification

`make verify` covers model-free SQLite persistence, imports, evidence traversal,
queue behavior and the pinned Pi adapter. `make verify-tracking` additionally
starts a temporary real local MLflow server, tests lost-response recovery,
failed-run status, metric-history replay, artifact checksums, trace replay, full
payload retrieval, session grouping, native cache restoration and bridge latency.
It requires `make setup-tracking` and permission to bind a localhost port.
Neither check establishes live model-provider capability or better ML decisions.

The shared-project layout has real-server regression coverage for:

- Chat-first and training-first creation, multiple sessions and multiple runs.
- Eight concurrent first registrations sharing one experiment.
- Lost experiment-create replies and recovery of a missing local mapping.
- Name collisions, wrong-project mappings and archived destinations failing closed.
- Continued sessions and queued inputs across a tracking-service restart.
- Exact user-input retrieval and separation between projects sharing a session ID.
- Existing metric/artifact replay and failed-run status checks.

Playwright verification also checks the same experiment ID in Sessions and Model
training, with user requests visible and both training attempts listed. Tests
use temporary workspaces; they do not populate the working project's history.

This layout change does not repair the separate capture/recovery limitations:
native-only messages are not reconciled into searchable events, snapshots can
lag the native transcript, and lifecycle traces can appear as empty chat turns.
Passing layout tests is not proof of complete capture under every Pi failure.
