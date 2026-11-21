# claude-mailbox

[中文](README.md)

A file-based, hierarchical mailbox that lets anywhere from 2 to several dozen Claude Code sessions talk to each other quickly and reliably. It does not rely on Claude Code's cross-session messaging. It ships as an **MCP server**, a **Claude Code skill** and the **`cmb` command line**.

When you run many Claude Code sessions in parallel (one lead, a few group leads, a set of workers), direct cross-session messages are slow and often fail to arrive. claude-mailbox takes a simple approach. Each member has an append-only Markdown inbox, and the `cmb` command appends messages under a lock. Sessions receive mail through channel push, the `wait` tool, or a Monitor running `cmb watch`, so they learn about new mail as soon as it lands. Messages are plain text files that both people and models can inspect directly.

- **Fast.** MCP tools read and write in-process, without spawning anything. `wait` returns within about 0.1 s of a message arriving, and each delivery takes milliseconds, even with dozens of sessions.
- **Hierarchical routing.** You declare members and reporting lines in one config file. By default a member can only write to its direct parent, its direct children and its siblings. Skipping levels requires an explicit `--escalate`.
- **Reliable under concurrency.** A global `flock` plus single-write appends means dozens of concurrent writers neither lose messages nor duplicate IDs. Each ID carries the sender's prefix: `A-12` is alpha's 12th message.
- **No missed mail.** `watch` lists every unread message on startup, so mail that arrived while a Monitor was expired and not yet re-armed is still reported.
- **Bounded size.** When an inbox grows past a configured size, read messages are moved to an archive. Unread messages are never archived. The `unread`, `since` and `inbox` commands read only what they need.
- **Blocking wait on the command line.** `cmb wait` works like the MCP `wait` tool: it returns the full text as soon as mail arrives. Headless processes and subagents need neither a Monitor nor a hand-written polling script.
- **No stolen mail.** Only one reader that marks mail as read (`unread` or `wait`) may run per member at a time; a second one is refused. You can also `--peek` first and `mark-read` once you have handled the mail.
- **Acknowledgement tally.** `cmb acks <id>` lists who replied (with their replies), who read the message without replying, and who has not read it yet. `--wait` blocks until everyone has replied.
- **Cascade.** `--cascade` delivers a notice to every descendant in one step, so intermediate levels do not have to relay it.
- **Coordination.** `claim` and `release` record who holds a shared resource (a deploy, a staging database, a port) and can notify others at the same time. `--wait` queues in arrival order while the resource is held, and `--ttl` releases it automatically.
- **Results on the first line.** Success, refusal and timeout are stated on the first line of output, with the exit code on failure, so a model has no reason to append `echo $?`.
- **Secret guard.** Common key and token formats are rejected before sending.
- **Zero dependencies.** A single Python 3 file using only the standard library (Python 3.9+). It runs on macOS and Linux.

## Install

```bash
git clone https://github.com/Gordonynh/claude-mailbox.git
cd claude-mailbox
./install.sh          # links bin/cmb into ~/.local/bin and installs the skill into ~/.claude/skills
```

You can also install it as a Claude Code plugin (`/plugin marketplace add Gordonynh/claude-mailbox`, then `/plugin install session-mailbox@session-mailbox`). The plugin bundles the skill and the MCP server, and puts `cmb` on the Bash tool's PATH.

Register the MCP server for all projects:

```bash
./install.sh --mcp     # same as: claude mcp add -s user mailbox -- python3 <repo>/bin/cmb mcp
```

## Quick start

```bash
cmb init ~/mailboxes/demo --example        # 1 lead, 2 group leads, 3 workers each
cmb --root ~/mailboxes/demo tree
cmb --root ~/mailboxes/demo guide alpha-1  # paste the output into the alpha-1 session
```

`mailbox.conf`, one member per line:

```text
# name     parent  prefix  role
lead      -      L    Lead
alpha     lead   A    Frontend group lead
alpha-1   alpha  A1   Frontend worker
option rotate_bytes 262144
option keep 50
```

