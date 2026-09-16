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


def process_due_followups(states: dict[str, State], statuses: dict[str, str]):
    """Processes follow-ups in the current process-local job registry.

    Reuses the same job_id end-to-end (no new job is created for the follow-up) —
    the job just re-enters "awaiting_approval" so the existing /jobs/{id} and
    /jobs/{id}/approve routes pick it back up, then finishes gracefully.
    """
    now = datetime.now(timezone.utc)
    for job_id, state in states.items():
        follow_up_at = state.follow_up_at
        if not follow_up_at or follow_up_at > now:
            continue

        # Always check for a reply (by to_email/thread_id/message_id) before
        # drafting a follow-up — a reply means the sequence is done, no follow-up needed.
        if _reply_received(state):
            print(f"[Worker] Job {job_id}: Recipient replied! Stopping follow-up sequence.")
            states[job_id] = state.model_copy(update={
                "follow_up_at": None,
                "followup_stopped_reason": "recipient_replied",
            })
            statuses[job_id] = "completed"
            continue

        print(f"[Worker] Job {job_id}: Follow-up due. Creating follow-up draft.")
        res = draft_followup(state)
        new_followup_drafts = res.get("drafts", {}).get("follow_up", [])
        merged_drafts = {**state.drafts, "follow_up": new_followup_drafts}

        states[job_id] = state.model_copy(update={
            "drafts": merged_drafts,
            "follow_up_at": None,
        })
        # Same job_id re-enters the HITL cycle — no override, no new job.
        statuses[job_id] = "awaiting_approval" if new_followup_drafts else "completed"


def run_daemon(poll_interval: int = 60):
    from routers.jobs import job_states, job_statuses

    print("[FollowupWorker] Starting process-local follow-up worker...")
    while True:
        try:
            process_due_followups(job_states, job_statuses)
        except Exception as e:
            print(f"[FollowupWorker] Error during poll cycle: {e}")
        time.sleep(poll_interval)

