# ============================================================
# followup_worker.py — Scheduled Follow-Up Daemon Worker (SQLite)
# ============================================================

import os
import sqlite3
import time
import argparse
from datetime import datetime, timezone

from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore

from graph import build_graph
from nodes.outreach_drafter import draft_followup
from gmail_mcp_client import gmail_client


def _draft_info_for(values):
    drafts = values.get("drafts") or {} if isinstance(values, dict) else getattr(values, "drafts", {})
    outreach = drafts.get("outreach", []) if isinstance(drafts, dict) else getattr(drafts, "outreach", [])
    if outreach and isinstance(outreach, list):
        item = outreach[0]
        if isinstance(item, dict):
            return {
                "to_email": item.get("to_email"),
                "thread_id": item.get("gmail_thread_id"),
                "message_id": item.get("gmail_message_id"),
            }
    return {
        "to_email": values.get("to_email") if isinstance(values, dict) else getattr(values, "to_email", None),
        "thread_id": None,
        "message_id": None,
    }


def _reply_received(values: dict) -> bool:
    info = _draft_info_for(values)
    to_email = info.get("to_email")
    thread_id = info.get("thread_id")
    message_id = info.get("message_id")

    if not to_email:
        return False

    return gmail_client.check_for_reply(to_email=to_email, thread_id=thread_id, message_id=message_id)


def check_followup_stop(values: dict) -> bool:
    return _reply_received(values)


def process_due_followups(conn, checkpointer, graph):
    """Queries persistent checkpoints for jobs where follow_up_at is due."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoints;")
        rows = cursor.fetchall()
    except Exception:
        rows = []

    now = datetime.now(timezone.utc)
    for (thread_id,) in rows:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        if not snapshot or not snapshot.values:
            continue

        values = snapshot.values
        follow_up_at = values.get("follow_up_at")
        if not follow_up_at:
            continue

        if isinstance(follow_up_at, str):
            try:
                follow_up_at = datetime.fromisoformat(follow_up_at)
            except Exception:
                continue

        if follow_up_at <= now:
            if _reply_received(values):
                print(f"[Worker] Thread {thread_id}: Recipient replied! Stopping follow-up sequence.")
                graph.update_state(config, {"follow_up_at": None, "followup_stopped_reason": "recipient_replied"})
            else:
                print(f"[Worker] Thread {thread_id}: Follow-up due. Creating follow-up draft.")
                res = draft_followup(values)
                graph.update_state(config, {"drafts": res.get("drafts"), "follow_up_at": None})


def run_daemon(poll_interval: int = 60):
    DB_FILE = os.environ.get("SQLITE_DB_PATH", "state.db")
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()

    graph = build_graph(checkpointer)

    print(f"[FollowupWorker] Starting daemon using SQLite ('{DB_FILE}') (polling every {poll_interval}s)...")
    while True:
        try:
            process_due_followups(conn, checkpointer, graph)
        except Exception as e:
            print(f"[FollowupWorker] Error during poll cycle: {e}")
        time.sleep(poll_interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Follow-up Scheduler Worker")
    parser.add_argument("--once", action="store_true", help="Run a single poll pass and exit")
    args = parser.parse_args()

    DB_FILE = os.environ.get("SQLITE_DB_PATH", "state.db")
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    graph = build_graph(checkpointer)

    if args.once:
        process_due_followups(conn, checkpointer, graph)
    else:
        run_daemon()
