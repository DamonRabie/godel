import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import {
  DefaultResourceLoader,
  SettingsManager,
  formatSkillsForPrompt,
} from '@earendil-works/pi-coding-agent';
import { pythonRequest } from '../dist/pi/bridge.js';
import { agentStatusWidget } from '../dist/pi/extension.js';

const skillNames = [
  'ml-diagnostics',
  'ml-experiment-design',
  'ml-reproducibility',
  'ml-validation',
];

test('agent status widget summarizes completed and current work', () => {
  assert.deepEqual(
    agentStatusWidget({
      summary: 'Inspected the data and established a baseline.',
      next: 'Diagnose the largest validation errors.',
      blockers: ['Waiting for target-column confirmation.'],
    }),
    [
      'Done: Inspected the data and established a baseline.',
      'Working on: Diagnose the largest validation errors.',
      'Blocked: Waiting for target-column confirmation.',
    ],
  );

  assert.deepEqual(agentStatusWidget(null), [
    'Done: No progress checkpoint yet.',
    'Working on: Clarify the brief and establish a baseline.',
  ]);
  assert.deepEqual(agentStatusWidget({ summary: 'Retained legacy progress.' }), [
    'Done: Retained legacy progress.',
    'Working on: No current focus recorded.',
  ]);

  const compacted = agentStatusWidget({
    summary: `Finished  the first pass.\n${'x'.repeat(220)}`,
    next: 'Review results.',
    blockers: [],
  });
  assert.ok(compacted[0].startsWith('Done: Finished the first pass. '));
  assert.ok(compacted[0].endsWith('…'));
  assert.equal(compacted[0].length, 186);
});

test('actual Pi loader registers Godel tools/commands and only explicit resources', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'godel-pi-'));
  try {
    const agentDir = join(temporary, 'agent');
    const project = join(temporary, 'project');
    await mkdir(join(agentDir, 'extensions'), { recursive: true });
    await mkdir(project);
    await writeFile(
      join(agentDir, 'extensions', 'unwanted.ts'),
      'throw new Error("Global extension must not load")',
    );
    await writeFile(join(temporary, 'AGENTS.md'), 'UNWANTED_ANCESTOR_CONTEXT');
    for (const location of [
      join(agentDir, 'skills', 'ambient'),
      join(project, '.pi', 'skills', 'ambient'),
      join(temporary, '.agents', 'skills', 'ambient'),
    ]) {
      await mkdir(location, { recursive: true });
      await writeFile(
        join(location, 'SKILL.md'),
        '---\nname: ambient\ndescription: Unwanted ambient skill.\n---\nAMBIENT_BODY',
      );
    }
    const loader = new DefaultResourceLoader({
      cwd: project,
      agentDir,
      settingsManager: SettingsManager.inMemory(),
      noExtensions: true,
      noSkills: true,
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true,
      additionalExtensionPaths: [resolve('dist/pi/extension.js')],
      additionalPromptTemplatePaths: [resolve('agent/prompts')],
      additionalSkillPaths: skillNames.map((name) => resolve('agent/skills', name, 'SKILL.md')),
    });
    await loader.reload();
    const loaded = loader.getExtensions();
    assert.deepEqual(loaded.errors, []);
    assert.equal(loaded.extensions.length, 1);
    const extension = loaded.extensions[0];
    assert.deepEqual([...extension.tools.keys()].sort(), [
      'godel_checkpoint',
      'godel_decision',
      'godel_evidence',
      'godel_history',
      'godel_history_event',
      'godel_propose_lesson',
      'godel_remote_run',
      'godel_review',
      'godel_run',
    ]);
    for (const command of ['project', 'runs', 'lessons', 'teach', 'accept', 'retire', 'history'])
      assert.ok(extension.commands.has(command));
    for (const hook of [
      'input',
      'message_end',
      'tool_execution_start',
      'tool_execution_end',
      'session_start',
      'session_shutdown',
    ])
      assert.ok(extension.handlers.has(hook));
    assert.deepEqual(loader.getAgentsFiles().agentsFiles, []);
    const skillResult = loader.getSkills();
    assert.deepEqual(skillResult.diagnostics, []);
    assert.deepEqual(skillResult.skills.map((skill) => skill.name).sort(), skillNames);
    const catalog = formatSkillsForPrompt(skillResult.skills);
    for (const skill of skillResult.skills) {
      assert.equal(skill.disableModelInvocation, false);
      assert.ok(catalog.includes(skill.name));
      assert.ok(catalog.includes(skill.description));
      const content = await readFile(skill.filePath, 'utf8');
      const body = content.split('---')[2].trim();
      assert.ok(!catalog.includes(body), 'Detailed skill body must load on demand');
      // References must remain inside the shared workspace and actually exist.
      for (const match of content.matchAll(/\]\(([^)]+)\)/g)) {
        if (/^https?:/.test(match[1])) continue;
        const reference = resolve(skill.baseDir, match[1]);
        assert.ok(reference.startsWith(resolve('.') + '/'));
        await readFile(reference);
      }
    }
    assert.ok(!catalog.includes('AMBIENT_BODY'));
    assert.deepEqual(
      loader
        .getPrompts()
        .prompts.map((prompt) => prompt.name)
        .sort(),
      ['plan', 'reflect', 'report'],
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test('Python bridge transports large conversation records over stdin', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'godel-bridge-'));
  try {
    const script = join(temporary, 'echo.py');
    await writeFile(
      script,
      'import json, sys\nvalue = json.load(sys.stdin)\nprint(json.dumps(value))\n',
    );
    const payload = { text: 'conversation evidence '.repeat(30000) };
    assert.deepEqual(await pythonRequest('python3', script, temporary, 'echo', payload), payload);
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      pythonRequest('python3', script, temporary, 'echo', {}, controller.signal),
      /cancelled/,
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test('pinned Pi CLI supports the isolation flags used by the Python launcher', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'godel-help-'));
  try {
    const { stdout, stderr } = await promisify(execFile)(
      resolve('node_modules/.bin/pi'),
      ['--offline', '--no-session', '--help'],
      {
        env: {
          PATH: process.env.PATH,
          HOME: temporary,
          PI_CODING_AGENT_DIR: temporary,
          PI_TELEMETRY: '0',
        },
        timeout: 20000,
      },
    );
    for (const flag of [
      '--session-dir',
      '--no-extensions',
      '--no-skills',
      '--skill',
      '--no-context-files',
      '--tools',
    ])
      assert.ok((stdout + stderr).includes(flag), flag);
    const pkg = JSON.parse(
      await readFile('node_modules/@earendil-works/pi-coding-agent/package.json', 'utf8'),
    );
    const manifest = JSON.parse(await readFile('package.json', 'utf8'));
    assert.equal(pkg.version, manifest.dependencies['@earendil-works/pi-coding-agent']);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
