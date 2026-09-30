#!/usr/bin/env node
import { createServer } from 'node:http';
import { createReadStream, createWriteStream } from 'node:fs';
import { chmod, mkdir, readFile, readdir, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { hostname, homedir, networkInterfaces } from 'node:os';
import path from 'node:path';
import { randomBytes, randomInt, timingSafeEqual, randomUUID } from 'node:crypto';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { isIP } from 'node:net';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function option(name, fallback) {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
}

const host = option('--host', process.env.HOST || '0.0.0.0');
const port = Number(option('--port', process.env.PORT || '8787'));
const inbox = path.resolve(option('--dir', process.env.DESKDROP_DIR || path.join(here, 'received')));
const maxBytes = Number(process.env.MAX_FILE_SIZE || 1024 * 1024 * 1024);
const pin = process.env.TRANSFER_PIN || String(randomInt(100000, 1000000));
const sessionCookie = 'deskdrop_session';
const sessions = new Map();
const loginAttempts = new Map();
const sessionTtlMs = 7 * 24 * 60 * 60 * 1000;
const stateDir = path.resolve(process.env.DESKDROP_STATE_DIR || path.join(homedir(), '.local', 'state', 'deskdrop'));
const sessionsFile = path.join(stateDir, 'sessions.json');
const messagesFile = path.join(stateDir, 'messages.json');
const trustedClients = (process.env.DESKDROP_TRUSTED_CLIENTS || '').split(',').map((entry) => entry.trim()).filter(Boolean);
const maxMessages = 500;
const messages = [];
const eventClients = new Set();
const publicFiles = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/style.css', ['style.css', 'text/css; charset=utf-8']],
]);

if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be between 1 and 65535.');
if (!/^\d{4,12}$/.test(pin)) throw new Error('TRANSFER_PIN must contain 4 to 12 digits.');
if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) throw new Error('MAX_FILE_SIZE must be a positive byte count.');
await mkdir(inbox, { recursive: true });
await mkdir(stateDir, { recursive: true, mode: 0o700 });
await chmod(stateDir, 0o700).catch(() => {});

try {
  const saved = JSON.parse(await readFile(sessionsFile, 'utf8'));
  for (const [token, expires] of Object.entries(saved)) {
    if (/^[0-9a-f]{64}$/.test(token) && Number.isFinite(expires) && expires > Date.now()) sessions.set(token, expires);
  }
} catch (error) {
  if (error.code !== 'ENOENT') console.warn(`Could not restore saved login sessions: ${error.message}`);
}

try {
  const saved = JSON.parse(await readFile(messagesFile, 'utf8'));
  if (Array.isArray(saved)) {
    for (const message of saved.slice(-maxMessages)) {
      if (message && typeof message.id === 'string' && ['text', 'file'].includes(message.type)
        && Number.isFinite(message.createdAt) && typeof message.sender === 'string') messages.push(message);
    }
  }
} catch (error) {
  if (error.code !== 'ENOENT') console.warn(`Could not restore saved chat history: ${error.message}`);
}

async function persistSessions() {
  const now = Date.now();
  for (const [token, expires] of sessions) if (expires <= now) sessions.delete(token);
  const temp = `${sessionsFile}.${randomUUID()}.tmp`;
  await writeFile(temp, JSON.stringify(Object.fromEntries(sessions)), { mode: 0o600 });
  await chmod(temp, 0o600);
  await rename(temp, sessionsFile);
}

async function persistMessages() {
  while (messages.length > maxMessages) messages.shift();
  const temp = `${messagesFile}.${randomUUID()}.tmp`;
  await writeFile(temp, JSON.stringify(messages), { mode: 0o600 });
  await chmod(temp, 0o600);
  await rename(temp, messagesFile);
}

function publish(event) {
  const payload = `data: ${JSON.stringify(event)}\n\n`;
  for (const client of eventClients) {
    try {
      if (client.destroyed || !client.write(payload)) continue;
    } catch {
      eventClients.delete(client);
    }
  }
}

