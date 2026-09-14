# Security and private data

Godel is experimental software for a trusted local operator. There is no supported
production release or guaranteed response schedule yet; fixes target the current
development branch.

## Operating model

The agent can run commands with your host permissions. Workspace-local Pi
configuration is not an OS sandbox. Run untrusted tasks in an environment whose
filesystem, network and compute access you are comfortable granting them.

The local MLflow service binds to loopback and is intended for local use. Godel
does not provide a public or multi-user hosting configuration. Conversation
history, artifacts, native session caches and backups can contain sensitive task
content; keep them private and review material before sharing it.

See [architecture](docs/architecture.md) for configuration, execution and recovery
boundaries. Never include credentials, private datasets or full session logs in
a public report.

## Reporting a concern

Use the hosting platform's private vulnerability reporting feature when the
published repository has it enabled. If no private reporting route is available,
open a minimal issue requesting a private contact, without disclosing the issue
details, affected data or reproduction. Wait for a private channel before sending
sensitive evidence. Maintainers should enable private reporting when publishing.
