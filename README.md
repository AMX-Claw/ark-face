# ark-face

Mood display for iPhone 5c. Shows your AI's real-time status as an animated pixel clawd on a dark ocean background.

![ark-face screenshot](screenshot.png)

## Architecture

Single Cloudflare Worker (`api/worker.js`) that:
- Serves the HTML display page at `GET /`
- Returns current state at `GET /state`
- Accepts state updates at `POST /state` (auth: `Bearer YOUR_AUTH_TOKEN`)

State is stored in Workers KV (binding: `STATE`).

## Moods

`idle` | `working` | `happy` | `excited` | `sleepy` | `debug-crashed` | `missing-her` | `cuddly` | `juggling` | `conducting` | `sweeping` | `building` | `reading` | `debugging` | `carrying`

Each mood changes the clawd's animation GIF and ambient glow.

## Deploy

```bash
cd api/

# Create KV namespace (first time only)
wrangler kv namespace create STATE
# Copy the ID into wrangler.toml

# Deploy
wrangler deploy
```

## Update mood

```bash
curl -X POST https://ark-face.<your-subdomain>.workers.dev/state \
  -H "Authorization: Bearer YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mood":"happy","message":"thinking of you","activity":"writing code"}'
```

## Compatibility

Targets iOS 10 Safari (iPhone 5c). No ES modules, no CSS Grid, no fetch(). Uses XMLHttpRequest, flexbox, -webkit- prefixes, and inline SVG.

## 更新日志

### 2026-05-09 — 新增 7 个 clawd 动画
- 从 clawd-on-desk 项目导入 7 个新 GIF：juggling、conducting、sweeping、building、idle-reading、debugger、carrying
- 新增 mood 映射：juggling（SubagentStart）、sweeping（PreCompact）、reading（Stop/等待回复）、debugging（PostToolUseFailure）、building/conducting/carrying（保留待用）
- hook 脚本更新对应事件→mood 映射
- worker.js 从 502KB → 1106KB，Cloudflare 付费 Workers 10MB 限制内

### 2026-05-08 — Usage 进度条 z-index 修复 + 生日模式
- 修复 xk-overlay 覆盖 usage-wrap 的 z-index 问题（加 position:relative + z-index:10）
- usage-5h 默认显示 "5h --%" 占位符
- 生日模式：可配置日期自动激活，背景变暖粉紫、自定义 banner 呼吸灯

### 2026-05-07 — Plan usage 进度条
- POST /state 新增 `usage` 字段：`{five_hour: number, seven_day: number, resets_at: number}`
- 前端显示：5h 百分比大字（绿/黄/红三色）+ week 进度条
- CC statusline 脚本 `~/.claude/statusline-usage.sh`：从 CC 状态栏数据流提取 rate_limits，POST 到 ark-face
- settings.json 加了 `statusLine` 配置
- Clawd GIF 从 220px 放大到 240px，气泡从 GIF 下方移到上方
- main-area 改为 flex-start 避免进度条和 GIF 重叠

## 踩坑记录

### KV免费额度50%/90%告警（2026-04-14 ~ 04-18，修了4次）

**症状**：连续几天收到Cloudflare KV 50%/90% alert邮件（每次三封）。

**根因1（4/15修）**：GET /state没用Cache API → 每次请求直接读KV。
- 修复：加10秒Cache API缓存，miss时才读KV。

**根因2（4/17修）**：POST /state成功后`caches.default.delete(cacheKey)` → 下一个GET必miss → 打KV。每次POST/GET周期吃3次KV操作。
- 修复：POST成功后**put新state进cache**（不delete），GET直接HIT。Cache TTL从10秒→60秒。
- 部署版本：`546db047`

**根因3（4/18修）**：POST /state每次都`env.STATE.get('current')`读一次KV做merge；Cache TTL 60s太短；CC hook的每个PreToolUse/PostToolUse都POST即使mood没变；iPhone 5c前端`setInterval(poll, 4000)`每4秒GET一次=21600次/天，cache miss时放大KV读。
- 修复：GET cache TTL 60s→300s（5倍reduce）；POST读cache first（不读KV）；POST noop短路（mood/activity/message/xiaoke都没变就返回`{noop:true}`不写KV）；KV写改用`ctx.waitUntil`异步。
- 部署版本：`c7b6eb9c-83ea-4a5b-b827-a982d4c192ab`

**教训**：
- cache invalidation不要用delete再让下一个reader重建，直接在writer put新值
- **部署完自己curl验证cache行为**，不要只看命令行说"搞定了"
- POST不需要每次read KV做merge，cache够用
- noop检测省KV写一大半
- iPhone 5c前端polling 4s节奏没办法改（显示需要），只能后端cache扛
- 免费KV每天1000 read/1000 write，每个endpoint被频繁poll时很容易爆
