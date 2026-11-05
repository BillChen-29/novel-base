import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {test} from 'node:test';
import {acquireLock, recoverLock, disposeAndRelease} from '../retrieval_pilot_lock.mjs';

const helper = fileURLToPath(new URL('../retrieval_pilot_lock.mjs', import.meta.url));
function temporary(fn) {
  const directory = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'retrieval-lock-'));
  return Promise.resolve().then(() => fn(path.join(directory, 'embedding.lock')))
    .finally(() => fs.rmSync(directory, {recursive: true, force: true}));
}
function abandoned(lockPath) {
  const code = `import {acquireLock} from ${JSON.stringify(pathToFileURL(helper).href)}; acquireLock(process.argv[1]);`;
  const child = spawnSync(process.execPath, ['--input-type=module', '-e', code, lockPath], {encoding: 'utf8'});
  assert.equal(child.status, 0, child.stderr);
  return JSON.parse(fs.readFileSync(lockPath, 'utf8'));
}

test('records ownership and rejects a concurrent owner', () => temporary(lockPath => {
  const lock = acquireLock(lockPath);
  const record = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  assert.equal(record.pid, process.pid);
  assert.ok(Number.isFinite(Date.parse(record.created_at)));
  assert.ok(Number.isFinite(Date.parse(record.process_started_at)));
  assert.match(record.token, /^[a-f0-9-]{36}$/);
  assert.throws(() => acquireLock(lockPath), /active|running/i);
  assert.throws(() => recoverLock(lockPath, record.token), /active|running/i);
  assert.deepEqual(JSON.parse(fs.readFileSync(lockPath, 'utf8')), record);
  assert.equal(lock.release(), true);
  assert.equal(fs.existsSync(lockPath), false);
  assert.equal(lock.release(), false);
}));

test('dead process lock reports a recovery command and can be explicitly recovered', () => temporary(lockPath => {
  const old = abandoned(lockPath);
  assert.throws(() => acquireLock(lockPath), /recover.*embedding\.lock/);
  recoverLock(lockPath, old.token);
  const current = acquireLock(lockPath);
  assert.notEqual(current.record.token, old.token);
  current.release();
}));

test('recovery refuses an outdated token', () => temporary(lockPath => {
  const old = abandoned(lockPath);
  assert.throws(() => recoverLock(lockPath, 'outdated-token'), /changed|token/i);
  assert.equal(JSON.parse(fs.readFileSync(lockPath, 'utf8')).token, old.token);
}));

test('release preserves a replacement lock', () => temporary(lockPath => {
  const old = acquireLock(lockPath);
  fs.unlinkSync(lockPath);
  const replacement = acquireLock(lockPath);
  assert.equal(old.release(), false);
  assert.equal(JSON.parse(fs.readFileSync(lockPath, 'utf8')).token, replacement.record.token);
  replacement.release();
}));

test('cleanup attempts every resource and releases ownership even when disposal throws', () => temporary(async lockPath => {
  const lock = acquireLock(lockPath);
  const called = [];
  await assert.rejects(disposeAndRelease([
    {dispose: async () => { called.push('context'); throw Error('context failure'); }},
    {dispose: async () => { called.push('model'); }},
    {dispose: async () => { called.push('runtime'); throw Error('runtime failure'); }},
  ], lock), AggregateError);
  assert.deepEqual(called, ['context', 'model', 'runtime']);
  assert.equal(fs.existsSync(lockPath), false);
}));

test('an active recovery guard blocks other recovery attempts', () => temporary(lockPath => {
  const old = abandoned(lockPath);
  const guard = acquireLock(lockPath + '.recovery');
  assert.throws(() => recoverLock(lockPath, old.token), /active|running/i);
  assert.equal(JSON.parse(fs.readFileSync(lockPath, 'utf8')).token, old.token);
  guard.release();
  recoverLock(lockPath, old.token);
}));

test('unknown legacy locks and linked paths are preserved', () => temporary(lockPath => {
  fs.writeFileSync(lockPath, '');
  assert.throws(() => recoverLock(lockPath, 'anything'), /invalid|unknown|legacy/i);
  assert.equal(fs.readFileSync(lockPath, 'utf8'), '');
  fs.unlinkSync(lockPath);
  const outside = lockPath + '.source';
  fs.writeFileSync(outside, 'preserved');
  fs.symlinkSync(outside, lockPath);
  assert.throws(() => acquireLock(lockPath), /symbolic|symlink/i);
  assert.throws(() => recoverLock(lockPath, 'anything'), /symbolic|symlink/i);
  assert.equal(fs.readFileSync(outside, 'utf8'), 'preserved');
  fs.unlinkSync(lockPath);
  const old = abandoned(lockPath);
  fs.linkSync(lockPath, lockPath + '.copy');
  assert.throws(() => recoverLock(lockPath, old.token), /hard.link/i);
  assert.equal(fs.statSync(lockPath).nlink, 2);
}));

test('the recovery CLI works without importing any model runtime', () => temporary(lockPath => {
  const old = abandoned(lockPath);
  const result = spawnSync(process.execPath, [helper, 'recover', lockPath, old.token], {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(lockPath), false);
}));


test('embedding cache success and fingerprint failure both release the lock without model imports', () => temporary(lockPath => {
  const directory = path.dirname(lockPath);
  const hash = value => crypto.createHash('sha256').update(value).digest('hex');
  const dataset = '{}';
  fs.writeFileSync(path.join(directory, 'dataset.json'), dataset);
  const item = {id: hash('query\0test'), kind: 'query', text: 'test', title: ''};
  const input = JSON.stringify({schema_version: 1, dataset_sha256: hash(dataset), items: [item]});
  const inputPath = path.join(directory, 'embedding-input.json');
  fs.writeFileSync(inputPath, input);
  const modelPath = path.join(directory, 'never-loaded.gguf');
  fs.writeFileSync(modelPath, 'not-a-model');
  const qmd = path.join(directory, 'qmd');
  const runtime = path.join(qmd, 'node_modules/node-llama-cpp');
  fs.mkdirSync(runtime, {recursive: true});
  fs.writeFileSync(path.join(qmd, 'package.json'), '{"version":"test"}');
  fs.writeFileSync(path.join(runtime, 'package.json'), '{"version":"test"}');
  const output = path.join(directory, 'embeddings.json');
  const state = {schema_version: 1, model_sha256: hash('not-a-model'), model_file: 'never-loaded.gguf',
    qmd_version: 'test', runtime_version: 'test', prefix: 'qmd-format-functions-v1', requested_gpu: false,
    context_size: 2048, threads: 4, input_sha256: hash(input), dataset_sha256: hash(dataset),
    dimensions: 2, complete: true, total_inputs: 1, vectors: {[item.id]: [1, 0]}, elapsed_seconds: 0,
    query_embedding_ms: {}};
  fs.writeFileSync(output, JSON.stringify(state));
  const embed = fileURLToPath(new URL('../retrieval_pilot_embed.mjs', import.meta.url));
  const command = [embed, '--input', inputPath, '--output', output, '--model', modelPath,
    '--qmd-root', qmd, '--gpu', 'false'];
  let result = spawnSync(process.execPath, command, {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Cached complete index/);
  assert.equal(fs.existsSync(lockPath), false);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, 'utf8')), state);
  state.model_sha256 = 'incorrect';
  fs.writeFileSync(output, JSON.stringify(state));
  result = spawnSync(process.execPath, command, {encoding: 'utf8'});
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Checkpoint mismatch: model_sha256/);
  assert.equal(fs.existsSync(lockPath), false);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, 'utf8')), state);
}));
