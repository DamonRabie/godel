import { spawn } from 'node:child_process';
import { request } from 'node:http';
import { dirname, join } from 'node:path';

function serviceRequest(
  entrypoint: string,
  project: string,
  action: string,
  payload: unknown,
): Promise<any> {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ project, action, payload });
    const req = request(
      {
        socketPath: join(dirname(dirname(entrypoint)), '.godel/api.sock'),
        path: '/',
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      },
      (response) => {
        let result = '';
        response.setEncoding('utf8').on('data', (chunk) => {
          result += chunk;
        });
        response.on('end', () => {
          try {
            const value = JSON.parse(result);
            if (response.statusCode !== 200)
              reject(new Error(value.error ?? 'Godel service failed.'));
            else resolve(value);
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    req.on('error', reject);
    req.setTimeout(30000, () =>
      req.destroy(new Error('Godel service request timed out; outcome may be unknown.')),
    );
    req.end(body);
  });
}

/** JSON goes over stdin so large conversation events do not hit argv limits. */
export async function pythonRequest(
  python: string,
  entrypoint: string,
  project: string,
  action: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<any> {
  if (signal?.aborted) return Promise.reject(new Error('Godel request cancelled before launch.'));
  if (!['run', 'remote_run'].includes(action)) {
    try {
      return await serviceRequest(entrypoint, project, action, payload);
    } catch (error) {
      // Only retry when no connection was established. Retrying an ambiguous
      // response could duplicate a checkpoint, lesson or event.
      if (!['ENOENT', 'ECONNREFUSED'].includes((error as NodeJS.ErrnoException).code ?? ''))
        throw error;
    }
  }
  return new Promise((resolve, reject) => {
    const child = spawn(python, [entrypoint, 'api', action, '--project', project], {
      cwd: project,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let forceKill: ReturnType<typeof setTimeout> | undefined;
    const abort = () => {
      child.kill('SIGTERM');
      forceKill = setTimeout(() => {
        if (child.exitCode === null) child.kill('SIGKILL');
      }, 5000);
    };
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    child.stdout.setEncoding('utf8').on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.setEncoding('utf8').on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', reject);
    child.stdin.on('error', (error) => {
      if ((error as NodeJS.ErrnoException).code !== 'EPIPE') reject(error);
    });
    child.on('close', (code) => {
      if (forceKill) clearTimeout(forceKill);
      signal?.removeEventListener('abort', abort);
      if (code !== 0 || !stdout.trim()) {
        reject(new Error(stderr.trim() || `Godel ${action} stopped without a result.`));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`Godel ${action} returned invalid JSON.`));
      }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}
