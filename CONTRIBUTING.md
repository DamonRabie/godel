# Contributing to Godel

Godel is an early, source-checkout-based project. Bug reports, documentation
improvements and focused pull requests are welcome. Discuss substantial runtime,
storage or interface changes in an issue before implementing them.

## Development setup

Use macOS or Linux with Python 3.11+, Node.js 22.19.0+, npm, Git, Make and
[uv](https://docs.astral.sh/uv/getting-started/installation/). From the repository root:

```bash
make setup
make verify
```

Setup installs the locked local Python environment (including MLflow and Ruff)
and the pinned Pi adapter dependencies. No model account is needed for the tests.
Godel currently runs from a complete source checkout; a standalone PyPI wheel or
npm package is not a supported installation method.

```bash
make format           # Format Python and TypeScript; no automatic lint fixes
make lint             # Python lint and formatting, TypeScript formatting
make test             # Python tests and actual Pi adapter integration tests
make verify           # All of the above checks, without model inference
make verify-tracking  # Real local MLflow service, recovery and delivery checks
```

The tracking tests use temporary workspaces and local ports. They do not use your
existing projects or provider credentials. See [verification](docs/verification.md)
for the evidence boundary and [architecture](docs/architecture.md) for ownership.

## Scope and review

Keep reusable project/state/execution code in `src/godel/`, terminal bindings in
`pi/`, runtime guidance in `agent/`, and new-project conventions in
`templates/project/`. Read [AGENTS.md](AGENTS.md) before using an agent to contribute.
Runtime skills under `agent/skills/` are part of this distributable repository;
they must not depend on a contributor's global skill installation.

Keep each pull request focused. Explain the problem, resulting behavior and
verification, and add a regression test when behavior changes. Update the README
and relevant contracts when changing setup, interfaces or storage. Changes to
schema or history handling must preserve existing project state. Separate model
quality claims from deterministic software checks; use the [evaluation protocol](evals/README.md)
for agent behavior changes.

Never commit `.godel/`, `projects/`, `mlflow/`, credentials, real task data or
conversation logs. Use small synthetic fixtures when reproducing bugs. Inspect
the staged diff before committing; Git does not back up ignored workspace state.
Do not copy external task solutions or third-party source into the repository
without establishing permission and preserving the required notices.

Local commit subjects follow `:gitmoji: type: concise description`. Keep messages
free of private data and credentials. Before submitting, run `make verify`; run
`make verify-tracking` when changing storage, history, tracking or bridge behavior.
Describe any checks you could not run.

## Reports and conduct

Use repository issues for reproducible bugs and feature proposals. Include the
Godel revision, OS, Python/Node versions and a minimal synthetic reproduction.
For sensitive reports, follow [SECURITY.md](SECURITY.md).
Be respectful, explain disagreements with evidence, and keep discussion focused
on the work. Contributions are provided under the repository's [MIT license](LICENSE).