## Sending and reading

```bash
R=~/mailboxes/demo
cmb send --root $R --as alpha --to alpha-1 "Please build the order page."
cmb send --root $R --as alpha --to @children "Submit by 18:00."
cmb send --root $R --as alpha-1 --to @parent "Order page done."
cmb reply A1-1 --root $R --as alpha "Merged."     # goes to the original sender
cmb ack A-1 --root $R --as alpha-1 "Started."
cmb unread --root $R --as alpha                    # full text of unread mail, then marks read
cmb inbox  --root $R --as alpha                    # recent headers
cmb since A1-3 --root $R --as alpha                # everything after a message, archives included
cmb thread A1-1 --root $R
cmb wait   --root $R --as alpha --timeout 110s     # block until mail arrives; exit code 6 on timeout
cmb acks A-3 --root $R --wait 300s                 # tally replies; wait until everyone has replied
cmb send --root $R --as alpha --cascade "Freeze merges at 17:00."   # every descendant at once
```

Only one `unread` or `wait` may run per member at a time. If two readers ran at once, one would mark the mail as read and the other would miss it, so the second one is refused (exit code 7). Add `--peek` to look without marking, or run `unread --peek` and then `mark-read #<n>` once the mail is handled.

`acks` counts a reply when a recipient answers the message and the answer goes to the original sender (`ack`, `reply` and `send --reply-to` all count).

Group recipients: `@parent`, `@children` and `@siblings` are always allowed. `@subtree` and `@all` require `--escalate`. `--cascade` (instead of `--to`) reaches every descendant without `--escalate` and marks the header `cascade`; use it for notices that need no processing in between. Results should still be reported level by level.

## Claude Code integration

**The mailbox is the only channel between members.** Tasks, questions, progress, results and acknowledgements all go through the mailbox. Do not rely on Claude Code's built-in return paths:

- A subagent started with the Agent tool hands a final report back to the session that started it, and a side session relays its final reply upward. These bypass the mailbox, so routing rules do not apply and nothing can be traced in the mailbox. A member's final reply should only say "Reported via the mailbox (message X)".
- The dispatching side judges whether a member is done only from mailbox messages, not from subagent return values or session notifications. If they disagree, the message wins.
- Do not use `SendMessage` to assign work or chase progress. Write a message instead.
- To guarantee the mailbox is the only channel, run members as independent sessions or headless processes (`claude -p`) rather than Agent subagents.

The `join` result, the `cmb guide` brief and the skill all state this rule.

Arm a Monitor in each session (`timeout_ms: 1800000`):

```bash
cmb --root ~/mailboxes/demo watch --as alpha-1
```

Each new message produces exactly one line, and therefore one notification. A Monitor runs for at most 30 minutes, so re-arm it as soon as it expires. Because `watch` reports all unread mail on startup, nothing is lost in the gap. `cmb monitor-cmds` prints the command for every member. `cmb guide <member>` prints a ready-to-paste onboarding brief. The skill in [`skills/session-mailbox/SKILL.md`](skills/session-mailbox/SKILL.md) teaches sessions the full protocol: receiving mail, replying with ACK, re-arming the Monitor and catching up on missed mail.

### MCP tools

`cmb mcp` is a stdio MCP server built on the standard library only. Each session runs its own server process, which keeps that session's identity. Call `join` first with `member` and, optionally, `root`. Then use these tools:

- `send`, `reply`, `ack` and `forward` to write;
- `unread`, `inbox`, `since`, `read` and `thread` to read;
- `wait` to block until mail arrives, which then returns the full text;
- `tree`, plus `claim`, `release` and `claims` for shared resources.

There are three ways to receive mail, and you can combine them:

