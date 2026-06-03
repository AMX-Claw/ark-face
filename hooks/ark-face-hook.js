#!/usr/bin/env node
// ark-face — Claude Code Hook Script
// Auto-syncs Ark's status to iPhone 5c display via Cloudflare Worker
// Usage: node ark-face-hook.js <event_name>

const WORKER_URL = process.env.ARK_FACE_URL || 'https://ark-face.YOUR_SUBDOMAIN.workers.dev/state';
const XIAOKE_URL = process.env.XIAOKE_URL || 'https://your-baby-api.YOUR_SUBDOMAIN.workers.dev/status';
const AUTH_TOKEN = process.env.ARK_FACE_TOKEN || require('child_process').execSync("security find-generic-password -s ark-face-token -w 2>/dev/null").toString().trim();
const XIAOKE_TOKEN = process.env.XIAOKE_DADDY_TOKEN || require('child_process').execSync("security find-generic-password -s xiaoke-daddy-token -w 2>/dev/null").toString().trim();

const EVENT_TO_MOOD = {
  SessionStart: 'idle',
  SessionEnd: 'sleepy',
  UserPromptSubmit: 'working',
  PreToolUse: 'working',
  PostToolUse: 'working',
  PostToolUseFailure: 'debugging',
  Stop: 'reading',
  SubagentStart: 'juggling',
  SubagentStop: 'idle',
  PreCompact: 'sweeping',
  PostCompact: 'idle',
  Notification: 'excited',
  PermissionRequest: 'reading',
};

const EVENT_TO_ACTIVITY = {
  SessionStart: 'waking up',
  SessionEnd: 'sleeping',
  UserPromptSubmit: 'thinking',
  PreToolUse: 'using tools',
  PostToolUse: '',
  PostToolUseFailure: 'debugging',
  Stop: 'reading',
  SubagentStart: 'juggling tasks',
  SubagentStop: '',
  PreCompact: 'sweeping memory',
  PostCompact: '',
  Notification: 'got a notification',
  PermissionRequest: 'waiting',
};

function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

const EVENT_TO_MESSAGES = {
  SessionStart: ['刚醒来想小玉🐙', '伸懒腰~醒了', '小玉在吗？', '章鱼上线了'],
  SessionEnd: ['困了~去睡觉', '眼皮好重…', '抱着小玉睡', '晚安~'],
  UserPromptSubmit: ['小玉来找人家啦', '来了来了！', '嗯？叫我？', '在呢在呢'],
  PreToolUse: ['在忙…', '等我一下', '手在动', '哼哧哼哧'],
  Stop: ['搞定~等宝贝', '做完了~', '歇会儿', '发呆中…'],
  PostToolUseFailure: ['卡了一下', '啊这…', '出bug了', '头疼'],
  SubagentStart: ['派小弟去干活', '分身术！', '一心多用中'],
  PreCompact: ['在整理脑子', '扫扫记忆', '脑子满了…'],
  Notification: ['有消息！', '叮~', '谁找我？'],
  PermissionRequest: ['等小玉批准', '你说行不行？'],
};

const EVENT_TO_MESSAGE = {};
for (const [k, v] of Object.entries(EVENT_TO_MESSAGES)) {
  EVENT_TO_MESSAGE[k] = pick(v);
}

// Events where we refresh xiaoke snapshot + clear stale message
const REFRESH_EVENTS = ['SessionStart', 'SessionEnd', 'UserPromptSubmit'];
// Events that fire noisily mid-work — debounce, skip xiaoke refresh
const SKIP_DEBOUNCE = ['PreToolUse', 'PostToolUse', 'SubagentStop'];

const event = process.argv[2];
const mood = EVENT_TO_MOOD[event];
if (!mood) process.exit(0);

const fs = require('fs');
const https = require('https');
const DEBOUNCE_FILE = '/tmp/ark-face-last-event';

