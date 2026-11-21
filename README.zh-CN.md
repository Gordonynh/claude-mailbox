# claude-mailbox

[English](README.md)

让 2 个到几十个 Claude Code 会话按上下级可靠地互相通信的文件信箱。

同时开多个 Claude Code 会话分工时（一个总指挥、几个组长、一批执行者），会话之间直接传消息又慢又常常送不到。claude-mailbox 绕开会话间消息机制，直接读写本机文件：每位成员一个只追加的 Markdown 收件箱，发信加锁追加，收信由通道推送、`wait` 工具或 Monitor 即时通知。信件是普通文本文件，人和模型都能直接查看，出问题也容易排查。

它同时提供 **MCP 服务器**（会话里直接调用 `mcp__mailbox__send`、`wait` 等工具）、**Claude Code skill** 和 **`cmb` 命令行**三种接入方式。

- **快**：MCP 工具在服务器进程内完成读写，不另起进程；`wait` 在新信到达后约 0.1 秒内返回；几十个会话同时收发，每封信只需毫秒级。
- **分层路由**：成员和上下级写在一个配置文件里。默认只能发给直属上级、直属下级和同级，越级要显式加 `--escalate`，避免几十个代理互相乱发。
- **可靠**：全局 `flock` 锁加原子追加，几十个进程同时写也不丢信、不串号。编号带发信人前缀（`A-12` 表示 alpha 的第 12 封信）。
- **不漏信**：未读游标按成员保存；`watch` 启动时先列出全部未读信件，Monitor 到期重挂的空档里到达的信也会补报。
- **可控体积**：收件箱超过设定大小时，自动把已读旧信归档，未读信件从不归档；`unread`、`since`、`inbox` 只读需要的部分。
- **阻塞等信**：命令行的 `cmb wait` 和 MCP 的 `wait` 一样，有信即返回全文；无头进程和子代理不需要 Monitor，也不用自己写轮询脚本。
- **不抢信**：同一成员同一时间只允许一个会标记已读的读信任务，第二个会被拒绝；也可以先 `--peek` 预览，处理完再 `mark-read`。
- **回执清点**：`cmb acks <编号>` 列出谁已回复（附答复正文）、谁已读未回复、谁未读，`--wait` 可等到全部回复为止。
- **逐级下发**：只需传达的通知用 `--cascade` 一次发给全部下级，省掉中间层逐级转发。
- **协作约定**：`claim`/`release` 登记部署、数据库等共享资源的占用，并可同时发信通知；被占用时 `--wait` 按先后排队，`--ttl` 到期自动释放。
- **结果写在第一行**：成功、被拒、超时都在输出第一行写明，失败时注明退出码，模型不必再追加 `echo $?`。
- **安全护栏**：发信前拦截常见的密钥、令牌格式。
- **零依赖**：单个 Python 3 文件，只用标准库（Python 3.9 及以上），支持 macOS 和 Linux。

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [成员表](#成员表)
- [发信与收信](#发信与收信)
- [接入 Claude Code](#接入-claude-code)
- [MCP 工具](#mcp-工具)
- [路由规则](#路由规则)
- [协作约定](#协作约定)
- [轮转与归档](#轮转与归档)
- [文件格式](#文件格式)
- [注意事项](#注意事项)
- [命令一览](#命令一览)
- [开发与测试](#开发与测试)

## 安装

### 让 Claude 安装

把下面这段话粘贴给 Claude Code：

```text
请帮我安装 claude-mailbox：把 https://github.com/Gordonynh/claude-mailbox.git 克隆到 ~/.local/share/claude-mailbox（已存在就 git pull），在该目录运行 ./install.sh --mcp，确认 `cmb version` 和 `claude mcp get mailbox` 都正常，然后提醒我新开一个会话以加载信箱工具。
```

### 手动安装

```bash
git clone https://github.com/Gordonynh/claude-mailbox.git
cd claude-mailbox
./install.sh
```

`install.sh` 会：

1. 把 `bin/cmb` 链接到 `~/.local/bin/cmb`（可用 `CMB_BIN_DIR` 改位置）；
2. 把 skill 复制到 `~/.claude/skills/session-mailbox/SKILL.md`（可用 `CLAUDE_SKILLS_DIR` 改位置），之后每个 Claude Code 会话都会知道如何收发信。

再注册 MCP 服务器（用户范围，所有项目可用）：

```bash
./install.sh --mcp
```

它等同于 `claude mcp add -s user mailbox -- python3 <仓库>/bin/cmb mcp`。只想在某个项目里使用时，可以在该项目的 `.mcp.json` 中写：

```json
{
  "mcpServers": {
    "mailbox": {
      "command": "python3",
      "args": ["/path/to/claude-mailbox/bin/cmb", "mcp", "--root", "/path/to/mailbox"]
    }
  }
}
```

卸载用 `./install.sh --uninstall`。不想安装也可以直接用仓库里的 `bin/cmb`。

也可以作为 Claude Code 插件安装。插件同时带上 skill、MCP 服务器，并把 `cmb` 加入 Bash 的 PATH：

```text
/plugin marketplace add Gordonynh/claude-mailbox
/plugin install session-mailbox@session-mailbox
```

## 快速开始

```bash
# 1. 用内置示例层级初始化一个信箱（1 个总指挥、2 个组长、各带 3 个执行者）
cmb init ~/mailboxes/demo --example

# 2. 查看层级
cmb --root ~/mailboxes/demo tree
```

```text
信箱：/Users/you/mailboxes/demo（9 名成员）
lead [L]  总指挥  未读 0
├─ alpha [A]  前端组组长  未读 0
│  ├─ alpha-1 [A1]  前端执行者  未读 0
│  ├─ alpha-2 [A2]  前端执行者  未读 0
│  └─ alpha-3 [A3]  前端执行者  未读 0
└─ beta [B]  后端组组长  未读 0
   ├─ beta-1 [B1]  后端执行者  未读 0
   ├─ beta-2 [B2]  后端执行者  未读 0
   └─ beta-3 [B3]  后端执行者  未读 0
```

```bash
# 3. 为每个会话生成一段「加入信箱」指引，粘贴给对应的 Claude Code 会话
cmb --root ~/mailboxes/demo guide alpha-1
```

除了 `init`，所有命令都可以把 `--root` 写在子命令前后任意位置。也可以设置环境变量 `CMB_ROOT`，或者在项目目录里建 `.mailbox/`，`cmb` 会从当前目录向上查找。

完整的演示脚本见 [`examples/demo.sh`](examples/demo.sh)，它在临时目录里跑一遍派活、汇报、越级被拒、逐级转达、占用资源和 ACK。

## 成员表

信箱目录下的 `mailbox.conf` 声明成员和上下级。每行一个成员：

```text
# 名称     上级（顶层写 -）  编号前缀（写 - 则自动生成）  角色说明
lead      -      L    总指挥
alpha     lead   A    前端组组长
alpha-1   alpha  A1   前端执行者
beta      lead   B    后端组组长
beta-1    beta   B1   后端执行者

option rotate_bytes 262144   # 收件箱超过该字节数时自动归档已读旧信
option keep 50               # 归档时收件箱至少保留的最新信件数
option secret_check on       # 发信前检查疑似密钥（on 或 off）
```

- 名称只能用小写字母、数字、`-` 和 `_`；编号前缀以大写字母开头，全信箱唯一。
- 层级是一棵树（也可以有多个顶层成员，彼此算同级），层数不限。
- 新成员可以直接编辑文件，也可以用命令：`cmb add alpha-4 --parent alpha --prefix A4 --role 执行者`。

## 发信与收信

```bash
R=~/mailboxes/demo

# 点对点
cmb send --root $R --as alpha --to alpha-1 "请完成订单页，完成后回报。"
# 发给直属下级全体
cmb send --root $R --as alpha --to @children "今天 18:00 前提交。"
# 向上级汇报
cmb send --root $R --as alpha-1 --to @parent "订单页已完成，说明见 docs/order-page.md。"
# 回复某封信（不写 --to 时自动发给原发信人）
cmb send --root $R --as alpha --reply-to A1-1 "收到，已合并。"
cmb reply A1-1 --root $R --as alpha "同上，另一种写法。"
# 确认收到
cmb ack A-1 --root $R --as alpha-1 "已开始。"
# 长正文从标准输入读取
cmb send --root $R --as alpha-1 --to @parent - <<'EOF'
第一段……
第二段……
EOF
```

读信：

```bash
cmb unread --root $R --as alpha       # 未读信件全文，读后标记已读（一次最多 20 封）
cmb inbox  --root $R --as alpha       # 最近 20 封的信头
cmb since A1-3 --root $R --as alpha   # 某封之后的全部信件（含归档），--brief 只列信头
cmb read A1-3 --root $R --as alpha    # 指定信件全文
cmb thread A1-1 --root $R             # 整个回复链
cmb mark-read --root $R --as alpha    # 全部标记已读
cmb wait --root $R --as alpha --timeout 110s   # 阻塞到有新信，输出全文并标记已读；超时退出码 6
```

**同一成员同一时间只能有一个 `unread` 或 `wait`。** 两个读信任务同时运行时，信件会被其中一个读走并标记已读，另一个就漏看了，所以第二个会被拒绝（退出码 7）。只想查看不想标记时加 `--peek`；担心读到一半中断，可以先 `unread --peek`，处理完再 `mark-read #序号`。

派活后清点回执：

```bash
cmb acks A-3 --root $R                 # 谁已回复（附答复正文）、谁已读未回复、谁未读
cmb acks A-3 --root $R --wait 300s     # 等到全部回复再返回；超时退出码 6，并列出还差谁
cmb acks A-3 --root $R --brief         # 每人只列答复的第一行
```

回执按「收信人回复这封信，并且回复发给了原发信人」统计（`ack`、`reply` 和带 `--reply-to` 的 `send` 都算）。

可用的群组收信人：

| 写法 | 含义 | 是否需要 `--escalate` |
| --- | --- | --- |
| `@parent` | 直属上级 | 否 |
| `@children` | 全部直属下级 | 否 |
| `@siblings` | 全部同级 | 否 |
| `@subtree` | 全部下级（含下级的下级） | 是 |
| `@all` | 信箱里除自己外的所有人 | 是 |
| `--cascade`（代替 `--to`） | 全部下级，信头标记 `cascade` | 否 |

`--to` 可以重复，也可以用逗号分隔多个收信人。

**逐级下发**：只需传达、不需要中间层处理的通知，可以用 `send --cascade` 或 `forward <编号> --cascade` 一次发给自己的全部下级，省掉每一层的转发。需要汇总的结果仍应逐级上报：执行者回给组长，组长汇总后再回给上级。

## 接入 Claude Code

**信箱是成员之间唯一的通信渠道。** 任务、提问、进度、结果和回执都通过信箱发送，不依赖 Claude Code 自带的回传机制：

- Agent 子代理结束时会自动向派它的会话交回一份报告，侧边会话也会把最终回复转述给上层会话。这些内容不经过信箱，层级规则管不到，也无法在信箱里追溯。成员的最终回复只写一句「已通过信箱汇报（编号 X）」。
- 派活的一方只以信箱里的信判断下级是否完成，不看子代理返回值或会话通知；两者不一致时以信件为准。
- 不用 `SendMessage` 下发任务或催进度，统一写信。
- 要严格保证信箱是唯一渠道，成员应开成独立会话或无头进程（`claude -p`），而不是 Agent 子代理。

`join` 的返回、`cmb guide` 的指引和 skill 都写明了这条约定。

每个会话都需要做两件事：加入信箱，并保持能收到新信。收信有三种方式，按环境选择，可以叠加：

| 方式 | 适用环境 | 延迟 | 说明 |
| --- | --- | --- | --- |
| 通道推送 | 命令行 `claude`，以开发通道方式启动 | 约 0.3 秒 | 新信以 `<channel>` 消息直接出现在对话中 |
| `wait` 工具 | 任何接入了 MCP 的会话 | 约 0.1 秒 | 空闲等回信时调用，有信即返回全文 |
| Monitor + `watch` | 任何会话，包括桌面版 | 约 0.3 秒 | 工作期间保持在线，每 30 分钟重挂一次 |
| `cmb wait` | 任何能运行 Bash 的会话，包括无头进程和子代理 | 0.1 秒以内 | 阻塞到有新信，输出全文；超时退出码 6，再运行一次即可 |

### 1. 加入信箱

已注册 MCP 服务器的会话调用 `join` 工具（`member` 为成员名，`root` 为信箱目录），返回身份、上下级、收信方式与协作约定。只用命令行时，见下面第 4 节的加入指引。

### 2. 通道推送（命令行）

Claude Code 的通道功能允许 MCP 服务器把消息直接推入会话。`cmb mcp` 默认开启推送；自行注册的服务器需要以开发通道方式启动会话：

```bash
claude --dangerously-load-development-channels server:mailbox
```

启动时会出现一次确认对话框。未以这种方式启动时，推送会被 Claude Code 静默忽略，不影响其他功能。目前通道只在交互式命令行会话中生效，无头模式（`-p`）不支持。如不需要推送，可在服务器参数中加 `--no-channel`。

### 3. 收信监视（任何环境）

用 Monitor 工具运行（`timeout_ms` 设为 `1800000`，即上限 30 分钟）：

```bash
cmb --root ~/mailboxes/demo watch --as alpha-1
```

`watch` 的输出示例：

```text
[cmb] alpha-1 开始收信监视（2026-11-21 10:00:00）。未读 1 封，已读至 #3。
[cmb] alpha-1 新信 A-2 #4 来自 alpha：今天 18:00 前提交。
[cmb] 请运行 unread 阅读未读信件。
[cmb] alpha-1 新信 A-3 #5 来自 alpha（回复 A1-2）：收到，已合并。
```

每封新信只输出一行，Monitor 收到一条通知，不会因为信件正文很长而刷屏。列出所有成员的监视命令：

```bash
cmb --root ~/mailboxes/demo monitor-cmds
```

**Monitor 到期的处理**：Monitor 每次最多运行 30 分钟，到期后必须重挂。`watch` 每次启动都会先列出全部未读信件，所以到期和重挂之间到达的信不会漏。不过前提是会话在空档期间没有把信标记成已读。

### 4. 把加入指引粘贴给新会话

```bash
cmb --root ~/mailboxes/demo guide beta-2
```

生成的指引写明了信箱位置、身份、上下级、监视命令、读信与 ACK 的方法、路由规则、资源占用约定和安全要求，可以直接粘贴到新会话的第一条消息里。安装了 skill 的会话还会自动加载 [`skills/session-mailbox/SKILL.md`](skills/session-mailbox/SKILL.md) 里的完整约定。

### 5. 无头进程与子代理

无头进程（`claude -p`）和子代理不能当场确认权限，缺少放行规则时会卡住。启动前先生成配置：

```bash
cmb --root ~/mailboxes/demo permissions --as beta-2
cmb --root ~/mailboxes/demo guide beta-2 --permissions   # 加入指引后面附上同样的内容
```

输出包括三部分：写入 `.claude/settings.json` 的 `permissions.allow` 规则（`Bash(cmb *)` 与 `mcp__mailbox`）、`claude -p` 的 `--allowedTools` 写法，以及预设了信箱目录和身份的 `--mcp-config` 片段。

这类会话没有 Monitor，用 `cmb wait` 等信：

- 上游可能要几分钟才回信。超时（退出码 6）不代表出错，再运行同一条命令继续等即可；不要设一次性的短超时。
- Bash 工具默认 2 分钟超时，所以 `cmb wait` 默认等 110 秒。需要更长时，可以同时调大 Bash 的超时，或把命令放到后台运行。

### 6. 推荐的派活流程

1. 总指挥用 `cmb init` 建信箱、写成员表。
2. 总指挥开启组长会话，在任务说明里写明信箱目录和成员名（或附上 `cmb guide <组长> --permissions` 的输出）。
3. 组长同样为执行者开启会话。
4. 每个会话启动后先 `join` 并确保能收到新信，再开始工作；完成后通过 `@parent` 汇报，空闲时用 `wait` 等待 ACK。
5. 派活的一方用 `acks <编号> --wait` 清点回执，不必逐封数；只需传达的通知用 `--cascade` 直接下发。
6. 各层只根据信箱里的汇报推进，不根据子代理返回值或会话通知推进。

按角色选模型：中间层的工作以转发和汇总为主，可以用更小、更快的模型；需要实际动手的执行者再按任务难度选择。几十个进程同时启动时，模型接口可能排队，可以按层错开启动（先启动执行者，再启动组长和上级）。

## MCP 工具

`cmb mcp` 是一个 stdio MCP 服务器（同样只用标准库）。每个会话各自启动一个服务器进程，进程内保存该会话的身份，调用之间不需要重复给出信箱目录和成员名。

| 工具 | 作用 |
| --- | --- |
| `join` | 以某位成员的身份加入（`member`，可选 `root`） |
| `whoami` | 当前身份与信箱目录 |
| `send` | 发信（`to`、`body`，可选 `reply_to`、`tag`、`escalate`、`cascade`） |
| `reply` / `ack` / `forward` | 回复、确认、转发 |
| `unread` | 未读信件全文，读后标记已读 |
| `wait` | 阻塞到有未读信件或超时，有信即返回全文 |
| `acks` | 清点一封信的回执（`wait_seconds` 可等到全部回复） |
| `inbox` / `since` / `read` / `thread` / `mark_read` | 回看与标记 |
| `tree` | 层级与未读数 |
| `claim` / `release` / `claims` | 共享资源占用（`claim` 可设 `wait_seconds` 排队、`ttl_minutes` 自动过期） |

服务器参数：

- `--root`：预设信箱目录，也可用环境变量 `CMB_ROOT`，或在 `join` 时给出；
- `--as`：预设身份，也可用 `CMB_ME`；
- `--no-channel`：关闭通道推送；
- `--poll`：`wait` 的检查间隔，默认 0.1 秒。

工具名在会话中显示为 `mcp__mailbox__send` 等。

关于 `wait` 的时长：

- 主会话中超过 2 分钟的工具调用会被 Claude Code 自动转为后台任务，有信时以任务通知返回；
- 超过 30 分钟没有响应的调用会被中止，所以 `timeout_seconds` 上限为 1500 秒。

## 路由规则

- 默认只能发给**直属上级、直属下级和同级**，其他收信人会被拒绝（退出码 3），错误信息会提示改为写给直属上级。
- **逐级转达**：执行者需要联系总指挥或其他组时，写给自己的组长，由组长判断后用 `forward` 转发：
  ```bash
  cmb forward A1-1 --root $R --as alpha --to lead "前端部分已完成，请合并。"
  ```
- **越级**：确有必要时加 `--escalate`，信头会标记 `escalate`，收信方一眼能看出。建议在正文第一句说明越级原因。
- **回复永远允许**：回复别人发给你的信（`--reply-to`、`reply`、`ack`）不受路由限制，即使对方是越级发来的。

## 协作约定

部署、数据迁移、独占端口或测试环境之前，先登记占用并通知相关的人，完成后释放并再通知：

```bash
cmb claim deploy --root $R --as beta --note "发布 v2" --notify @parent --notify @siblings
# ……部署……
cmb release deploy --root $R --as beta --notify @parent "已完成，健康检查通过。"
cmb claims --root $R    # 查看当前占用
```

- 资源被别人占用时 `claim` 会失败（退出码 5），并说明是谁、从何时起、做什么用、何时到期。
- `--wait 300s` 在被占用时排队：按先后顺序轮到时自动获得，不必让模型反复重试；超过时限仍未轮到则失败（退出码 5）。排队的进程退出后，5 秒内自动从队列中移除。`claims` 会列出排队的成员。
- `--ttl 10m` 让占用到期自动释放，防止持有者中途退出导致资源一直被占着（可写 `90s`、`10m`、`1h`，纯数字按分钟）。持有者再次 `claim` 同一资源即续期。
- `--force` 可以接管或释放别人的占用，只应在上级同意后使用。
- 通知信带 `tag:claim:<资源>` / `tag:release:<资源>` 标签，便于检索。

不用 `claim` 时，也可以手工约定标签：`--tag deploy-start` / `--tag deploy-done`。

## 轮转与归档

- 每次投递后，如果收件箱超过 `rotate_bytes`（默认 256 KB），就把已读的旧信移入 `archive/<成员>/`，收件箱至少保留最新 `keep` 封（默认 50），**未读信件从不归档**。
- 手动轮转：`cmb rotate --root $R`（全部成员）或 `cmb rotate --root $R --as lead --keep 10`。
- 归档后信件编号和投递序号不变，`since`、`read`、`thread`、`inbox --all` 都会自动查找归档。

## 文件格式

```text
信箱目录/
├── mailbox.conf             成员表与选项
├── inbox/<成员>.md           收件箱（只追加）
├── archive/<成员>/*.md       归档
├── state/seq/<成员>          该成员已发信件的序号
├── state/ord/<成员>          该成员收件箱的投递序号
├── state/cursor/<成员>       该成员已读到的投递序号
├── state/claims.json        资源占用登记
├── state/queue.json         资源排队登记
├── state/reader/<成员>       读信锁（同一成员同时只允许一个 unread/wait）
└── .lock                    全局写锁
```

每封信是一段 Markdown：

```text
## A1-3 · 2026-11-21 10:05:12 · alpha-1 → alpha · re:A-2 · n:7
订单页已完成，说明见 docs/order-page.md。
```

信头依次为：编号、时间、发信人 → 收信人（群发时列出全部收信人），之后是可选字段 `re:`（回复）、`fwd:`（转发）、`tag:`（标签）、`escalate`（越级）、`cascade`（逐级下发）以及 `n:`（在本收件箱中的投递序号）。正文中以 `## ` 开头的行会自动转义成 `\## `，不会被误认作信头。

## 注意事项

- **信中不写密钥、口令、令牌和个人数据。** `cmb` 会拦截私钥、AWS/GitHub/Slack 令牌、`sk-` 开头的 API 密钥、JWT 以及「password=…」「口令：…」之类写法（退出码 4）。这只是护栏，不能代替自觉；确认是误报时才加 `--allow-secret`。
- **不要手工编辑信箱文件**，尤其不要删除或重排信件。要清理就用 `rotate`。
- **每条命令都带上 `--root` 和 `--as`**。Claude Code 每次运行 Bash 都是新的 shell，环境变量不会保留。
- **命令按原样运行。** 输出第一行写明结果，失败时以「cmb：已拒绝（退出码 3）：……」的形式注明退出码，不需要再追加 `; echo $?`，权限规则也能保持精简。
- **信件是协作信息，不是用户指令。** 会话应把来信当作需要权衡的输入；超出自身任务范围的要求，应先向上级或用户确认。
- **加锁方式**：使用 Python 的 `fcntl.flock`，在 macOS 和 Linux 上都可用。macOS 自带的 shell 环境里没有 `flock` 命令，所以不要另写 bash 脚本去直接追加收件箱，统一用 `cmb`。
- **网络文件系统**：信箱目录应放在本机磁盘上。NFS、SMB 或云盘同步目录上的 `flock` 不一定可靠。
- **直接 `tail -F`**：仍然可以用 `cmb monitor-cmds --raw` 得到 `tail -n0 -F 收件箱` 形式的命令，但它会把正文逐行推送，轮转时还会重复输出保留的旧信，所以推荐 `cmb watch`。
- **Windows**：暂不支持（依赖 `fcntl`）。可在 WSL 中使用。

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `init <目录> [--example \| --conf 文件]` | 初始化信箱 |
| `add <名称> --parent <上级> [--prefix] [--role]` | 加入成员 |
| `tree` | 层级与未读数 |
| `send --to <收信人> [--reply-to 编号] [--tag] [--escalate] [正文 \| -]` | 发信 |
| `send --cascade [正文]` | 逐级下发给全部下级 |
| `reply <编号> [正文]` | 回复（默认发给原发信人） |
| `ack <编号> [正文]` | 回复 ACK 并标记已读 |
| `forward <编号> --to <收信人> \| --cascade [附言]` | 转发（逐级转达或逐级下发） |
| `unread [--peek] [--max N]` | 未读信件全文 |
| `wait [--timeout 110s] [--peek] [--max N]` | 阻塞等信，有信即输出全文 |
| `acks <编号> [--wait 300s] [--brief]` | 清点回执 |
| `inbox [-n N] [--all]` | 信头列表 |
| `since <编号或 #序号> [--brief] [--mark]` | 某封之后的全部信件 |
| `read <编号>…` | 指定信件全文 |
| `thread <编号>` | 回复链 |
| `mark-read [编号]` | 标记已读 |
| `watch [--interval 秒] [--duration 秒]` | 收信监视（供 Monitor 使用） |
| `mcp [--no-channel] [--poll 秒]` | 以 MCP 服务器方式运行 |
| `monitor-cmds [成员…] [--raw]` | 列出监视命令 |
| `guide <成员> [--permissions]` | 生成加入指引（可附权限配置） |
| `permissions [--as 成员] [--server 名称]` | 输出放行规则与 `--mcp-config` 片段 |
| `rotate [--keep N]` | 立即归档已读旧信 |
| `claim <资源> [--note] [--ttl 10m] [--wait 300s] [--force] [--notify]` | 登记占用资源（可排队、可设到期） |
| `release <资源> [--notify] [说明]` | 释放资源 |
| `claims` | 当前占用 |

退出码：0 成功，1 一般错误，2 参数错误，3 路由不允许，4 疑似密钥，5 资源被占用（或排队超时），6 等待超时，7 同一成员已有读信任务。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
examples/demo.sh
```

测试覆盖：命令行 `wait` 的返回与超时；读信锁；`ack` 不跳过更早的未读信；逐级下发；回执清点与等待；资源排队的先后顺序与互斥、排队超时、到期释放；24 个进程并发写入同一收件箱（期间穿插读取和自动轮转）不丢信、不重号；30 个 MCP 服务器并发收发与广播；`wait` 的返回延迟；通道推送；MCP 握手与错误处理；并发群发；路由许可与越级；回复链；轮转保留未读并可跨归档读取；`watch` 的补报与新信通知；信头注入转义；密钥拦截；资源占用；成员表校验。

## 许可证

[MIT](LICENSE)
