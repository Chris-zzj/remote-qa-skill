"""Thread-scoped remote QA ledger. Standard library only; no network or listener."""
import argparse
import json
import os
import platform
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

def email_address(value):
    value = required(value, "email address")
    if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", value):
        raise ValueError("Provide one plain email address, without display names")
    local, domain = value.rsplit("@", 1)
    return local + "@" + domain.lower()


def now():
    return datetime.now(timezone.utc).isoformat()


def required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def load_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object")
    return value


def render(q):
    local_time = datetime.fromisoformat(q["created_local"])
    offset = local_time.strftime("%z")
    display_time = local_time.strftime("%Y-%m-%d %H:%M:%S") + f" (UTC{offset[:3]}:{offset[3:]})"
    options = "\n".join(f"{chr(65+i)}. {v}" for i, v in enumerate(q["options"]))
    body = (
        f"发起设备：{q['device_name']}（{q['device_os']}）\n收件邮箱：{q['recipient']}\n"
        f"项目：{q['project_name']}\n会话名称：{q['thread_title']}\n"
        f"会话 ID：{q['thread_id']}\n问题编号：{q['qid']}\n时间（本机时间）：{display_time}\n\n"
        f"上下文：\n{q['context']}\n\n问题：\n{q['question']}\n\n"
        f"预设答案：\n{options or '开放问题，请直接回复文字。'}\n\n"
        "请直接回复本邮件，保留主题，填写选项字母或自由文字。\n"
        "同一问题也显示在电脑会话中；先被确认的有效回复生效，另一渠道的迟到答案不再采纳。\n"
        "无人回复不会自动采用推荐选项。电脑和应用需要保持运行，邮件检查可能有延迟。\n"
    )
    title = " ".join(q["thread_title"].split())
    project = " ".join(q["project_name"].split())
    return {"to": q["recipient"], "subject": f"[离机问答][{project}][{title}][{q['qid']}]", "body": body}


