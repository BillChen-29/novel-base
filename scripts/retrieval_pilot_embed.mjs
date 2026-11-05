#!/usr/bin/env node
// Uses an already-installed runtime and a local GGUF. Never downloads/builds models.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import {acquireLock, disposeAndRelease} from './retrieval_pilot_lock.mjs';

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  if (!process.argv[i]?.startsWith('--') || !process.argv[i + 1]) throw Error('Expected --name value pairs');
  args[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['input', 'output', 'model', 'qmd-root']) {
  if (!args[name]) throw Error(`Missing --${name}`);
}
const hash = (value) => crypto.createHash('sha256').update(value).digest('hex');
function safePath(value, mustExist = false) {
  const target = path.resolve(value);
  for (let current = target; ; current = path.dirname(current)) {
    if (fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) throw Error('Symlink path not allowed');
    if (current === path.dirname(current)) break;
  }
  if (mustExist && (!fs.existsSync(target) || !fs.statSync(target).isFile())) throw Error('Missing input file');
  return target;
}
const input = safePath(args.input, true);
const output = safePath(args.output);
// Model path is read-only; allow a trusted cache directory, but require an existing local file.
const modelPath = path.resolve(args.model);
if (!fs.existsSync(modelPath) || !fs.statSync(modelPath).isFile()) throw Error('Local GGUF is required; downloads are disabled');
if (path.dirname(input) !== path.dirname(output) || path.basename(output) !== 'embeddings.json'
    || input === output || output === modelPath) throw Error('Write embeddings.json beside the prepared input');
if (fs.existsSync(output) && fs.statSync(output).nlink !== 1) throw Error('Hard-linked output rejected');
const rawInput = fs.readFileSync(input);
const payload = JSON.parse(rawInput);
const inputHash = hash(rawInput);
if (payload.schema_version !== 1 || !Array.isArray(payload.items) || !payload.items.length) throw Error('Invalid embedding input');
const ids = new Set();
for (const item of payload.items) {
  if (!['document', 'query'].includes(item.kind) || typeof item.text !== 'string'
      || !item.text.trim() || typeof item.title !== 'string') throw Error('Invalid embedding item');
  const expected = hash(item.kind === 'query' ? `query\0${item.text}` : `document\0${item.title}\0${item.text}`);
  if (item.id !== expected || ids.has(item.id)) throw Error('Duplicate or mismatched embedding identity');
  ids.add(item.id);
}
const datasetPath = path.join(path.dirname(input), 'dataset.json');
if (hash(fs.readFileSync(datasetPath)) !== payload.dataset_sha256) throw Error('Dataset hash mismatch');
const packageRoot = path.resolve(args['qmd-root']);
const qmdVersion = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8')).version;
const runtimeRoot = path.join(packageRoot, 'node_modules/node-llama-cpp');
const runtimeVersion = JSON.parse(fs.readFileSync(path.join(runtimeRoot, 'package.json'), 'utf8')).version;
const gpu = args.gpu === 'false' ? false : (args.gpu || 'metal');
if (![false, 'metal', 'cuda', 'vulkan'].includes(gpu)) throw Error('Unsupported backend');
const threads = Number(args.threads || 4);
if (!Number.isInteger(threads) || threads < 1) throw Error('Invalid thread count');
const modelHash = await new Promise((resolve, reject) => {
  const h = crypto.createHash('sha256');
  const stream = fs.createReadStream(modelPath);
  stream.on('data', value => h.update(value));
  stream.on('end', () => resolve(h.digest('hex')));
  stream.on('error', reject);
});
const fingerprint = {model_sha256: modelHash, model_file: path.basename(modelPath), qmd_version: qmdVersion,
  runtime_version: runtimeVersion, prefix: 'qmd-format-functions-v1', requested_gpu: gpu,
  context_size: 2048, threads, input_sha256: inputHash, dataset_sha256: payload.dataset_sha256};
async function embed() {
  const lock = acquireLock(path.join(path.dirname(output), 'embedding.lock'));
  let llama, model, context, primaryError;
  const started = performance.now();
  let previousElapsed = 0;
  let state = {schema_version: 1, ...fingerprint, dimensions: null, complete: false,
    total_inputs: payload.items.length, vectors: {}, elapsed_seconds: 0, query_embedding_ms: {}};
  function checkpoint() {
    state.elapsed_seconds = previousElapsed + (performance.now() - started) / 1000;
    const temp = output + `.${process.pid}.tmp`;
    fs.writeFileSync(temp, JSON.stringify(state), {flag: 'wx'});
    fs.renameSync(temp, output);
  }
  try {
    if (fs.existsSync(output)) {
      state = JSON.parse(fs.readFileSync(output, 'utf8'));
      for (const [key, value] of Object.entries(fingerprint)) if (state[key] !== value) throw Error(`Checkpoint mismatch: ${key}`);
      for (const [id, v] of Object.entries(state.vectors)) {
        if (!ids.has(id) || !Array.isArray(v) || v.length !== state.dimensions
            || !v.every(Number.isFinite) || !v.some(n => n !== 0)) throw Error('Invalid checkpoint vector');
      }
      if (state.complete && Object.keys(state.vectors).length === ids.size) {
        console.log(`Cached complete index: ${ids.size} vectors`);
        return;
      }
    }
    previousElapsed = state.elapsed_seconds;
    // No QMD store/SQLite imports: the user's collections and index are untouched.
    const {getLlama} = await import(pathToFileURL(path.join(runtimeRoot, 'dist/index.js')));
    const {formatDocForEmbedding, formatQueryForEmbedding} = await import(pathToFileURL(path.join(packageRoot, 'dist/llm.js')));
    llama = await getLlama({gpu, build: 'never', skipDownload: true, maxThreads: threads});
    model = await llama.loadModel({modelPath, gpuLayers: gpu === false ? 0 : 'auto'});
    context = await model.createEmbeddingContext({contextSize: 2048, threads});
    state.gpu_layers = model.gpuLayers;
    state.runtime_build = llama.buildType;
    for (const item of payload.items) {
      if (state.vectors[item.id]) continue;
      const formatted = item.kind === 'query' ? formatQueryForEmbedding(item.text, modelPath)
        : formatDocForEmbedding(item.text, item.title, modelPath);
      if (model.tokenize(formatted).length > 2000) throw Error(`Input exceeds token limit: ${item.id}`);
      const then = performance.now();
      const embedding = await context.getEmbeddingFor(formatted);
      const vector = Array.from(embedding.vector);
      if (!vector.length || !vector.every(Number.isFinite) || !vector.some(n => n !== 0)) throw Error('Invalid vector');
      if (state.dimensions !== null && state.dimensions !== vector.length) throw Error('Embedding dimensions changed');
      state.dimensions = vector.length;
      state.vectors[item.id] = vector;
      if (item.kind === 'query') state.query_embedding_ms[item.id] = performance.now() - then;
      const done = Object.keys(state.vectors).length;
      if (done % 8 === 0 || done === payload.items.length) {
        checkpoint();
        console.log(`Embedded ${done}/${payload.items.length}`);
      }
    }
    state.complete = true;
    checkpoint();
    console.log(`Completed ${state.total_inputs} embeddings, ${state.dimensions} dimensions`);
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    try { await disposeAndRelease([context, model, llama], lock); }
    catch (error) {
      if (primaryError) console.error('Cleanup also failed:', error);
      else throw error;
    }
  }
}
await embed();
