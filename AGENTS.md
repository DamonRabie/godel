# Working on Godel

Godel is a Python ML harness with a thin TypeScript adapter for Pi's terminal.
Keep project/state/learning/execution behavior in `src/godel/` and UI bindings in
`pi/`. Runtime instructions belong in `agent/`; project conventions in
`templates/project/`. The harness creates independent repositories under
`projects/`; their code never belongs in this repository's Git history.

- Read `README.md` and `docs/architecture.md` before changing boundaries.
- All Pi configuration, credentials, sessions and agent knowledge stay inside
  this workspace. Do not automatically discover or import global Pi/agent
  configuration. An explicit user request may copy a selected provider into the
  local configuration; keep runtime loading independent of global files.
- Local tools can use the host machine. Resource isolation is not a sandbox.
- Preserve project data and `.godel/` state. Do not log or commit secrets.
- Use `make verify`; model-free checks do not prove live model capability.
- Contributor setup and review conventions live in `CONTRIBUTING.md`. Use
  `make format` for formatting and `make verify-tracking` for storage/history
  changes. Keep the lockfiles current; CI runs the same checks on a clean checkout.
- Prefer Python stdlib and narrow interfaces. Add dependencies when a real task
  justifies them. Pin Pi and test adapter compatibility before upgrading it.
- Do not make harness self-modification an automatic part of solving ML tasks.
