# Research and design decisions

Reviewed 2026-09-13 against primary sources and the locally installed Pi 0.74.2.
This records the original design review; the current supported Pi version is
pinned in `package.json` and checked by the adapter integration suite.
The recommendations below are design inferences. Published results for other
agents or benchmarks are not evidence that Godel already improves itself.

## Why Pi fits

[Pi's official documentation](https://github.com/earendil-works/pi/tree/main/packages/coding-agent)
describes a minimal coding harness with an interactive terminal, extension tools,
session branching, prompt templates, SDK embedding and RPC integration. The
current package is `@earendil-works/pi-coding-agent`; older material often uses
`@mariozechner/pi-coding-agent` and `badlogic/pi-mono`.

The [extension interface](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
supports the needed tools, slash commands, UI status and per-turn context hooks.
We verified these against the installed package and load the actual adapter in
offline integration tests. The native TypeScript extension is a small bridge to
Python, keeping the domain logic in the harness's primary implementation language.

**Decision:** reuse Pi's terminal and loop. Keep domain state outside its
conversation history. Adopt RPC if a separate UI becomes useful; an additional
orchestration framework is not needed for the first working flow.

## What self-adaptation should mean first

| Source | Relevant mechanism | Godel decision |
| --- | --- | --- |
| [ACE: Agentic Context Engineering](https://arxiv.org/abs/2510.04618) | Incremental generation, reflection and curation of contextual strategies; addresses knowledge loss from repeatedly rewriting summaries | Keep individual lessons with evidence and scope; retrieve a bounded selection; retain retirement history |
| [GEPA](https://arxiv.org/abs/2507.19457) | Reflect on execution trajectories and evaluate prompt candidates | Later optimize prompts against a stable local task set; do not treat reflection alone as improvement |
| [Darwin Gödel Machine](https://sakana.ai/dgm/) | Evaluate self-modifications and retain a branching archive of agent variants | Keep harness changes separate, versioned and evaluated; postpone automatic runtime evolution |
| [AIDE](https://github.com/WecoAI/aideml) | Execute and iteratively refine ML solutions using a search tree | Record hypotheses, executable attempts, measurements and optional parent run IDs before adding search policies |

There are three distinct optimization targets: solving the current ML problem,
improving the agent's context/workflow across problems, and training underlying
model weights. This version implements the first target's infrastructure and a
reviewed context-feedback loop. It does not implement model-weight training,
GEPA, ACE's full algorithm, AIDE tree search, or the DGM algorithm.

The hypothesis is that well-scoped corrections and useful execution evidence
will improve later work. Test that hypothesis on held-out project tasks rather
than assuming an increasing lesson count means an increasing capability.

## Reliability across sessions

[Anthropic's long-running harness study](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
reports that compaction alone does not preserve reliable progress; explicit
state, incremental work and verified outcomes help sessions continue usefully.
Its experiments concern software application development, so transfer to ML is
a design inference.

**Decision:** save a structured checkpoint and concrete run records. Preserve
the objective, evaluation definition and current next step independently of
Pi's conversation. A resumed agent should establish the state before taking
another action, and never infer that a conversation branch rewound the code.

## Measure the ML work and the agent separately

[MLE-bench](https://github.com/openai/mle-bench) provides task data/evaluation and
agent evaluation machinery for ML engineering. It is useful evidence that
the measurable unit should include the actual produced solution. Its Kaggle
scope does not cover every internal ML lifecycle or justify running the full
benchmark as the first local milestone.

[Anthropic's agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
distinguishes task outcomes, trajectories, graders and repeated trials. The
model and harness must be evaluated together; multiple sources of judgment may
be needed for complex behavior.

**Decision:** maintain two measurement layers. Project experiments measure ML
artifacts under a stable evaluator. Agent evaluations measure task completion,
scope decisions, leakage handling, reproducibility, communication and cost.
Use executed artifact checks where possible and human review for ambiguous
choices. Repeat model trials when assessing a behavioral change.

## Isolation and code ownership

The [Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)
and resource-loading options provide explicit extension/resource selection.
Pi extensions execute with host-process privileges. Configuration isolation is
therefore distinct from command isolation.

**Decision from the user:** encapsulate Godel's information and configuration,
while allowing local machine use. Disable global discovery and inherited model
credentials, use workspace-local auth/state, and keep a narrow explicit resource
list. Do not add a container or call this a security sandbox.

Each ML project owns its own repository and Python environment. Godel owns the
reusable agent behavior and project template. This avoids coupling a project's
dependencies, history and release cycle to the harness, while leaving the whole
working environment in one convenient directory.

## Deliberately deferred

Automatic agent-code mutation requires a credible evaluator, isolated candidate
execution, versioned promotion and rollback. Adding it now would make the system
harder to assess before we have representative ML projects. Likewise, multi-agent
scheduling, vector memory, a web dashboard, remote job orchestration and model
fine-tuning should answer observed needs. The current modules provide places to
add them without changing who owns project code or experiment evidence.
