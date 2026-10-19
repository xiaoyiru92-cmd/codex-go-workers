import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { readConfiguredConnection } from './connection.mjs';

const ENV = 'CONN_TEST_KEY_ISOLATED_XYZ';
let tmpFiles = [];

beforeEach(() => { delete process.env[ENV]; });
afterEach(async () => {
  delete process.env[ENV];
  for (const f of tmpFiles) await fs.rm(path.dirname(f), { recursive: true, force: true }).catch(() => {});
  tmpFiles = [];
});

async function makeKeyFile(content, mode = 0o600) {
  const p = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'conn-test-')), 'key');
  await fs.writeFile(p, content, { mode });
  await fs.chmod(p, mode);
  tmpFiles.push(p);
  return p;
}

function base(over = {}) {
  return {
    provider: 'openai-compatible',
    model: 'm1',
    modelConfig: {
      provider: 'openai-compatible', model: 'm1', baseUrl: 'https://example.com/v1',
      api: 'openai-completions', contextWindow: 1000, maxTokens: 100,
      ...over,
    },
  };
}

describe('openai-compatible validation', () => {
  it('env key success + metadata redaction', async () => {
    process.env[ENV] = '  secret-abc  ';
    const r = await readConfiguredConnection(base({ apiKeyEnv: ENV }));
    assert.equal(r.access, 'secret-abc');
    assert.deepEqual(r.sensitive, ['secret-abc']);
    assert.equal(r.baseUrl, 'https://example.com/v1');
    assert.equal(r.source.credentialSource, 'environment');
    assert.equal(r.costKnown, false);
    assert.equal(r.modelDefinition.compat.maxTokensField, 'max_tokens');
    assert.ok(!JSON.stringify(r.source).includes('secret-abc'));
    assert.ok(!JSON.stringify(r.modelDefinition).includes('secret-abc'));
  });

  it('file key success, trims trailing slash', async () => {
    const f = await makeKeyFile('file-secret\n');
    const r = await readConfiguredConnection(base({ baseUrl: 'https://example.com/v1/', apiKeyFile: f }));
    assert.equal(r.access, 'file-secret');
    assert.deepEqual(r.sensitive, ['file-secret']);
    assert.equal(r.baseUrl, 'https://example.com/v1');
    assert.equal(r.source.credentialSource, 'file');
  });

  it('apiKeyNone loopback ok, remote rejected; dummy nonsecret', async () => {
    const r = await readConfiguredConnection(base({ baseUrl: 'http://127.0.0.1:8080', apiKeyNone: true }));
    assert.equal(r.source.credentialSource, 'none');
    assert.deepEqual(r.sensitive, []);
    assert.ok(typeof r.access === 'string' && r.access.length > 0);
    await assert.rejects(readConfiguredConnection(base({ baseUrl: 'https://example.com', apiKeyNone: true })), /loopback/);
  });

  it('malformed URLs and credential/query/fragment rejected', async () => {
    await assert.rejects(readConfiguredConnection(base({ baseUrl: 'http://example.com', apiKeyEnv: ENV })), /HTTPS|loopback/);
    await assert.rejects(readConfiguredConnection(base({ baseUrl: 'https://user@example.com', apiKeyEnv: ENV })), /credentials/);
    await assert.rejects(readConfiguredConnection(base({ baseUrl: 'https://example.com/?x=1', apiKeyEnv: ENV })), /query/);
    await assert.rejects(readConfiguredConnection(base({ baseUrl: 'https://example.com/#f', apiKeyEnv: ENV })), /fragment/);
    await assert.rejects(readConfiguredConnection(base({ baseUrl: '::not-url::', apiKeyEnv: ENV })), /valid absolute URL/);
  });

  it('conflicting sources and inline key rejected', async () => {
    const f = await makeKeyFile('x');
    await assert.rejects(readConfiguredConnection(base({ apiKeyEnv: ENV, apiKeyFile: f })), /exactly one/);
    await assert.rejects(readConfiguredConnection(base({})), /exactly one/);
    await assert.rejects(readConfiguredConnection(base({ apiKeyEnv: ENV, apiKey: 'k' })), /inline/);
    await assert.rejects(readConfiguredConnection(base({ apiKeyFile: 'relative/path' })), /absolute/);
  });

  it('missing/blank keys mention source only', async () => {
    await assert.rejects(readConfiguredConnection(base({ apiKeyEnv: ENV })), (e) => e.message.includes(ENV) && !e.message.includes('secret'));
    process.env[ENV] = '   ';
    await assert.rejects(readConfiguredConnection(base({ apiKeyEnv: ENV })), new RegExp(ENV));
    const f = await makeKeyFile('   ');
    await assert.rejects(readConfiguredConnection(base({ apiKeyFile: f })), (e) => e.message.includes(f));
  });

  it('open file permissions rejected', async () => {
    const f = await makeKeyFile('k', 0o644);
    await assert.rejects(readConfiguredConnection(base({ apiKeyFile: f })), /permissions/);
  });

  it('unsupported provider rejected', async () => {
    await assert.rejects(readConfiguredConnection({ provider: 'nope', model: 'm' }), /Unsupported provider/);
  });

  it('wrong api rejected', async () => {
    await assert.rejects(readConfiguredConnection(base({ api: 'openai-responses', apiKeyEnv: ENV })), /openai-completions/);
  });
});

describe('execution snapshot guards', () => {
  it('rejects mismatched provider/model, invalid limits and ambiguous source types', async () => {
    for (const override of [
      { provider: 'another-provider' }, { model: 'another-model' },
      { maxTokens: 1001 }, { apiKeyNone: false }, { apiKeyFile: null },
      { apiKeyEnv: 'bad\nname' }, { apiKey: null },
    ]) {
      await assert.rejects(readConfiguredConnection(base({ apiKeyEnv: ENV, ...override })));
    }
  });
  it('rejects symlink key files without following them', async () => {
    const key = await makeKeyFile('fixture-secret');
    const link = path.join(path.dirname(key), 'link');
    await fs.symlink(key, link);
    await assert.rejects(readConfiguredConnection(base({ apiKeyFile: link })), /unavailable/);
  });
});
