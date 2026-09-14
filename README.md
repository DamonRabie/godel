# Godel

A self-contained, teachable ML engineering workspace. **Python owns the harness;
Pi provides the agent loop and terminal interface.** Each ML problem gets an
independent Python project repository.

Godel is a small working foundation: durable project context, bounded local
experiments, evidence-backed lessons, and a clean place to improve the agent.

**Status: experimental / work in progress.** Interfaces and storage may evolve.
The supported installation is a complete source checkout, not a standalone PyPI
or npm package. Back up private workspace state before upgrading.

The agent is defined in [agent/system.md](agent/system.md), with its general
[ML foundation](agent/model-development.md) refreshed each turn. Detailed
workflows are packaged as [Godel-owned Pi skills](docs/model-development.md#skills),
loaded on demand from this repository.
Its [evidence-review tool and artifact contract](docs/model-development.md)
help it diagnose results, retain validation decisions and distinguish a high
development score from confirmed generalization.

## Start

Requires macOS or Linux, Python 3.11+, Node.js 22.19.0+, npm, Git, Make, and
[uv](https://docs.astral.sh/uv/getting-started/installation/).
Clone or download this repository, then run these commands from its root:

```bash
make setup
python3 bin/godel.py doctor
python3 bin/godel.py init churn --goal "Build and evaluate a customer churn model"
python3 bin/godel.py chat churn
```

Inside Pi, run `/login` and `/model` to configure a provider **for this workspace**.
Pi is pinned to `@earendil-works/pi-coding-agent` 0.85.1. Godel deliberately starts
with its own configuration; an existing global Pi login is not automatically reused.
Custom endpoints belong in `.godel/pi/models.json`; follow
[Pi's model configuration documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md).
Do not put credentials in source files or command arguments.

Talk naturally:

> Inspect the data I describe, ask what you need to clarify, establish a credible
> validation split and baseline, then work toward the best solution within our budget.

Resume with `python3 bin/godel.py chat churn --continue`. Pi also provides `/tree`
and `/fork` for conversation branches. Branching a conversation does not rewind
project files, experiment records, or accepted lessons.
The full current session ID appears above the chat input and matches the ID in
MLflow's conversation sessions.

## Work with the agent

For Kaggle competitions, use the [Kaggle access guide](docs/kaggle.md).
The workspace wrapper also works from already-open Godel sessions.

| Command | Purpose |
| --- | --- |
| `/plan` | Clarify the objective, evaluation, budget, and next useful step |
| `/project` | Inspect the brief, checkpoint, budget, and best comparable result |
| `/runs` | See experiment status and measurements |
| `/teach <correction>` | Save your explicit correction as an active project lesson |
| `/reflect` | Ask the agent to propose evidence-backed lessons |
| `/lessons` | Inspect lesson text, evidence, scope, and status |
| `/accept <id>` | Activate a reviewed proposal |
| `/retire <id>` | Stop loading a stale lesson; retain its review history |
| `/report` | Produce a report from the project's evidence |
| `/history <text>` | Search MLflow history; omit text for session IDs and UI link |
| `/tracking` | Inspect pending MLflow exports and local run links |
| `/skill:ml-validation` | Design or audit validation and confirmation |
| `/skill:ml-diagnostics` | Analyze held-out errors and unexpected scores |
| `/skill:ml-experiment-design` | Plan a controlled experiment or bounded search |
| `/skill:ml-reproducibility` | Structure code and reproduce the selected model |

The agent should pursue the task actively and ask when missing information
changes the objective, data access, validation design, budget, or scope.
It must implement task solutions independently. Web research can inform ideas;
copying or adapting external solution repositories, notebooks, pipelines or
task-specific checkpoints is prohibited, including publicly licensed ones.
Standard libraries and authorized base models/data remain usable. This is agent
guidance, not a shell-level enforcement boundary; live compliance needs evaluation.
Default recorded-experiment limits are 300 seconds/run and 5 runs/Pi session.
Adjust `project.json` after agreeing on an appropriate budget.

## Where code and knowledge live

```text
godel/                         # Harness repository
├── src/godel/                 # Python state, context, execution, CLI
├── pi/                        # Thin TypeScript tools and terminal commands
├── agent/                     # Core instructions and short ML foundation
│   └── skills/                # On-demand SKILL.md workflows and references
├── templates/project/         # Default Python project structure
├── tests/                     # Offline correctness and integration checks
├── evals/                     # Agent behavior cases and evaluation protocol
├── docs/                      # Architecture, research, improvement roadmap
├── .godel/                    # Private local state; ignored by Git
│   ├── pi/                    # Godel-only settings, models and credentials
│   └── state.sqlite3          # History, runs, checkpoints, lessons and export queue
├── mlflow/                    # Private local MLflow database and artifact copies
└── projects/                  # Independent repositories; ignored by harness Git
    └── churn/
        ├── .git/
        ├── brief.md           # Goal, data, evaluation, scope and decisions
        ├── project.json       # Identity, tags, evaluation and run limits
        ├── pyproject.toml     # This project's own dependencies
        ├── src/ml_project/    # Reusable Python code
        ├── experiments/       # Thin experiment entrypoints
        ├── tests/             # Split, transformation and model checks
        ├── reports/           # Human-readable conclusions
        └── .godel/            # History, sessions, runs, snapshots and artifacts
```

Data and generated artifacts stay local. Each project should create its own
environment and dependency lockfile as its needs become clear. Godel does not
force scikit-learn, PyTorch, an experiment tracker, or a deployment stack onto it.
Project initialization creates a Git repository without a remote or commit.

## What isolation means here

All Godel-owned settings, credentials, sessions and knowledge stay in this
workspace. The launcher disables automatic extension, skill, prompt, theme, and
ancestor-context discovery and loads Godel's resources explicitly. Inherited
provider credentials and shell startup hooks are omitted from the launch
environment. The agent reads its current project's own instructions explicitly.

Local commands can use your machine. This is configuration and
knowledge isolation, not an OS sandbox. The shell and Python tools have the
launcher's host permissions; run limits and lesson review are workflow controls,
not a security boundary against code with those permissions.

## Record an experiment

Set `project.json.evaluation` before the first scored experiment:

```json
{
  "datasetId": "churn-2026-09-v1",
  "splitId": "grouped-by-customer-seed-17",
  "metric": "roc_auc",
  "direction": "maximize"
}
```

The agent calls `godel_run` with a hypothesis, argv, source paths and timeout.
For remote compute, `godel_remote_run` registers the exact job/version and imports
its downloaded results into the same project experiment. The agent owns launching,
monitoring and collecting the job; the harness never polls or launches remote work.
See [the remote tracking workflow](docs/kaggle.md#agent-owned-remote-experiment-tracking).
The current launcher does not activate the remote tool in its explicit tool list;
use the documented shell API fallback for remote registration and collection.
An experiment writes results to the fresh run directory:

```python
import json
import os
from pathlib import Path

run_dir = Path(os.environ["GODEL_RUN_DIR"])
(run_dir / "metrics.json").write_text(json.dumps({"roc_auc": validation_auc}))
```

Every run records its command, session/model identity when called through Pi,
evaluation definition, timestamps, source hashes/snapshots, output and status.
Only successful runs with valid metrics and identical evaluation definitions
can appear as the best measured result. Dataset/split identity is declared by
the project; the harness does not independently verify those labels or scores.
Source snapshots cover explicitly listed files, not the whole environment.

For an offline demonstration with synthetic data:

```bash
make demo
make verify
```

The demo creates a fresh `projects/demo-<id>/` repository, fits a linear regression,
compares it with a mean baseline, and saves real measurements. It requires no
model credentials. Tests cover the runner, learning lifecycle, persistence,
configuration isolation, and loading the adapter with the actual Pi runtime.

## Conversation history for improvement

MLflow session traces are the authoritative conversation history. They retain
prompts, completed model messages, tool results, decisions, selected context and
lifecycle events. Each request has a trace; its Pi session ID groups the traces
in MLflow's Sessions UI. The agent uses `godel_history`, `godel_history_event`
and `godel_evidence` for bounded retrieval and evidence links.

The persistent Python bridge records events into a durable delivery queue without
waiting for MLflow. Verified delivery removes the queued payload. SQLite retains
operational state and event IDs, not a second acknowledged conversation history.
No new Godel JSONL journals are written.

Pi's native `.godel/sessions/` files remain a runtime cache for resume, branching
and compaction. Exact snapshots are stored in MLflow and missing files are
restored before chat starts. These local files are required by the pinned Pi runtime;
they are not the history search backend. All history remains local and ignored
by Git. No automatic training or wholesale history injection occurs.

```bash
python3 bin/godel.py history churn --query baseline
python3 bin/godel.py history churn  # Session IDs and MLflow link
```

## Local MLflow

```bash
make setup-tracking
python3 bin/godel.py tracking start
python3 bin/godel.py tracking migrate-history  # Existing workspaces
```

Open http://127.0.0.1:5050 to compare experiments. MLflow's database and local
artifact copies live under the root `mlflow/` directory, ignored by Git.
Each project has one `godel / <project-name>` experiment containing its chat
sessions and training runs. Use GenAI → Sessions for chats and Model training
for runs; both views refer to the same experiment.
Chat starts the local service automatically. The service exports queued histories and runs; experiments continue while it
is stopped. Use `tracking status`, `tracking sync` and `tracking stop` to inspect,
retry or stop it. `make mlflow` runs it in the foreground instead.

`godel_run` accepts optional parameters and step curves; `godel_decision` links
decisions to supporting runs. See [tracking and history](docs/tracking.md) for
the artifact contract, evidence references, migration, recovery and verification.
Reopen Pi after upgrading to load the new tools.

## Improve it over time

Start with corrections through `/teach` and reviewed proposals through `/reflect`.
Project lessons apply to one project; accepted shared lessons apply to projects
with matching tags. Retrieval injects at most five lessons within a 4,000-character
budget each turn. Retiring a lesson removes it from future retrieval.

For broader changes, edit `agent/system.md`, `agent/skills/`, workflow prompts, Python tools, or
project templates. Compare the previous and candidate versions using the
[evaluation protocol](evals/README.md). This is adaptation through context and
workflow; the first version does not fine-tune model weights or automatically
rewrite and promote its own runtime.

Read [architecture](docs/architecture.md), [research and design decisions](docs/research.md),
and the [next iterations](docs/roadmap.md). Live provider behavior and improvement
on real ML tasks still require evaluation with your chosen model and projects.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, formatting, checks and pull request
guidance, [verification](docs/verification.md) for what has been tested, and
[SECURITY.md](SECURITY.md) for private reporting and the local operating model.

Godel is available under the [MIT license](LICENSE). Dependencies retain their
own licenses. Datasets, model weights and external research are not included in
that grant; follow their respective terms.