def run(a):
    a.thread = str(uuid.UUID(a.thread))
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    db = Path(a.db) if a.db else root / "remote-qa" / "state.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db, timeout=15)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS modes (thread TEXT PRIMARY KEY, enabled INTEGER NOT NULL, automation_id TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS questions (qid TEXT PRIMARY KEY, thread TEXT NOT NULL, record TEXT NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS session_config (thread TEXT PRIMARY KEY, recipient TEXT NOT NULL, sender_account TEXT NOT NULL, confirmed_at TEXT NOT NULL)")
        config = conn.execute("SELECT recipient, sender_account, confirmed_at FROM session_config WHERE thread=?", (a.thread,)).fetchone()
        row = conn.execute("SELECT enabled, automation_id FROM modes WHERE thread=?", (a.thread,)).fetchone()
        enabled, automation_id = (bool(row[0]) and bool(config), row[1]) if row else (False, None)
        records = [json.loads(r[0]) for r in conn.execute("SELECT record FROM questions WHERE thread=? ORDER BY rowid", (a.thread,))]

        def save(q):
            conn.execute("INSERT OR REPLACE INTO questions VALUES(?,?,?)", (q["qid"], a.thread, json.dumps(q, ensure_ascii=False)))

        if a.command in ("enable", "disable"):
            enabled = a.command == "enable"
            if enabled:
                recipient = email_address(a.recipient) if a.recipient else (config[0] if config else None)
                sender = email_address(a.sender_account) if a.sender_account else (config[1] if config else None)
                if not recipient or not sender:
                    raise ValueError("First invocation: ask the user for a recipient and verify the connected sender account")
                if (not config or (recipient, sender) != config[:2]) and any(q["status"] == "pending" for q in records):
                    raise ValueError("Resolve or explicitly cancel pending questions before changing mail configuration")
                if not config or (recipient, sender) != config[:2]:
                    conn.execute("INSERT OR REPLACE INTO session_config VALUES(?,?,?,?)", (a.thread, recipient, sender, now()))
                config = conn.execute("SELECT recipient, sender_account, confirmed_at FROM session_config WHERE thread=?", (a.thread,)).fetchone()
            conn.execute("INSERT INTO modes VALUES(?,?,?) ON CONFLICT(thread) DO UPDATE SET enabled=excluded.enabled", (a.thread, int(enabled), automation_id))
            if not enabled:
                for q in records:
                    if q["status"] == "pending":
                        q.update(status="cancelled", closed_at=now())
                        save(q)
            return {"thread_id": a.thread, "enabled": enabled, "automation_id": automation_id, "recipient": config[0] if config else None, "sender_account": config[1] if config else None}
        if a.command == "status":
            return {"thread_id": a.thread, "enabled": enabled, "configured": bool(config), "recipient": config[0] if config else None, "sender_account": config[1] if config else None, "automation_id": automation_id, "pending": [q for q in records if q["status"] == "pending"]}
        if a.command == "automation":
            if not row:
                raise ValueError("Enable this thread before recording an automation")
            conn.execute("UPDATE modes SET automation_id=? WHERE thread=?", (a.id, a.thread))
            return {"automation_id": a.id}
        if a.command == "create":
            if not enabled:
                raise ValueError("Remote mode is disabled for this thread")
            if any(q["status"] == "pending" for q in records):
                raise ValueError("Resolve or cancel the existing pending question first")
            data = load_json(a.input)
            q = {k: required(data.get(k), k) for k in ("project_name", "thread_title", "context", "question")}
            options = data.get("options", [])
            if not isinstance(options, list) or len(options) > 26:
                raise ValueError("options must be a list with at most 26 entries")
            q.update(options=[required(v, "option") for v in options], qid="RQA-" + uuid.uuid4().hex,
                     thread_id=a.thread, created_at=now(), created_local=datetime.now().astimezone().isoformat(),
                     recipient=config[0], sender_account=config[1], device_name=required(platform.node(), "device name"),
                     device_os=platform.system(), status="pending", mail_state="prepared", winner=None)
            save(q)
            return q
        q = next((q for q in records if q["qid"] == a.qid), None)
        if q is None:
            raise ValueError("Question not found in this thread")
        if a.command == "get":
            return q
        if a.command == "render":
            if not all(k in q for k in ("recipient", "created_local", "device_name", "device_os")):
                raise ValueError("Legacy question lacks confirmed mail/device metadata; create a new question after configuration")
            return render(q)
        if a.command == "cancel":
            if q["status"] == "pending":
                q.update(status="cancelled", closed_at=now())
                save(q)
            return q
        if a.command == "mail":
            if a.state == "sending":
                if not enabled or q["status"] != "pending" or q["mail_state"] != "prepared":
                    raise ValueError("Cannot send: disabled, closed, or already attempted; reconcile Gmail first")
                q.update(device_name=required(platform.node(), "device name"), device_os=platform.system(),
                         created_local=datetime.fromisoformat(q["created_at"]).astimezone().isoformat())
            elif a.state == "sent":
                required(a.message_id, "message_id")
                required(a.gmail_thread_id, "gmail_thread_id")
                if q["mail_state"] not in ("sending", "uncertain", "sent"):
                    raise ValueError("Record sending before marking sent")
                if q.get("message_id") and q["message_id"] != a.message_id:
                    raise ValueError("Cannot replace a recorded sent message")
                q.update(message_id=a.message_id, gmail_thread_id=a.gmail_thread_id)
            elif q["mail_state"] not in ("sending", "uncertain"):
                raise ValueError("Only an in-flight send can become uncertain")
            q.update(mail_state=a.state, mail_updated_at=now())
            save(q)
            return q
        if a.command == "claim":
            data = load_json(a.input) if a.input else vars(a)
            source = data.get("source")
            answer = required(data.get("answer"), "answer")
            evidence = required(data.get("evidence_id"), "evidence_id")
            if source not in ("screen", "email"):
                raise ValueError("source must be screen or email")
            if source == "email" and (email_address(data.get("sender")).casefold() != q.get("recipient", "").casefold() or q["mail_state"] != "sent"):
                raise ValueError("Email needs the verified sender and a reconciled sent question")
            if not enabled or q["status"] != "pending":
                return {"accepted": False, "status": q["status"], "winner": q["winner"]}
            winner = {"source": source, "answer": answer, "evidence_id": evidence, "observed_at": now()}
            q.update(status="resolved", winner=winner, closed_at=winner["observed_at"])
            save(q)
            return {"accepted": True, "qid": q["qid"], "winner": winner}
        raise ValueError("Unsupported command")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db")
    p.add_argument("--thread", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    enable = sub.add_parser("enable")
    enable.add_argument("--recipient")
    enable.add_argument("--sender-account")
    for name in ("disable", "status"):
        sub.add_parser(name)
    sub.add_parser("automation").add_argument("--id", required=True)
    sub.add_parser("create").add_argument("--input", required=True)
    for name in ("get", "render", "cancel", "mail", "claim"):
        c = sub.add_parser(name)
        c.add_argument("--qid", required=True)
        if name == "mail":
            c.add_argument("--state", choices=("sending", "sent", "uncertain"), required=True)
            c.add_argument("--message-id")
            c.add_argument("--gmail-thread-id")
        if name == "claim":
            c.add_argument("--input")
            c.add_argument("--source", choices=("screen", "email"))
            c.add_argument("--answer")
            c.add_argument("--evidence-id")
            c.add_argument("--sender")
    return p


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = run(parser().parse_args())
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