function cleanSender(value) {
  const sender = String(value || '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 32);
  return sender || '我的电脑';
}

function cleanSenderId(value) {
  const id = String(value || '');
  return /^[a-zA-Z0-9_-]{8,64}$/.test(id) ? id : 'unknown-device';
}

function headers(res) {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
  res.setHeader('Cache-Control', 'no-store');
}

function json(res, status, value, extraHeaders = {}) {
  headers(res);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...extraHeaders });
  res.end(JSON.stringify(value));
}

function getSession(req) {
  const cookieHeader = req.headers.cookie || '';
  const value = cookieHeader.split(';').map((part) => part.trim()).find((part) => part.startsWith(`${sessionCookie}=`))?.slice(sessionCookie.length + 1);
  if (!value) return null;
  const expires = sessions.get(value);
  if (!expires || expires < Date.now()) {
    sessions.delete(value);
    return null;
  }
  return value;
}

function requireSession(req, res) {
  if (getSession(req) || isTrustedClient(req)) return true;
  json(res, 401, { error: 'Please enter the PIN to continue.' });
  return false;
}

function readJson(req, maxLength = 2048) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > maxLength) {
        reject(Object.assign(new Error('Request body is too large.'), { status: 413 }));
        req.destroy();
      }
    });
    req.on('end', () => {
      try { resolve(JSON.parse(body || '{}')); }
      catch { reject(Object.assign(new Error('Invalid JSON.'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

function safeFilename(input) {
  let name = path.basename(String(input || 'file').replaceAll('\\', '/'))
    .normalize('NFC')
    .replace(/[\u0000-\u001f<>:"/\\|?*]/g, '_')
    .replace(/[. ]+$/g, '')
    .trim()
    .slice(0, 180);
  if (!name || name === '.' || name === '..') name = 'file';
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i.test(name)) name = `_${name}`;
  return name;
}

function decodePathname(url) {
  try { return decodeURIComponent(url.pathname); }
  catch { return ''; }
}

function contentDisposition(name) {
  const fallback = name.replace(/[^\x20-\x7E]/g, '_').replace(/["\\]/g, '_');
  return `attachment; filename="${fallback}"; filename*=UTF-8''${encodeURIComponent(name)}`;
}

async function listFiles() {
  const entries = await readdir(inbox, { withFileTypes: true });
  const files = await Promise.all(entries.filter((entry) => entry.isFile() && /^[0-9a-f-]{36}__/.test(entry.name)).map(async (entry) => {
    const info = await stat(path.join(inbox, entry.name));
    return { id: entry.name, name: entry.name.slice(38), size: info.size, modified: info.mtimeMs };
  }));
  return files.sort((a, b) => b.modified - a.modified);
}

function clientIp(req) {
  const address = req.socket.remoteAddress || 'unknown';
  return address.startsWith('::ffff:') ? address.slice(7) : address;
}

function ipv4Number(address) {
  if (isIP(address) !== 4) return null;
  return address.split('.').reduce((value, octet) => ((value << 8) | Number(octet)) >>> 0, 0);
}

function isTrustedClient(req) {
  const address = clientIp(req);
  if (address === '127.0.0.1' || address === '::1') return true;
  for (const rule of trustedClients) {
    if (!rule.includes('/')) {
      if (address === rule) return true;
      continue;
    }
    const [network, prefixText, ...extra] = rule.split('/');
    const bits = Number(prefixText);
    const clientNumber = ipv4Number(address);
    const networkNumber = ipv4Number(network);
    if (extra.length || clientNumber === null || networkNumber === null || !Number.isInteger(bits) || bits < 0 || bits > 32) continue;
    const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
    if ((clientNumber & mask) === (networkNumber & mask)) return true;
  }
  return false;
}

async function handle(req, res) {
  headers(res);
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const route = decodePathname(url);

  if (req.method === 'GET' && publicFiles.has(route)) {
    const [filename, type] = publicFiles.get(route);
    res.writeHead(200, { 'Content-Type': type });
    createReadStream(path.join(here, 'public', filename)).pipe(res);
    return;
  }

  if (req.method === 'GET' && route === '/api/status') {
    json(res, 200, { authenticated: Boolean(getSession(req) || isTrustedClient(req)), room: hostname() });
    return;
  }

  if (req.method === 'POST' && route === '/api/login') {
    if (trustedClients.length) {
      json(res, 403, { error: 'PIN login is disabled for this two-computer room.' });
      return;
    }
    const ip = clientIp(req);
    const attempt = loginAttempts.get(ip);
    if (attempt && attempt.until > Date.now() && attempt.count >= 8) {
      json(res, 429, { error: 'Too many attempts. Wait one minute and try again.' });
      return;
    }
    const body = await readJson(req);
    const candidate = String(body.pin || '');
    const a = Buffer.from(candidate);
    const b = Buffer.from(pin);
    const valid = a.length === b.length && timingSafeEqual(a, b);
    if (!valid) {
      const current = attempt && attempt.until > Date.now() ? attempt : { count: 0, until: Date.now() + 60_000 };
      current.count += 1;
      loginAttempts.set(ip, current);
      json(res, 401, { error: 'That PIN did not match. Check the terminal on the receiving computer.' });
      return;
    }
    loginAttempts.delete(ip);
    const token = randomBytes(32).toString('hex');
    sessions.set(token, Date.now() + sessionTtlMs);
    await persistSessions();
    json(res, 200, { ok: true }, {
      'Set-Cookie': `${sessionCookie}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${Math.floor(sessionTtlMs / 1000)}`,
    });
    return;
  }

  if (req.method === 'POST' && route === '/api/logout') {
    const token = getSession(req);
    if (token) {
      sessions.delete(token);
      await persistSessions();
    }
    json(res, 200, { ok: true }, { 'Set-Cookie': `${sessionCookie}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0` });
    return;
  }

  if (route.startsWith('/api/') && !requireSession(req, res)) return;

  if (req.method === 'GET' && route === '/api/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.write(': connected\n\n');
    eventClients.add(res);
    const heartbeat = setInterval(() => {
      if (!res.destroyed) res.write(': ping\n\n');
    }, 25_000);
    heartbeat.unref();
    req.on('close', () => {
      clearInterval(heartbeat);
      eventClients.delete(res);
    });
    return;
  }

  if (req.method === 'GET' && route === '/api/messages') {
    const knownFiles = new Set(messages.filter((message) => message.type === 'file').map((message) => message.fileId));
    const files = await listFiles();
    const legacy = files.filter((file) => !knownFiles.has(file.id)).map((file) => ({
      id: `legacy-${file.id}`,
      type: 'file',
      fileId: file.id,
      name: file.name,
      size: file.size,
      sender: '已接收文件',
      senderId: 'legacy',
      createdAt: file.modified,
    }));
    const history = [...messages, ...legacy].sort((a, b) => a.createdAt - b.createdAt);
    json(res, 200, { messages: history });
    return;
  }

  if (req.method === 'POST' && route === '/api/messages') {
    const body = await readJson(req, 16 * 1024);
    const text = String(body.text || '').trim();
    if (!text) { json(res, 400, { error: '消息不能为空。' }); return; }
    if (text.length > 2000) { json(res, 413, { error: '消息最多 2000 个字符。' }); return; }
    const message = {
      id: randomUUID(),
      type: 'text',
      text,
      sender: cleanSender(body.sender),
      senderId: cleanSenderId(body.senderId),
      createdAt: Date.now(),
    };
    messages.push(message);
    await persistMessages();
    publish({ type: 'message', message });
    json(res, 201, { message });
    return;
  }

  if (req.method === 'GET' && route === '/api/files') {
    json(res, 200, { files: await listFiles(), maxBytes });
    return;
  }

  if (req.method === 'POST' && route === '/api/upload') {
    const rawName = url.searchParams.get('name') || 'file';
    const filename = safeFilename(rawName);
    const id = `${randomUUID()}__${filename}`;
    const tempPath = path.join(inbox, `.${randomUUID()}.part`);
    const targetPath = path.join(inbox, id);
    if (Number(req.headers['content-length'] || 0) > maxBytes) {
      json(res, 413, { error: `This file is larger than the ${formatBytes(maxBytes)} limit.` });
      req.resume();
      return;
    }
    let received = 0;
    const limiter = new Transform({
      transform(chunk, encoding, callback) {
        received += chunk.length;
        if (received > maxBytes) callback(Object.assign(new Error('File is too large.'), { code: 'LIMIT_EXCEEDED' }));
        else callback(null, chunk);
      },
    });
    try {
      await pipeline(req, limiter, createWriteStream(tempPath, { flags: 'wx' }));
      await rename(tempPath, targetPath);
      const file = await stat(targetPath);
      const message = {
        id: randomUUID(),
        type: 'file',
        fileId: id,
        name: filename,
        size: received,
        sender: cleanSender(url.searchParams.get('sender')),
        senderId: cleanSenderId(url.searchParams.get('senderId')),
        createdAt: file.mtimeMs,
      };
      messages.push(message);
      await persistMessages();
      publish({ type: 'message', message });
      json(res, 201, { id, name: filename, size: received });
    } catch (error) {
      await unlink(tempPath).catch(() => {});
      if (error.code === 'LIMIT_EXCEEDED') json(res, 413, { error: `This file is larger than the ${formatBytes(maxBytes)} limit.` });
      else if (error.code === 'ECONNRESET' || error.code === 'ERR_STREAM_PREMATURE_CLOSE') return;
      else throw error;
    }
    return;
  }

  const fileMatch = route.match(/^\/api\/files\/(.+)$/);
  if (fileMatch) {
    const id = fileMatch[1];
    if (!/^[0-9a-f-]{36}__/.test(id) || path.basename(id) !== id) {
      json(res, 400, { error: 'Invalid file id.' });
      return;
    }
    const filePath = path.join(inbox, id);
    let info;
    try { info = await stat(filePath); }
    catch { json(res, 404, { error: 'File not found.' }); return; }
    if (!info.isFile()) { json(res, 404, { error: 'File not found.' }); return; }
    if (req.method === 'GET') {
      const name = id.slice(38);
      res.writeHead(200, {
        'Content-Type': 'application/octet-stream',
        'Content-Length': info.size,
        'Content-Disposition': contentDisposition(name),
      });
      createReadStream(filePath).pipe(res);
      return;
    }
    if (req.method === 'DELETE') {
      await unlink(filePath);
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        if (messages[index].type === 'file' && messages[index].fileId === id) messages.splice(index, 1);
      }
      await persistMessages();
      publish({ type: 'refresh' });
      json(res, 200, { ok: true });
      return;
    }
  }

  json(res, 404, { error: 'Not found.' });
}

function formatBytes(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

function localAddresses() {
  const addresses = [];
  for (const rows of Object.values(networkInterfaces())) {
    for (const item of rows || []) {
      if (item.family === 'IPv4' && !item.internal) addresses.push(item.address);
    }
  }
  return [...new Set(addresses)];
}

const server = createServer((req, res) => {
  handle(req, res).catch((error) => {
    if (res.headersSent) {
      res.destroy(error);
      return;
    }
    json(res, error.status || 500, { error: error.status ? error.message : 'Something went wrong on the receiving computer.' });
    if (!error.status) console.error(error);
  });
});

server.listen(port, host, () => {
  const addresses = localAddresses();
  console.log('\nDeskDrop is ready. On the sending computer, open one of these addresses:');
  console.log(`  This computer: http://localhost:${port}`);
  const localHostname = hostname().split('.')[0];
  if (/^[a-zA-Z0-9-]+$/.test(localHostname)) console.log(`  Hostname (if mDNS is enabled): http://${localHostname}.local:${port}`);
  for (const address of addresses) console.log(`  Local network: http://${address}:${port}`);
  if (trustedClients.length) console.log('\nTrusted-computer mode is on; PIN login is disabled.');
  else console.log(`\nPIN: ${pin}`);
  console.log(`Receiving files in: ${inbox}`);
  if (process.env.DESKDROP_SERVICE === '1') console.log('Running as a user service. Stop it with: systemctl --user stop deskdrop.service\n');
  else console.log('Keep this terminal open while transferring files. Press Ctrl+C to stop.\n');
});