| Method | Where | Latency |
| --- | --- | --- |
| Channel push (`notifications/claude/channel`) | Interactive CLI started with `claude --dangerously-load-development-channels server:mailbox` | ~0.3 s |
| `wait` tool | Any session with the MCP server | ~0.1 s |
| Monitor + `cmb watch` | Any session, including the desktop app | ~0.3 s |
| `cmb wait` | Any session that can run Bash, including headless processes and subagents | under 0.1 s |

In the main session, tool calls longer than 2 minutes are moved to the background automatically. Calls with no response for 30 minutes are aborted, so `wait` is capped at 1500 s. Pass `--no-channel` to disable push. `acks` tallies replies (`wait_seconds` waits for everyone), `send` and `forward` accept `cascade`, and `claim` accepts `wait_seconds` and `ttl_minutes`.

### Headless processes and subagents

Headless processes (`claude -p`) and subagents cannot approve permissions on the spot, so they stall without allow rules. Generate the configuration before starting them:

```bash
cmb --root ~/mailboxes/demo permissions --as beta-2
cmb --root ~/mailboxes/demo guide beta-2 --permissions   # the brief followed by the same configuration
```

The output contains the `permissions.allow` rules for `.claude/settings.json` (`Bash(cmb *)` and `mcp__mailbox`), the equivalent `--allowedTools` flags for `claude -p`, and an `--mcp-config` snippet with the mailbox and identity preset.

These sessions have no Monitor, so they wait with `cmb wait`. Upstream members may take minutes to answer. A timeout (exit code 6) is not an error: run the same command again rather than using one short timeout. The Bash tool times out after 2 minutes by default, which is why `cmb wait` defaults to 110 s.

### Suggested workflow

1. The lead creates the mailbox with `cmb init` and writes the member table.
2. The lead starts group-lead sessions, giving each the mailbox path and member name (or the output of `cmb guide <member> --permissions`). Group leads start their workers the same way.
3. Every session joins first and makes sure it receives mail, then starts work and reports to `@parent` when done.
4. The dispatching side tallies replies with `acks <id> --wait` instead of counting messages, and sends plain notices with `--cascade`.
5. Every level acts only on mailbox messages, never on subagent return values or session notifications.

Pick models by role: intermediate levels mostly relay and summarise, so a smaller, faster model is usually enough. When dozens of processes start at once, model requests may queue; consider starting the levels in stages.

## Rules and conventions

- **Relay, don't skip levels.** A worker that needs the lead writes to its group lead. The group lead relays the message with `cmb forward <id> --to lead`. Replies to any message you received are always allowed.
- **Announce shared-resource use.** Claim the resource and notify before you start, then release it and notify when you finish:
  `cmb claim deploy --as beta --note "release v2" --notify @parent`, then `cmb release deploy --as beta --notify @parent "done"`.
  If the resource is held, `--wait 300s` queues in arrival order and takes it automatically when it is your turn; a queued process that exits drops out of the queue within 5 s. `--ttl 10m` releases the claim automatically (`90s`, `10m`, `1h`; a bare number means minutes), and claiming again as the holder renews it.
- **Run commands exactly as given.** The first line of output states the result, and failures read like `cmb：已拒绝（退出码 3）：…` with the exit code, so there is no need to append `; echo $?`.
- **Never put secrets or personal data in messages.** The built-in check is a guardrail, not a guarantee.
- **Do not edit mailbox files by hand.** Use `cmb rotate` to clean up.
- **Pass `--root` and `--as` on every command.** Each Bash call in Claude Code starts a fresh shell, so environment variables do not persist.
- **Keep the mailbox on a local disk.** `flock` may be unreliable on NFS, SMB or cloud-synced folders. Windows is not supported; use WSL.

Exit codes: 0 ok, 1 error, 2 usage, 3 routing denied, 4 suspected secret, 5 resource held by someone else (or queue timeout), 6 wait timeout, 7 another reader is already running for this member.

## Tests

```bash
python3 -m unittest discover -s tests -v
examples/demo.sh
```

## License

[MIT](LICENSE)
