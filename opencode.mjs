import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const run = promisify(execFile);
const localHost = url => ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);

export async function discoverOpenCode() {
  if (process.env.OPENCODE_V2_SERVER && process.env.OPENCODE_V2_CLI) {
    return { server: process.env.OPENCODE_V2_SERVER, cli: process.env.OPENCODE_V2_CLI };
  }
  const { stdout } = await run('ps', ['-axo', 'pid=,ppid=,comm=']);
  const processes = stdout.split('\n').map(line => line.match(/^\s*(\d+)\s+(\d+)\s+(.+)$/)).filter(Boolean);
  const desktops = new Set(processes.filter(p => p[3].endsWith('/OpenCode.app/Contents/MacOS/OpenCode')).map(p => p[1]));
  const candidates = processes.filter(p => p[3].endsWith('/opencode-cli') && desktops.has(p[2]));
  const found = [];
  for (const p of candidates) {
    const { stdout: listeners } = await run('lsof', ['-a', '-p', p[1], '-iTCP', '-sTCP:LISTEN', '-Fn']).catch(() => ({ stdout: '' }));
    const ports = [...listeners.matchAll(/^n(?:localhost|127\.0\.0\.1|\[::1\]):(\d+)$/gm)];
    for (const port of ports) found.push({ cli: p[3], server: 'http://127.0.0.1:' + port[1] });
  }
  if (found.length !== 1) throw new Error('Cannot uniquely discover local OpenCode v2. Set OPENCODE_V2_SERVER and OPENCODE_V2_CLI.');
  return found[0];
}

export async function readConnection(modelId) {
  const location = await discoverOpenCode();
  const url = new URL(location.server);
  if (!localHost(url) || url.username || url.password) throw new Error('Only a local OpenCode v2 server is supported');
  const service = JSON.parse(await fs.readFile(path.join(os.homedir(), '.config/opencode/service.json'), 'utf8'));
  if (!service.password) throw new Error('Local OpenCode service password is unavailable');
  let exported;
  try {
    const { stdout } = await run(location.cli, ['auth', 'export', 'opencode', '--server', location.server], {
      env: { ...process.env, OPENCODE_PASSWORD: service.password }, timeout: 20000, maxBuffer: 1024 * 1024,
    });
    exported = JSON.parse(stdout);
  } catch {
    // Never propagate execFile errors: they retain credential-bearing stdout.
    throw new Error('Could not read active OpenCode v2 login');
  }
  const active = exported.filter(c => c.active === true && c.value?.type === 'oauth');
  if (active.length !== 1) throw new Error('Expected one active OpenCode login');
  const credential = active[0].value;
  if (credential.expires <= Date.now()) throw new Error('OpenCode access token expired; refresh the login in OpenCode');
  const response = await fetch(new URL('/api/model', url), {
    headers: { authorization: 'Basic ' + Buffer.from('opencode:' + service.password).toString('base64') },
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error('OpenCode model lookup failed: HTTP ' + response.status);
  const { data } = await response.json();
  const model = data.find(m => m.providerID === 'opencode-go' && m.modelID === modelId && m.enabled);
  if (!model) throw new Error('Requested Go model is not enabled in OpenCode');
  if (model.headers?.['x-opencode-org-id'] !== credential.metadata?.orgID) throw new Error('Model and login workspaces differ');
  const endpoint = new URL(model.settings.baseURL);
  if (endpoint.protocol !== 'https:' || endpoint.hostname !== 'opencode.ai' || endpoint.username || endpoint.password || endpoint.search) {
    throw new Error('Unexpected Go endpoint; refusing to forward credentials');
  }
  return {
    access: credential.access,
    sensitive: [credential.access, credential.refresh, service.password].filter(Boolean),
    baseUrl: endpoint.href.replace(/\/$/, ''),
    headers: { 'x-opencode-org-id': model.headers['x-opencode-org-id'] },
    source: { kind: 'OpenCode v2 active OAuth', server: location.server, endpoint: endpoint.href, credentialId: active[0].id },
  };
}
