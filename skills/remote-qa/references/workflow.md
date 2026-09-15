# Execution reference / 执行参考

## Host requirements

This package follows Agent Skills format; its current adapter targets Codex desktop. It requires Gmail get_profile/send_email/search_emails/read_email, read_thread plus project metadata, a nonblocking user-input surface, and Python 3.10+. Durable idle polling additionally needs a same-thread heartbeat scheduler. The Python helper does not supply these integrations. Use equivalent adapters on other hosts only after verifying their semantics; otherwise report the missing capability.

Obtain the actual current thread ID from host context or CODEX_THREAD_ID and verify it with read_thread. Never select the most recently active thread as a substitute. Resolve project association with project metadata; an explicit projectless context maps to 无项目.

## First use

There is no shipping recipient default. Ask on screen if the user has not specified or confirmed a remote-QA recipient in this thread. A historical code constant or another thread is not consent. Verify the sending account through get_profile. Store configuration only after the user provides the recipient; passing command flags is not itself proof of user consent.

Use the following with the verified Python executable, script path and thread UUID. Addresses below are documentation examples only, never operational defaults.

```text
PYTHON SCRIPT --thread THREAD status
PYTHON SCRIPT --thread THREAD enable --recipient user@example.com --sender-account sender@example.com
PYTHON SCRIPT --thread THREAD enable
PYTHON SCRIPT --thread THREAD create --input question.json
PYTHON SCRIPT --thread THREAD mail --qid RQA-... --state sending
PYTHON SCRIPT --thread THREAD render --qid RQA-...
PYTHON SCRIPT --thread THREAD mail --qid RQA-... --state sent --message-id GMAIL_ID --gmail-thread-id GMAIL_THREAD_ID
PYTHON SCRIPT --thread THREAD claim --qid RQA-... --input answer.json
PYTHON SCRIPT --thread THREAD automation --id AUTOMATION_ID
PYTHON SCRIPT --thread THREAD disable
```

The second enable form reuses this thread's saved configuration. Initial enable without a recipient and verified account fails. disable cancels pending questions but retains configuration. get and cancel accept --qid. Legacy records remain readable with get, but missing metadata is never invented for sending.

## Files and device identity

Write UTF-8 JSON in a scratch/work directory rather than interpolating user text into shell code:

```json
{"project_name":"无项目","thread_title":"Verified current title","context":"Necessary context","question":"Question text","options":["Option one","Option two"]}
```

Question creation snapshots recipient and sender account. Immediately before sending, mail sending captures platform.node(), platform.system() and the local time offset on the actual executing host. Render AFTER this step. Device name means the host initiating the request, not Google's mail server, a serial number, or a guessed client device. No IP or hardware identifier is collected.

render returns to/subject/body. Pass these as structured tool arguments:

```text
send_email({to, subject, payload:{mime_type:"text/plain",charset:"UTF-8",body:{content:body}}})
```

Confirm the connector account matches the question's sender_account. Do not impersonate an address via from_address. An uncertain send transitions to uncertain and is reconciled using `in:sent to:RECIPIENT subject:QUESTION_ID`, then full-message inspection. Do not retry blindly, including after a crash with mail_state=sending.

## Answers

```json
{"source":"email","answer":"A","evidence_id":"Gmail message ID","sender":"user@example.com"}
```

Use source=screen and the user-message ID (or unique observation ID) for local input. The helper checks identity consistency, not email authentication: read and validate actual headers and new reply text before claim. Match against the question's recipient snapshot, not a global address. accepted=false never authorizes the losing answer.

Search `from:RECIPIENT subject:QUESTION_ID`, then read full messages. Preserve the distinction between Gmail thread ID and Codex thread ID. Exclude quoted history and automatic responses. Do not reorder accepted replies by email_ts.

## Polling and stopping

During active waiting, use an interruptible ~30-second wait between checks. Screen input can arrive as new user messages; claim matching answers promptly. After about two minutes, use an actual same-thread heartbeat if waiting must continue while this turn ends. Follow the available automation_update schema and retain its returned ID, preferring updates over duplicate creation. Do not write scheduler config files directly.

Suggested name: 离机问答｜CURRENT_TITLE. Cadence: every minute. Save a prompt with exact THREAD and DB values:

> Use $remote-qa for thread THREAD, database DB. Read status first. If mode is disabled or no question is pending, pause this monitor and stay quiet. Otherwise read the pending question's configured recipient and ID, search only for matching replies, validate the full email and atomically claim a valid answer. Ignore late email if a screen answer won. On success, report source and answer in the original thread and continue only the previously authorized task. Stay quiet while unchanged; notify only on an accepted answer, a failure or necessary user action. Never select a recommendation because of elapsed time. Do not create another conversation or bypass native approvals.

On resolution pause only this monitor, leaving mode enabled for subsequent questions. On explicit disable cancel pending questions and pause the recorded monitor. Preserve ownership checks: inspect the recorded automation before changing it. If scheduling is unavailable, preserve pending state and disclose that a user-triggered check is required. Local host/app/connectors must remain available; minute scheduling is not real-time delivery.