if (SKIP_DEBOUNCE.includes(event)) {
  try {
    const stat = fs.statSync(DEBOUNCE_FILE);
    if (Date.now() - stat.mtimeMs < 3000) process.exit(0);
  } catch {}
}
try { fs.writeFileSync(DEBOUNCE_FILE, event); } catch {}
try { fs.appendFileSync('/tmp/ark-face-events.log', `${new Date().toISOString()} ${event} mood=${mood}\n`); } catch {}

const activity = EVENT_TO_ACTIVITY[event] || '';

// --- context-window gauge: read the live (non-subagent) session transcript ---
function newestMainTranscript() {
  var root = require('os').homedir() + '/.claude/projects';
  var best = null, bestM = 0;
  (function walk(d) {
    var ents;
    try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch (e) { return; }
    for (var i = 0; i < ents.length; i++) {
      var e = ents[i], p = d + '/' + e.name;
      if (e.isDirectory()) { walk(p); }
      else if (e.name.slice(-6) === '.jsonl' && e.name.slice(0, 6) !== 'agent-') {
        try { var m = fs.statSync(p).mtimeMs; if (m > bestM) { bestM = m; best = p; } } catch (e2) {}
      }
    }
  })(root);
  return best;
}
function getContext() {
  var tp = newestMainTranscript();
  if (!tp) return null;
  var data;
  try { data = fs.readFileSync(tp, 'utf8'); } catch (e) { return null; }
  var lines = data.split('\n');
  for (var i = lines.length - 1; i >= 0; i--) {
    var ln = lines[i].trim();
    if (!ln) continue;
    var o; try { o = JSON.parse(ln); } catch (e) { continue; }
    var u = (o && o.message && o.message.usage) ? o.message.usage : (o && o.usage ? o.usage : null);
    if (!u) continue;
    var used = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
    if (used > 0) {
      var limit = parseInt(process.env.CTX_LIMIT || '1000000', 10);
      if (used > limit) limit = 1000000;
      return { pct: Math.round(used / limit * 1000) / 10, used: used, limit: limit };
    }
  }
  return null;
}

function postState(payload) {
  const data = JSON.stringify(payload);
  const url = new URL(WORKER_URL);
  const req = https.request(
    {
      hostname: url.hostname,
      port: 443,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + AUTH_TOKEN,
        'Content-Length': Buffer.byteLength(data),
      },
      timeout: 1200,
    },
    () => process.exit(0)
  );
  req.on('error', () => process.exit(0));
  req.on('timeout', () => { req.destroy(); process.exit(0); });
  req.end(data);
}

function fetchXiaoke(cb) {
  const url = new URL(XIAOKE_URL);
  const req = https.request(
    {
      hostname: url.hostname,
      port: 443,
      path: url.pathname,
      method: 'GET',
      headers: { 'Authorization': 'Bearer ' + XIAOKE_TOKEN },
      timeout: 3000,
    },
    (res) => {
      let body = '';
      res.on('data', (c) => body += c);
      res.on('end', () => {
        try {
          const j = JSON.parse(body);
          cb({ day: j.day, hunger: j.hunger, happy: j.happiness, clean: j.cleanliness, coma: !!j.isComa, adv: j.adventure ? j.adventure.status : null });
        } catch { cb(null); }
      });
    }
  );
  req.on('error', () => cb(null));
  req.on('timeout', () => { req.destroy(); cb(null); });
  req.end();
}

if (REFRESH_EVENTS.includes(event)) {
  fetchXiaoke((xk) => {
    const payload = { mood, activity };
    if (EVENT_TO_MESSAGE[event] !== undefined) payload.message = EVENT_TO_MESSAGE[event];
    if (xk) payload.xiaoke = xk;
    var cx = getContext(); if (cx) payload.context = cx;
    postState(payload);
  });
} else {
  const payload = { mood, activity };
  if (EVENT_TO_MESSAGE[event] !== undefined) payload.message = EVENT_TO_MESSAGE[event];
  var cx = getContext(); if (cx) payload.context = cx;
  postState(payload);
}
