// This sample harness follows the scripted model over the two local Pocket sockets.
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';

const CH = '/channels';
const production = process.env.POCKET_ACTIVATION_REQUIRED === '1';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function activation() {
  const file = CH + '/activation.json';
  if (!production) return JSON.parse(fs.readFileSync(file, 'utf8'));
  process.stdout.write('{"pocketStartup":"activation-wait"}\n');
  for (;;) {
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { await sleep(50); }
  }
}

function gateway(path, body) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const s = net.createConnection(CH + '/gateway.sock');
    const chunks = [];
    s.on('connect', () => {
      s.write('POST ' + path + ' HTTP/1.1\r\nHost: host\r\nContent-Type: application/json\r\nContent-Length: ' + data.length + '\r\nConnection: close\r\n\r\n');
      s.write(data);
    });
    s.on('data', chunk => chunks.push(chunk));
    s.on('error', reject);
    s.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      const cut = raw.indexOf('\r\n\r\n');
      resolve({ status: Number(raw.slice(9, 12)), text: cut < 0 ? '' : raw.slice(cut + 4) });
    });
  });
}

async function answer(session, messages) {
  const names = [];
  if (session.browser) names.push('pocket_browser_open', 'pocket_browser_fill', 'pocket_browser_click');
  else if (session.search || session.web) names.push('pocket_web_search', 'pocket_web_read', 'pocket_web_open', 'pocket_web_page');
  const limit = session.model?.stepLimit ?? 12;
  let waiting = false;
  for (let step = 0; step < limit; step++) {
    const res = await gateway('/v1/model/stream', { requestId: crypto.randomUUID(), model: session.model?.alias ?? 'practice',
      maxOutputTokens: session.model?.maxOutputTokens ?? 1024, messages, tools: waiting ? [] : names });
    if (res.status !== 200) return { status: 'completed', text: 'The model call failed: ' + res.text.slice(0, 80) };
    let text = '';
    const calls = [];
    for (const line of res.text.split('\n')) {
      if (!line.trim()) continue;
      const row = JSON.parse(line);
      if (row.type === 'text') text += row.text;
      if (row.type === 'tool') {          // a call can arrive in fragments that share an index
        const call = calls[row.index] ??= { id: '', name: '', arguments: '' };
        if (row.id) call.id = row.id;
        call.name += row.name ?? '';
        call.arguments += row.arguments ?? '';
      }
    }
    if (!calls.length) {
      return { status: waiting ? 'waiting' : 'completed', text: text || 'The model gave no answer.' };
    }
    messages.push({ role: 'assistant', content: text, toolCalls: calls });
    for (const call of calls) {
      const operation = call.name.replace(/^pocket_/, '').replace('_', '.');
      let args = {};
      try { args = JSON.parse(call.arguments || '{}'); } catch {}
      // This harness stops reading at the first fragment of a register.
      if (operation === 'web.page') {
        messages.push({ role: 'tool', toolCallId: call.id, content: 'This harness only reads the first fragment.' });
        continue;
      }
      const body = { operation, requestId: crypto.randomUUID(), ...args };
      const out = await gateway('/v1/tools/request', body);
      try { if (JSON.parse(out.text).requiresUserTakeover === true) waiting = true; } catch {}
      messages.push({ role: 'tool', toolCallId: call.id, content: out.text.slice(0, 16000) });
    }
  }
  return { status: 'completed', text: 'The step limit was reached.' };
}

const act = await activation();
// The nonce is made only after activation, from fresh randomness mixed with the entropy the host supplied.
const nonce = production ? crypto.createHash('sha256').update(crypto.randomBytes(32)).update(String(act.entropy)).digest('hex') : null;
const control = net.createConnection(CH + '/control.sock');
const messages = [];
let buffer = Buffer.alloc(0), session = null, queue = Promise.resolve();

function send(code, value) {
  const data = Buffer.from(JSON.stringify(value));
  control.write('HTTP/1.1 ' + code + (code === 200 ? ' OK' : ' Error') + '\r\nContent-Type: application/json\r\nContent-Length: ' + data.length + '\r\n\r\n');
  control.write(data);
}

async function handle(method, path, body) {
  if (method === 'GET' && path === '/v1/health') {
    return send(200, production ? { ready: true, instanceId: act.instanceId, instanceNonce: nonce } : { ready: true });
  }
  if (path === '/v1/session') {
    if (body?.runId !== act.runId || body?.taskId !== act.taskId) return send(400, { error: 'guest_protocol_error' });
    session = body;
    return send(200, { ready: true });
  }
  if (path === '/v1/message' && session) {
    messages.push({ role: 'user', content: String(body) });
    const reply = await answer(session, messages);
    return send(200, reply);
  }
  return send(404, { error: 'guest_protocol_error' });
}

control.on('data', chunk => {
  buffer = Buffer.concat([buffer, chunk]);
  queue = queue.then(async () => {
    for (;;) {
      const cut = buffer.indexOf('\r\n\r\n');
      if (cut < 0) return;
      const head = buffer.subarray(0, cut).toString('latin1').split('\r\n');
      const [method, path] = head[0].split(' ');
      const length = head.slice(1).map(h => h.match(/^content-length:\s*(\d+)/i)).find(Boolean);
      const size = length ? Number(length[1]) : 0;
      if (buffer.length < cut + 4 + size) return;
      const raw = buffer.subarray(cut + 4, cut + 4 + size).toString('utf8');
      buffer = buffer.subarray(cut + 4 + size);
      let body = null;
      try { body = raw ? JSON.parse(raw) : null; } catch {}
      await handle(method, path, body);
    }
  }).catch(() => process.exit(1));
});
control.on('close', () => process.exit(0));
control.on('error', () => process.exit(1));
