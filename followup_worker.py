# ============================================================
# followup_worker.py — Scheduled Follow-Up Daemon Worker
# ============================================================

import time
import argparse
from datetime import datetime, timezone

from nodes.outreach_drafter import draft_followup
from gmail_mcp_client import gmail_client
from state import State


def _draft_info_for(state: State) -> dict:
    outreach = state.drafts.get("outreach", [])
    if outreach:
        item = outreach[0]
        return {
            "to_email": item.to_email,
            "thread_id": item.gmail_thread_id,
            "message_id": item.gmail_message_id,
        }

    return {
        "to_email": None,
        "thread_id": None,
        "message_id": None,
    }


def _reply_received(state: State) -> bool:
    info = _draft_info_for(state)
    to_email = info.get("to_email")
    thread_id = info.get("thread_id")
    message_id = info.get("message_id")

    if not to_email:
        return False

    return gmail_client.check_for_reply(to_email=to_email, thread_id=thread_id, message_id=message_id)


def check_followup_stop(state: State) -> bool:
    return _reply_received(state)


def process_due_followups(states: dict[str, State]):
    """Processes follow-ups in the current process-local job registry."""
    now = datetime.now(timezone.utc)
    for thread_id, state in states.items():
        follow_up_at = state.follow_up_at
        if not follow_up_at:
            continue

        if follow_up_at <= now:
            if _reply_received(state):
                print(f"[Worker] Thread {thread_id}: Recipient replied! Stopping follow-up sequence.")
                updates = {
                    "follow_up_at": None,
                    "followup_stopped_reason": "recipient_replied",
                }
            else:
                print(f"[Worker] Thread {thread_id}: Follow-up due. Creating follow-up draft.")
                res = draft_followup(state)
                updates = {"drafts": res.get("drafts"), "follow_up_at": None}

            states[thread_id] = state.model_copy(update=updates)


def run_daemon(poll_interval: int = 60):
    from routers.jobs import job_states

    print("[FollowupWorker] Starting process-local follow-up worker...")
    while True:
        try:
            process_due_followups(job_states)
        except Exception as e:
            print(f"[FollowupWorker] Error during poll cycle: {e}")
        time.sleep(poll_interval)

