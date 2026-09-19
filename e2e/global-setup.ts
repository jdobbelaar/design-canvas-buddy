import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '..');
const composeFile = path.join(repoRoot, 'docker-compose.yaml');

function run(command: string, args: string[], env: NodeJS.ProcessEnv) {
  return spawnSync(command, args, { cwd: repoRoot, env, encoding: 'utf8' });
}

/** Starts the compose stack; returns a function that removes it again. */
export default async function globalSetup(): Promise<(() => void) | void> {
  // Pointed at a stack that is already running: nothing to start or stop.
  if (process.env.E2E_BASE_URL) return;

  const project = process.env.E2E_PROJECT!;
  const port = process.env.E2E_PORT!;

  const docker = run('docker', ['info'], process.env);
  if (docker.error || docker.status !== 0) {
    throw new Error(
      'The e2e tests need Docker with the compose plugin and a running daemon, ' +
        `but it is not available.\n${docker.error ?? docker.stderr}`,
    );
  }

  // An explicit environment, so a developer's shell (POSTGRES_PASSWORD, ...) or a
  // root .env can't change what is being tested.
  const env: NodeJS.ProcessEnv = { ...process.env, APP_PORT: port };
  for (const key of Object.keys(env)) {
    if (key.startsWith('POSTGRES_') || key === 'DATABASE_URL') delete env[key];
  }
  const scratch = mkdtempSync(path.join(tmpdir(), 'dcb-e2e-'));
  const emptyEnvFile = path.join(scratch, 'empty.env'); // stops compose reading a root .env
  writeFileSync(emptyEnvFile, '');

  const compose = (...args: string[]) =>
    run('docker', ['compose', '-p', project, '--env-file', emptyEnvFile, '-f', composeFile, ...args], env);

  console.log(
    `\nStarting the docker compose stack "${project}" on port ${port} ` +
      '(the first run builds the image and can take a few minutes)...',
  );
  const up = compose('up', '-d', '--build', '--wait', '--wait-timeout', '180');
  if (up.status !== 0) {
    const logs = compose('logs', '--tail', '60').stdout;
    compose('down', '-v', '--rmi', 'local', '--remove-orphans');
    rmSync(scratch, { recursive: true, force: true });
    throw new Error(`docker compose up failed:\n${up.stdout}\n${up.stderr}\n--- logs ---\n${logs}`);
  }
  console.log('Stack is healthy.\n');

  return () => {
    console.log(`\nRemoving the docker compose stack "${project}" (containers, volume, image)...`);
    // -v drops the database volume; --rmi local drops the image built for this
    // throwaway project name so repeated runs don't leave one tagged image each.
    compose('down', '-v', '--rmi', 'local', '--remove-orphans');
    rmSync(scratch, { recursive: true, force: true });
  };
}
