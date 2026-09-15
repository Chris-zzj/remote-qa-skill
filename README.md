# remote-qa

Email-assisted questions for an active Codex conversation. Questions remain visible on screen and are mirrored through Gmail; the first validated answer recorded from either channel wins.

## What it does

- Asks for a recipient on first use unless the user already supplied one in the conversation. **No built-in recipient or sender account.**
- Reuses that configuration in the same conversation until changed. Resolving a question does not turn the mode off.
- Includes the initiating device name and OS, project (or 无项目), current conversation title and full ID, question ID, local time with UTC offset, context and answer options.
- Uses a SQLite transaction to prevent competing answers from overwriting each other.
- Keeps reply instructions separate from quoted email history and preserves native approval boundaries.

## Install

This repository uses the open [Agent Skills format](https://agentskills.io/specification). Install from GitHub using the [skills CLI](https://skills.sh/docs):

```sh
npx skills add Chris-zzj/remote-qa-skill --skill remote-qa
```

Alternatively, ask Codex's skill-installer to install the `skills/remote-qa` directory from this repository. For manual installation, copy that complete directory into the skill location supported by your host. Python code and references must stay alongside SKILL.md.

## Use

```text
Use $remote-qa for this conversation; send questions to user@example.com.
```

If the recipient is omitted on first use, the agent asks on screen before sending. Later invocations reuse this conversation's recipient. A new or forked conversation has no default. To stop, say `Disable remote QA for this conversation`.

中文示例：

```text
使用 $remote-qa 开启当前会话的离机问答，收件邮箱为我指定的邮箱。
关闭当前会话的离机模式。
```

实际使用时请给出真实邮箱；示例地址不是默认设置。首次未给出邮箱必须询问，确认后在本会话持续使用。邮件标明实际发起设备、项目、会话名称和 ID，以及本机时间。

## Requirements and limits

The package format is portable; **the current workflow adapter targets Codex desktop**, with Gmail connector access, current-thread/project metadata tools, asynchronous user input and Python 3.10+. The standard-library helper itself does not send mail or listen for messages. Other agents need equivalent adapters.

Active waiting checks approximately every 30 seconds. After around two minutes, an available same-thread heartbeat can continue at one-minute intervals. No scheduler is installed merely by installing this skill. Background behavior requires the app, host and connector to remain available; it is not a Gmail push subscription. If required tools are missing, the agent reports this instead of claiming to monitor.

“First” means first successfully validated and recorded, not the earliest send-button time. A recommendation is never selected merely because the user is silent. Original on-screen questions may remain visible after an email wins. Native permission dialogs cannot be approved through this workflow.

Device means the actual host initiating the Codex operation. Remote execution can therefore identify a different machine from the user's screen. No IP address or hardware serial is collected.

## Local data and upgrades

Runtime configuration and question history are stored under `$CODEX_HOME/remote-qa/state.sqlite3` (fallback `~/.codex/remote-qa/state.sqlite3`). They are not part of this repository and must not be published. Tests use isolated databases.

Existing records are preserved. Old configurations without an explicit per-conversation recipient are treated as unconfigured, never migrated from a previously hard-coded address. Resolve or explicitly cancel old pending questions before changing configuration.

## Development

```sh
python -m unittest discover -s tests -v
```

Tests cover first-use configuration, reuse, conversation isolation, device/time fields, uncertain sends, simultaneous answer claims, disabling and legacy-state handling. They do not send real email or exercise the host scheduler. Live connector and scheduler integration require a separately authorized interactive test.

## License

MIT. See [LICENSE](LICENSE).
