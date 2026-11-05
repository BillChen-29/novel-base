// Ownership-aware local locks. Recovery is explicit and never removes a live process lock.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const modulePath = fileURLToPath(import.meta.url);
const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
function checkedPath(value) {
  const resolved = path.resolve(value);
  for (let current = resolved; ; current = path.dirname(current)) {
    try {
      if (fs.lstatSync(current).isSymbolicLink()) throw Error('Symbolic link lock paths are not allowed');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    if (current === path.dirname(current)) break;
  }
  return resolved;
}
function readLock(lockPath) {
  const stat = fs.lstatSync(lockPath);
  if (!stat.isFile() || stat.isSymbolicLink()) throw Error('Lock must be a regular file, not a symbolic link');
  if (stat.nlink !== 1) throw Error('Hard-linked locks cannot be recovered');
  let record;
  try { record = JSON.parse(fs.readFileSync(lockPath, 'utf8')); } catch { /* fail closed below */ }
  if (!record || record.schema_version !== 1 || !Number.isSafeInteger(record.pid) || record.pid <= 0
      || typeof record.token !== 'string' || !/^[a-f0-9-]{36}$/.test(record.token)
      || !Number.isFinite(Date.parse(record.created_at)) || !Number.isFinite(Date.parse(record.process_started_at))) {
    throw Error('Unknown or legacy lock owner; preserve this lock and use a new run directory until ownership is checked');
  }
  return {record, stat};
}
function isRunning(pid) {
  try { process.kill(pid, 0); return true; } catch (error) {
    if (error.code === 'ESRCH') return false;
    // EPERM and other errors cannot establish that a process has exited.
    return true;
  }
}
function occupied(lockPath) {
  const {record} = readLock(lockPath);
  if (isRunning(record.pid)) return Error(`Lock belongs to active or unverifiable PID ${record.pid}; do not remove it`);
  return Error(`Lock owner PID ${record.pid} has exited. Recover explicitly, then retry:\n`
    + `${quote(process.execPath)} ${quote(modulePath)} recover ${quote(lockPath)} ${quote(record.token)}`);
}
export function acquireLock(value) {
  const lockPath = checkedPath(value);
  let fd;
  try { fd = fs.openSync(lockPath, 'wx', 0o600); } catch (error) {
    if (error.code === 'EEXIST') throw occupied(lockPath);
    throw error;
  }
  const stat = fs.fstatSync(fd);
  const record = {schema_version: 1, pid: process.pid, token: crypto.randomUUID(),
    created_at: new Date().toISOString(), process_started_at: new Date(Date.now() - process.uptime() * 1000).toISOString()};
  try { fs.writeFileSync(fd, JSON.stringify(record) + '\n'); } catch (error) {
    const current = fs.lstatSync(lockPath);
    if (current.dev === stat.dev && current.ino === stat.ino) fs.unlinkSync(lockPath);
    throw error;
  } finally { fs.closeSync(fd); }
  let released = false;
  return {record, release() {
    if (released) return false;
    released = true;
    let current;
    try { current = readLock(lockPath); } catch { return false; }
    if (current.stat.dev !== stat.dev || current.stat.ino !== stat.ino
        || current.record.token !== record.token || current.record.pid !== process.pid) return false;
    fs.unlinkSync(lockPath);
    return true;
  }};
}
export function recoverLock(value, expectedToken) {
  const lockPath = checkedPath(value);
  // Serialize recoveries, including retries, so an old recovery cannot remove a new owner.
  // If this short operation itself crashes, its guard has its own PID and recovery command.
  const guard = acquireLock(lockPath + '.recovery');
  try {
    const {record} = readLock(lockPath);
    if (record.token !== expectedToken) throw Error('Lock token changed; inspect the current owner before recovery');
    if (isRunning(record.pid)) throw Error(`Lock belongs to active or unverifiable PID ${record.pid}; recovery refused`);
    fs.unlinkSync(lockPath);
  } finally { guard.release(); }
}
export async function disposeAndRelease(resources, lock) {
  const errors = [];
  for (const resource of resources) {
    try { await resource?.dispose(); } catch (error) { errors.push(error); }
  }
  try { lock.release(); } catch (error) { errors.push(error); }
  if (errors.length) throw new AggregateError(errors, 'Embedding cleanup failed after attempting every resource and lock release');
}
if (process.argv[1] && path.resolve(process.argv[1]) === modulePath) {
  try {
    if (process.argv.length !== 5 || process.argv[2] !== 'recover') throw Error('Usage: node retrieval_pilot_lock.mjs recover LOCK_PATH LOCK_TOKEN');
    recoverLock(process.argv[3], process.argv[4]);
    console.log('Recovered exited process lock; restart the embedding command to resume its checkpoint.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
