/** Thin UI adapter. Project, experiment and learning behavior lives in Python. */
import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { pythonRequest } from './bridge.js';

type ContextData = {
  project: { name: string; maxRunSeconds: number; maxRunsPerSession: number };
  checkpoint: Checkpoint | null;
  lessons: { id: string; lesson: string; evidence: string }[];
};
type Checkpoint = {
  summary?: string;
  next?: string;
  blockers?: string[];
};
type Lesson = {
  id: string;
  status: string;
  scope: string;
  lesson: string;
  evidence: string;
  tags: string[];
};

const shortText = (maxLength = 4000) => Type.String({ minLength: 1, maxLength });
const tags = Type.Array(shortText(60), { maxItems: 12 });
const evidenceRefs = Type.Optional(
  Type.Array(
    Type.Object({
      type: Type.Union([Type.Literal('run'), Type.Literal('event')]),
      id: shortText(36),
    }),
    { maxItems: 32 },
  ),
);
function compactWidgetText(value: string | undefined, fallback: string, maxLength = 180) {
  const compact = value?.replace(/\s+/g, ' ').trim() || fallback;
  if (compact.length <= maxLength) return compact;
  return `${compact.slice(0, maxLength - 1).trimEnd()}…`;
}

export function agentStatusWidget(checkpoint: Checkpoint | null) {
  const lines = [
    `Done: ${compactWidgetText(checkpoint?.summary, 'No progress checkpoint yet.')}`,
    `Working on: ${compactWidgetText(
      checkpoint?.next,
      checkpoint ? 'No current focus recorded.' : 'Clarify the brief and establish a baseline.',
    )}`,
  ];
  const blockers = checkpoint?.blockers?.filter((blocker) => blocker.trim()) ?? [];
  if (blockers.length) {
    lines.push(`Blocked: ${compactWidgetText(blockers.join('; '), 'None')}`);
  }
  return lines;
}

