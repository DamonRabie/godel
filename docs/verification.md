# Verification

Run from a complete source checkout after `make setup`:

```bash
make verify
make verify-tracking
```

`make verify` runs Python lint and formatting checks, TypeScript formatting and
compilation, the actual Pi loader/bridge tests, and Python unit tests. It does not
make model calls. Tests exercise temporary projects with synthetic evidence;
they do not require or modify existing user projects.

`make verify-tracking` also launches real local MLflow services in temporary
workspaces. It checks metric/artifact delivery, retries, project mapping,
conversation search, pagination, payload integrity, native session restoration,
legacy migration and service restart. It requires the tracking environment
installed by `make setup` and permission to bind loopback ports.

The optional installed Kaggle CLI test skips when `.godel/tools/kaggle/` is absent.
The ten tests requiring live local MLflow skip in the ordinary suite and run via
`make verify-tracking`. Skips are not evidence of integration success.

## Publication review

The 2026-09-14 review uses Pi 0.85.1, Node.js 22.22.0 and MLflow 3.16.0 in a
separate clean source copy with Python 3.12.12. The ordinary suite passes 48
Python tests and all 3 Pi integration tests; 10 tracking tests and the optional
installed Kaggle CLI test skip. The tracking command runs all 12 tracking tests
and all 8 trace tests, with some tests shared between commands. The installed
Kaggle CLI check also passed separately in the original workspace.

Both `npm audit` and an audit of the clean Python tracking environment report
no known dependency vulnerabilities at review time. This is a point-in-time
dependency check, not a guarantee about unreported issues or model behavior.
The public source file scan found no credential signatures or personal paths,
and relative Markdown links resolve within the distributable tree.

The GitHub Actions workflow runs the same setup and checks on Linux/Python 3.11
and macOS/Python 3.12 with Node.js 22. A local pass does not establish a hosted CI
pass; that requires the workflow to run after publication.

No provider inference, paid compute, remote job or model-quality evaluation was
performed during this publication review. The synthetic regression fixture
tests execution and evidence collection, not general ML agent competence.
The [behavior evaluation protocol](../evals/README.md) defines the separate trials
needed to support quality or improvement claims.
