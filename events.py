# ============================================================
# events.py — Real-Time SSE Telemetry & Event Streaming Bus
# ============================================================

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List


class JobEventManager:
    

    def __init__(self):
        self._history: Dict[str, List[dict]] = {}
        self._listeners: Dict[str, List[asyncio.Queue]] = {}

    def emit(self, job_id: str, node: str, event_type: str, message: str, payload: dict | None = None):
        if not job_id:
            return

        event = {
            "job_id": job_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "time_formatted": datetime.now().strftime("%H:%M:%S"),
            "node": node,
            "event_type": event_type,  
            "message": message,
            "payload": payload or {},
        }

        # Store in history
        if job_id not in self._history:
            self._history[job_id] = []
        self._history[job_id].append(event)

        # Broadcast to active SSE listeners
        if job_id in self._listeners:
            for q in list(self._listeners[job_id]):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def get_history(self, job_id: str) -> List[dict]:
        
        return self._history.get(job_id, [])

    async def subscribe(self, job_id: str) -> AsyncGenerator[str, None]:

        q = asyncio.Queue()
        if job_id not in self._listeners:
            self._listeners[job_id] = []
        self._listeners[job_id].append(q)

        for past_event in self.get_history(job_id):
            yield f"data: {json.dumps(past_event)}\n\n"

        try:
            while True:
            
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("event_type") in ("job_complete", "job_failed", "job_rejected"):
                        break
                except asyncio.TimeoutError:
                    # Ping heartbeat to keep connection alive
                    yield f": heartbeat\n\n"
        finally:
            if job_id in self._listeners and q in self._listeners[job_id]:
                self._listeners[job_id].remove(q)



events_manager = JobEventManager()