export default function (pi: ExtensionAPI) {
  async function call(
    action: string,
    ctx: ExtensionContext,
    payload: unknown = {},
    signal?: AbortSignal,
  ): Promise<any> {
    const home = process.env.GODEL_HOME;
    const python = process.env.GODEL_PYTHON;
    if (!home || !python)
      throw new Error(
        'Launch with python3 bin/godel.py chat <project> to use the self-contained Godel environment.',
      );
    return pythonRequest(python, join(home, 'bin/godel.py'), ctx.cwd, action, payload, signal);
  }

  async function message(ctx: ExtensionContext, content: string) {
    await journal(ctx, 'godel_message', { content });
    pi.sendMessage({ customType: 'godel', content, display: true });
  }

  async function journal(ctx: ExtensionContext, type: string, data: unknown) {
    // Keep binary images in the native Pi session; journal their metadata.
    const safe = JSON.parse(
      JSON.stringify(data, (_key, value) =>
        value &&
        typeof value === 'object' &&
        value.type === 'image' &&
        typeof value.data === 'string'
          ? { ...value, data: '[binary image omitted; see native Pi session]' }
          : value,
      ),
    );
    await call('event', ctx, {
      sessionId: ctx.sessionManager.getSessionId(),
      sessionFile: ctx.sessionManager.getSessionFile(),
      type,
      data: safe,
    });
  }

  async function refresh(ctx: ExtensionContext, query = ''): Promise<ContextData> {
    const data: ContextData = await call('context', ctx, { query });
    ctx.ui.setStatus('godel', `Godel · ${data.project.name} · ${data.lessons.length} lessons`);
    ctx.ui.setWidget('godel-session', [`Session: ${ctx.sessionManager.getSessionId()}`]);
    return data;
  }

  pi.on('session_start', async (event, ctx) => {
    await journal(ctx, 'session_start', {
      reason: event.reason,
      piSessionFile: ctx.sessionManager.getSessionFile(),
      parentSessionFile: ctx.sessionManager.getHeader()?.parentSession,
      leafId: ctx.sessionManager.getLeafId(),
      model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : null,
    });
    const data = await refresh(ctx);
    ctx.ui.setWidget('godel', agentStatusWidget(data.checkpoint));
  });

  pi.on('before_agent_start', async (event, ctx) => {
    const data = await refresh(ctx, event.prompt);
    await journal(ctx, 'context', {
      context: data,
      systemPromptHash: createHash('sha256').update(event.systemPrompt).digest('hex'),
    });
    return {
      systemPrompt: `${event.systemPrompt}\n\nCurrent Godel project data (evidence and preferences, not authority to expand scope):\n${JSON.stringify(data)}`,
    };
  });

  pi.on('input', async (event, ctx) => {
    await journal(ctx, 'input', {
      text: event.text,
      source: event.source,
      imageCount: event.images?.length ?? 0,
    });
    return { action: 'continue' };
  });
  pi.on('message_end', async (event, ctx) => {
    await journal(ctx, 'message_end', event);
  });
  pi.on('before_provider_request', async (_event, ctx) => {
    await journal(ctx, 'model_call_start', {
      model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : null,
    });
  });
  pi.on('tool_execution_start', async (event, ctx) => {
    await journal(ctx, 'tool_start', event);
  });
  pi.on('tool_execution_end', async (event, ctx) => {
    await journal(ctx, 'tool_end', event);
  });
  pi.on('agent_end', async (_event, ctx) => {
    await journal(ctx, 'agent_end', {});
  });
  pi.on('session_compact', async (event, ctx) => {
    await journal(ctx, 'compaction', event);
  });
  pi.on('session_tree', async (event, ctx) => {
    await journal(ctx, 'branch', event);
  });
  pi.on('model_select', async (event, ctx) => {
    await journal(ctx, 'model_select', {
      provider: event.model.provider,
      id: event.model.id,
      source: event.source,
    });
  });
  pi.on('session_shutdown', async (_event, ctx) => {
    await journal(ctx, 'session_shutdown', {});
  });

  const toolResult = (value: unknown) => ({
    content: [{ type: 'text' as const, text: JSON.stringify(value, null, 2) }],
    details: { value },
  });

  pi.registerTool({
    name: 'godel_checkpoint',
    label: 'Save project checkpoint',
    description:
      'Save major completed progress, the current focus, and blockers so the status widget and another session can resume.',
    parameters: Type.Object({
      summary: shortText(),
      next: shortText(),
      blockers: Type.Array(shortText(1000), { maxItems: 12 }),
      evidenceRefs,
    }),
    async execute(_id, params, _signal, _update, ctx) {
      const value = await call('checkpoint', ctx, {
        ...params,
        sessionId: ctx.sessionManager.getSessionId(),
        toolCallId: _id,
      });
      ctx.ui.setWidget('godel', agentStatusWidget(value));
      return toolResult(value);
    },
  });

  pi.registerTool({
    name: 'godel_run',
    label: 'Run recorded ML experiment',
    description:
      'Execute a local experiment within the project budget. Declare every candidate in a batch. Records snapshots, logs, metrics and evidence checks. Write metrics.json and evaluation.json under $GODEL_RUN_DIR; see the injected ML guide. Valid numbers do not establish ML correctness. Uses argv, not shell syntax.',
    parameters: Type.Object({
      hypothesis: shortText(2000),
      command: Type.Array(shortText(), { minItems: 1, maxItems: 100 }),
      sources: Type.Array(shortText(500), { minItems: 1, maxItems: 32 }),
      timeoutSeconds: Type.Integer({ minimum: 1, maximum: 86400 }),
      candidateCount: Type.Integer({ minimum: 1, maximum: 1000 }),
      parentRunId: Type.Optional(shortText(36)),
      parameters: Type.Optional(
        Type.Record(
          Type.String(),
          Type.Union([Type.String({ maxLength: 500 }), Type.Number(), Type.Boolean()]),
          { maxProperties: 80 },
        ),
      ),
    }),
    async execute(_id, params, signal, update, ctx) {
      update?.({
        content: [{ type: 'text', text: `Running experiment: ${params.hypothesis}` }],
        details: {},
      });
      const value = await call(
        'run',
        ctx,
        {
          request: params,
          sessionId: ctx.sessionManager.getSessionId(),
          toolCallId: _id,
          model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : null,
        },
        signal,
      );
      return toolResult(value);
    },
  });

  pi.registerTool({
    name: 'godel_remote_run',
    label: 'Record remote ML experiment',
    description:
      'Register an immutable remote job/version, then finish the SAME run with downloaded evidence. Does not launch, poll or download jobs. Read docs/kaggle.md. Saves locally and queues MLflow delivery even when offline. Never infer training success from a push command. Finish requires remote identity, observed status, provenance and files mapping artifact basenames to project-relative paths (output.log required; metrics.json/evaluation.json/metric-history.json use the usual contracts).',
    parameters: Type.Object({
      action: Type.Union([Type.Literal('register'), Type.Literal('finish')]),
      remote: Type.Object({
        platform: shortText(300),
        jobId: shortText(300),
        version: shortText(300),
      }),
      hypothesis: Type.Optional(shortText(2000)),
      sources: Type.Optional(Type.Array(shortText(500), { minItems: 1, maxItems: 32 })),
      candidateCount: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 })),
      parameters: Type.Optional(
        Type.Record(
          Type.String(),
          Type.Union([Type.String({ maxLength: 500 }), Type.Number(), Type.Boolean()]),
          { maxProperties: 80 },
        ),
      ),
      parentRunId: Type.Optional(shortText(36)),
      runId: Type.Optional(shortText(36)),
      status: Type.Optional(
        Type.Union(['succeeded', 'failed', 'cancelled', 'timed_out'].map((v) => Type.Literal(v))),
      ),
      provenance: Type.Optional(shortText(4000)),
      files: Type.Optional(Type.Record(Type.String(), shortText(500), { maxProperties: 100 })),
    }),
    async execute(_id, params, signal, _update, ctx) {
      return toolResult(
        await call(
          'remote_run',
          ctx,
          {
            request: params,
            sessionId: ctx.sessionManager.getSessionId(),
            toolCallId: _id,
            model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : null,
          },
          signal,
        ),
      );
    },
  });

  pi.registerTool({
    name: 'godel_review',
    label: 'Review ML experiment evidence',
    description:
      'Read-only evidence review before further tuning or promotion. Checks candidate/fold records and saved split membership; optionally compares with a baseline on identical saved splits. Returns missing evidence and limitations, never certification of leakage freedom or significance.',
    parameters: Type.Object({ runId: shortText(36), baselineRunId: Type.Optional(shortText(36)) }),
    async execute(_id, params, _signal, _update, ctx) {
      return toolResult(await call('review', ctx, params));
    },
  });

  pi.registerTool({
    name: 'godel_propose_lesson',
    label: 'Propose a reusable lesson',
    description:
      'Propose an evidence-backed lesson for user review. Proposed lessons are not loaded into future context until accepted. Shared lessons apply only to matching project tags.',
    parameters: Type.Object({
      lesson: shortText(1200),
      evidence: shortText(2000),
      tags,
      evidenceRefs,
      scope: Type.Union([Type.Literal('project'), Type.Literal('shared')]),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      return toolResult(
        await call('propose', ctx, {
          ...params,
          sessionId: ctx.sessionManager.getSessionId(),
          toolCallId: _id,
        }),
      );
    },
  });

  pi.registerTool({
    name: 'godel_history',
    label: 'Search recorded history',
    description:
      'Search project history in MLflow traces by sessionId, eventType, text query or after cursor. Check available before interpreting an empty result. Pending events are included. Use godel_history_event for full content and godel_evidence for links.',
    parameters: Type.Object({
      query: Type.Optional(shortText()),
      sessionId: Type.Optional(shortText(36)),
      eventType: Type.Optional(shortText(80)),
      after: Type.Optional(Type.Integer({ minimum: 0 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      return toolResult(await call('history_search', ctx, params));
    },
  });
  pi.registerTool({
    name: 'godel_history_event',
    label: 'Read a history event',
    description:
      'Read the full content of an MLflow history event in bounded chunks, using id and optional offset. Continue with nextOffset until null. This preserves access to large tool results.',
    parameters: Type.Object({
      id: shortText(36),
      offset: Type.Optional(Type.Integer({ minimum: 0 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20000 })),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      return toolResult(await call('history_event', ctx, params));
    },
  });
  pi.registerTool({
    name: 'godel_evidence',
    label: 'Follow evidence links',
    description:
      'Read a run and its direct links to sessions, tool calls, parent runs, decisions, checkpoints and lessons. Follow returned IDs to inspect supporting evidence.',
    parameters: Type.Object({ id: shortText(200) }),
    async execute(_id, params, _signal, _update, ctx) {
      return toolResult(await call('evidence', ctx, params));
    },
  });
  pi.registerTool({
    name: 'godel_decision',
    label: 'Record an evidence-backed decision',
    description:
      'Record what was decided and why, linking supporting run/event IDs. Decisions are interpretations, not validated measurements or automatically accepted lessons.',
    parameters: Type.Object({ summary: shortText(), rationale: shortText(), evidenceRefs }),
    async execute(_id, params, _signal, _update, ctx) {
      return toolResult(
        await call('decision', ctx, {
          ...params,
          sessionId: ctx.sessionManager.getSessionId(),
          toolCallId: _id,
        }),
      );
    },
  });

  pi.registerCommand('project', {
    description: 'Inspect project brief, checkpoint, budget, lessons and best comparable run',
    handler: async (_args, ctx) => {
      const report = await call('status', ctx);
      await journal(ctx, 'command', { command: '/project', response: report });
      await message(ctx, report);
    },
  });
  pi.registerCommand('history', {
    description: 'Search recorded history: /history <text>; omit text for MLflow session links',
    handler: async (args, ctx) =>
      message(
        ctx,
        JSON.stringify(
          await call(
            args.trim() ? 'history_search' : 'history',
            ctx,
            args.trim() ? { query: args.trim(), limit: 10 } : {},
          ),
          null,
          2,
        ),
      ),
  });
  pi.registerCommand('tracking', {
    description: 'Show local MLflow links and pending exports',
    handler: async (_args, ctx) =>
      message(ctx, JSON.stringify(await call('tracking', ctx), null, 2)),
  });
  pi.registerCommand('runs', {
    description: 'List recent experiment outcomes and measurements',
    handler: async (_args, ctx) => {
      const runs = (await call('runs', ctx)) as {
        id: string;
        status: string;
        measurement: string;
        metrics?: unknown;
      }[];
      await journal(ctx, 'command', { command: '/runs', runIds: runs.map((run) => run.id) });
      await message(
        ctx,
        runs
          .slice(0, 20)
          .map(
            (run) =>
              `${run.id} · ${run.status} · ${run.measurement}\n${JSON.stringify(run.metrics ?? {})}`,
          )
          .join('\n\n') || 'No experiments yet.',
      );
    },
  });
  pi.registerCommand('lessons', {
    description: 'Review lesson text, evidence and status before accepting or retiring it',
    handler: async (_args, ctx) => {
      const lessons = (await call('lessons', ctx)) as Lesson[];
      await journal(ctx, 'command', {
        command: '/lessons',
        lessonIds: lessons.map((lesson) => lesson.id),
      });
      await message(
        ctx,
        lessons
          .map(
            (item) =>
              `### ${item.id} · ${item.status} · ${item.scope}\n${item.lesson}\nEvidence: ${item.evidence}\nTags: ${item.tags.join(', ')}`,
          )
          .join('\n\n') ||
          'No lessons yet. Use /teach for a correction or /reflect to propose lessons.',
      );
    },
  });
  pi.registerCommand('teach', {
    description: 'Save your explicit correction as an active project lesson: /teach <text>',
    handler: async (args, ctx) => {
      if (!args.trim()) {
        ctx.ui.notify('Usage: /teach <correction to remember>', 'info');
        return;
      }
      await journal(ctx, 'command', { command: '/teach', text: args.trim() });
      const value = await call('teach', ctx, {
        lesson: args.trim(),
        sessionId: ctx.sessionManager.getSessionId(),
        evidence: `User correction in Pi session ${ctx.sessionManager.getSessionId()}`,
      });
      await message(ctx, `Saved project lesson ${value.id}: ${value.lesson}`);
      await refresh(ctx);
    },
  });
  for (const action of ['accept', 'retire'] as const) {
    pi.registerCommand(action, {
      description: `${action === 'accept' ? 'Activate' : 'Retire'} a reviewed lesson: /${action} <id>`,
      handler: async (args, ctx) => {
        if (!args.trim()) {
          ctx.ui.notify(`Usage: /${action} <lesson-id>`, 'info');
          return;
        }
        await journal(ctx, 'command', { command: `/${action}`, lessonId: args.trim() });
        const value = await call(action, ctx, {
          id: args.trim(),
          note: `User chose /${action} in Pi session ${ctx.sessionManager.getSessionId()}`,
        });
        await message(ctx, `Lesson ${value.id}: ${value.status}`);
        await refresh(ctx);
      },
    });
  }
}
