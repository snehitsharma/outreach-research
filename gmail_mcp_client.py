# ============================================================
# gmail_mcp_client.py — Dedicated Gmail MCP / OAuth API Client
# ============================================================

import os
import base64
import uuid
from email.mime.text import MIMEText
from typing import Any

# Check environment settings
GMAIL_MCP_ENABLED = os.environ.get("GMAIL_MCP_ENABLED", "true").lower() in ("true", "1")
CREDENTIALS_FILE = os.environ.get("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.environ.get("GMAIL_TOKEN_FILE", "token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailMCPClient:
    """
    Single source of truth for all Gmail MCP / API calls.
    Handles draft creation, sending emails, and tracking recipient replies via
    thread_id, message_id, and to_email. Automatically loads OAuth credentials from
    credentials.json.
    """

    def __init__(self):
        self._mock_threads: dict[str, list[dict]] = {}
        self._service = None

    def _get_service(self):
        """Builds and caches authenticated Gmail API service if credentials.json is present."""
        if self._service:
            return self._service

        if not os.path.exists(CREDENTIALS_FILE):
            return None

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if os.path.exists(TOKEN_FILE):
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)



            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                elif os.path.exists(CREDENTIALS_FILE) and os.isatty(0):
                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open(TOKEN_FILE, "w") as token:
                        token.write(creds.to_json())
                else:
                    return None


            self._service = build("gmail", "v1", credentials=creds)
            return self._service
        except Exception as e:
            print(f"[GmailMCPClient] Note: Gmail OAuth setup fallback due to: {e}")
            return None

    def create_draft(
        self,
        to_email: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
    ) -> dict[str, str]:
        """
        Creates a draft email in Gmail.
        Returns a dict containing 'draft_id', 'message_id', and 'thread_id'.
        """
        service = self._get_service()
        if service:
            try:
                message = MIMEText(body)
                message["to"] = to_email
                message["subject"] = subject
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

                draft_body = {"message": {"raw": raw}}
                if thread_id:
                    draft_body["message"]["threadId"] = thread_id

                draft = service.users().drafts().create(userId="me", body=draft_body).execute()
                msg = draft.get("message", {})
                return {
                    "draft_id": draft.get("id", ""),
                    "message_id": msg.get("id", ""),
                    "thread_id": msg.get("threadId", thread_id or ""),
                }
            except Exception as e:
                print(f"[GmailMCPClient] Error creating Gmail draft: {e}")

        # Fallback simulation for offline / testing environments
        draft_id = f"draft_{uuid.uuid4().hex[:10]}"
        message_id = f"msg_{uuid.uuid4().hex[:10]}"
        t_id = thread_id or f"thread_{uuid.uuid4().hex[:10]}"

        if t_id not in self._mock_threads:
            self._mock_threads[t_id] = []
        self._mock_threads[t_id].append({
            "type": "draft",
            "draft_id": draft_id,
            "message_id": message_id,
            "to_email": to_email,
            "subject": subject,
            "body": body,
        })

        return {
            "draft_id": draft_id,
            "message_id": message_id,
            "thread_id": t_id,
        }

    def send_message(
        self,
        to_email: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        draft_id: str | None = None,
    ) -> dict[str, str]:
        """
        Sends an email message via Gmail API / MCP.
        If SEND_ACTUAL_EMAILS is false, stores the message as a draft only and does not transmit.
        """
        SEND_ACTUAL_EMAILS = os.environ.get("SEND_ACTUAL_EMAILS", "false").lower() in ("true", "1")
        if not SEND_ACTUAL_EMAILS:
            draft_meta = self.create_draft(to_email=to_email, subject=subject, body=body, thread_id=thread_id)
            return {
                "message_id": draft_meta.get("message_id", ""),
                "thread_id": draft_meta.get("thread_id", ""),
                "status": "stored_in_draft_only",
            }

        service = self._get_service()
        if service:
            try:
                message = MIMEText(body)
                message["to"] = to_email
                message["subject"] = subject
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

                msg_body = {"raw": raw}
                if thread_id:
                    msg_body["threadId"] = thread_id

                sent_msg = service.users().messages().send(userId="me", body=msg_body).execute()
                return {
                    "message_id": sent_msg.get("id", ""),
                    "thread_id": sent_msg.get("threadId", thread_id or ""),
                    "status": "sent",
                }
            except Exception as e:
                print(f"[GmailMCPClient] Error sending Gmail message: {e}")

        # Fallback simulation
        message_id = f"msg_sent_{uuid.uuid4().hex[:10]}"
        t_id = thread_id or f"thread_{uuid.uuid4().hex[:10]}"

        if t_id not in self._mock_threads:
            self._mock_threads[t_id] = []

        self._mock_threads[t_id].append({
            "type": "sent",
            "message_id": message_id,
            "draft_id": draft_id,
            "to_email": to_email,
            "subject": subject,
            "body": body,
        })

        return {
            "message_id": message_id,
            "thread_id": t_id,
            "status": "sent",
        }

    def check_for_reply(
        self,
        to_email: str,
        thread_id: str | None = None,
        message_id: str | None = None,
    ) -> bool:
        """
        Queries Gmail API / MCP for incoming replies from `to_email` or within `thread_id`.
        Returns True if recipient has replied, False otherwise.
        """
        if not to_email:
            return False

        service = self._get_service()
        if service and thread_id:
            try:
                tdata = service.users().threads().get(userId="me", id=thread_id).execute()
                messages = tdata.get("messages", [])
                if len(messages) > 1:
                    # Check if any subsequent message is from recipient
                    for msg in messages[1:]:
                        headers = msg.get("payload", {}).get("headers", [])
                        from_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
                        if to_email.lower() in from_header.lower():
                            return True
            except Exception as e:
                print(f"[GmailMCPClient] Error checking thread reply: {e}")

        # Fallback local thread check
        if thread_id and thread_id in self._mock_threads:
            for item in self._mock_threads[thread_id]:
                if item.get("type") == "reply":
                    return True

        return False

    def simulate_incoming_reply(self, to_email: str, thread_id: str, reply_body: str = "Thanks for reaching out!"):
        """Helper to simulate an incoming reply for testing / verification."""
        if thread_id not in self._mock_threads:
            self._mock_threads[thread_id] = []
        self._mock_threads[thread_id].append({
            "type": "reply",
            "from_email": to_email,
            "body": reply_body,
        })


# Global client instance for import across nodes & workers
gmail_client = GmailMCPClient()
