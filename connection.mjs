import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import { readConnection } from './opencode.mjs';

const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1']);

function isLoopback(hostname) {
  const h = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  return LOOPBACK.has(h);
}

function normalizeBaseUrl(raw) {
  let u;
  try {
    u = new URL(String(raw));
  } catch {
    throw new Error('modelConfig.baseUrl must be a valid absolute URL');
  }
  return u;
}

// Validates spec.modelConfig structurally AND at execution time (called on every invocation).
async function resolveOpenAICompatible(spec) {
  const mc = spec?.modelConfig;
  if (!mc || typeof mc !== 'object') throw new Error('modelConfig is required for provider openai-compatible');
  const { provider, model, baseUrl, api, contextWindow, maxTokens, apiKeyEnv, apiKeyFile, apiKeyNone, apiKey } = mc;
  if (provider !== 'openai-compatible') throw new Error('modelConfig.provider must be openai-compatible');
  if (typeof model !== 'string' || !model.trim() || model !== spec.model) throw new Error('modelConfig.model must match spec.model');
  if (api !== 'openai-completions') throw new Error("modelConfig.api must be 'openai-completions'");
  if (!Number.isInteger(contextWindow) || contextWindow <= 0) throw new Error('modelConfig.contextWindow must be a positive integer');
  if (!Number.isInteger(maxTokens) || maxTokens <= 0) throw new Error('modelConfig.maxTokens must be a positive integer');
  if (maxTokens > contextWindow) throw new Error('modelConfig.maxTokens must not exceed contextWindow');
  if ('apiKey' in mc) throw new Error('modelConfig must not contain an inline apiKey');

  const sources = [
    'apiKeyEnv' in mc ? 'apiKeyEnv' : null,
    'apiKeyFile' in mc ? 'apiKeyFile' : null,
    'apiKeyNone' in mc ? 'apiKeyNone' : null,
  ].filter(Boolean);
  if (sources.length !== 1) throw new Error('modelConfig must specify exactly one of apiKeyEnv, apiKeyFile, or apiKeyNone:true');
  if (sources[0] === 'apiKeyEnv' && (typeof apiKeyEnv !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(apiKeyEnv))) throw new Error('apiKeyEnv must be an environment variable name');
  if (sources[0] === 'apiKeyFile' && (typeof apiKeyFile !== 'string' || !apiKeyFile.startsWith('/'))) throw new Error('apiKeyFile must be an absolute path');
  if (sources[0] === 'apiKeyNone' && apiKeyNone !== true) throw new Error('apiKeyNone must be true');
  if (typeof baseUrl !== 'string' || !baseUrl.trim()) throw new Error('modelConfig.baseUrl must be a valid absolute URL');

  const url = normalizeBaseUrl(baseUrl);
  if (url.username || url.password) throw new Error('modelConfig.baseUrl must not contain credentials');
  if (url.search && url.search !== '') throw new Error('modelConfig.baseUrl must not contain a query string');
  if (url.hash && url.hash !== '') throw new Error('modelConfig.baseUrl must not contain a fragment');
  const loopback = isLoopback(url.hostname);
  if (url.protocol === 'https:') {
    // ok
  } else if (url.protocol === 'http:' && loopback) {
    // ok: HTTP loopback (localhost, 127.0.0.1, [::1])
  } else {
    throw new Error('modelConfig.baseUrl must use HTTPS, or HTTP to a loopback host (localhost, 127.0.0.1, [::1])');
  }
  if (sources[0] === 'apiKeyNone' && !loopback) {
    throw new Error('apiKeyNone is only allowed for loopback endpoints');
  }
  const normalized = url.href.replace(/\/$/, '');

  let access;
  let credentialSource;
  let sensitive;
  if (sources[0] === 'apiKeyEnv') {
    // Secret read happens only here, inside the worker at execution time.
    const raw = process.env[apiKeyEnv];
    if (typeof raw !== 'string' || raw.trim() === '') {
      throw new Error(`API key unavailable from environment variable ${apiKeyEnv}`);
    }
    access = raw.trim();
    credentialSource = 'environment';
    sensitive = [access];
  } else if (sources[0] === 'apiKeyFile') {
    if (!apiKeyFile.startsWith('/')) throw new Error('modelConfig.apiKeyFile must be an absolute path');
    let handle;
    let raw;
    try {
      // Inspect and read the same descriptor, without following a final symlink.
      handle = await fs.open(apiKeyFile, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      const st = await handle.stat();
      if (!st.isFile() || st.size > 65536) throw new Error('API key file must be a small regular file');
      if (typeof process.getuid === 'function' && st.uid !== process.getuid()) throw new Error('API key file must be owned by the current user');
      if ((st.mode & 0o077) !== 0) throw new Error('API key file permissions must exclude group and other users (use chmod 600)');
      raw = await handle.readFile('utf8');
    } catch (error) {
      throw new Error(`API key unavailable from file ${apiKeyFile}${error.code ? '' : ': ' + error.message}`);
    } finally {
      await handle?.close();
    }
    if (raw.trim() === '') throw new Error(`API key unavailable from file ${apiKeyFile}`);
    access = raw.trim();
    credentialSource = 'file';
    sensitive = [access];
  } else {
    // apiKeyNone: some Pi runtime paths require a credential string even for
    // keyless local servers. Use a non-secret placeholder; the root worker may
    // choose to omit the Authorization header entirely. It is NOT sensitive.
    access = 'no-auth-local-loopback';
    credentialSource = 'none';
    sensitive = [];
  }

  const modelDefinition = {
    id: spec.model,
    name: spec.model,
    api: 'openai-completions',
    provider: 'openai-compatible',
    baseUrl: normalized,
    reasoning: false,
    input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow,
    maxTokens,
    compat: {
      supportsStore: false,
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      maxTokensField: 'max_tokens',
    },
  };

  return {
    access,
    sensitive,
    baseUrl: normalized,
    headers: {},
    source: {
      kind: 'OpenAI-compatible API',
      endpoint: normalized,
      credentialSource,
    },
    costKnown: false, // SDK requires numeric costs; zero placeholders are not a price claim.
    modelDefinition,
  };
}

export async function readConfiguredConnection(spec) {
  const provider = spec?.provider;
  if (provider === undefined || provider === 'opencode-go') {
    return readConnection(spec?.model);
  }
  if (provider === 'openai-compatible') {
    return resolveOpenAICompatible(spec);
  }
  throw new Error(`Unsupported provider: ${String(provider)}`);
}
