

import re
import unicodedata
from config import config
from state import State

INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (all )?(previous|prior|above)",
    r"system prompt",
    r"you are now",
    r"act as if",
]

CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_node(state: State) -> dict:
    job_id = state.get("job_id") if isinstance(state, dict) else getattr(state, "job_id", None)
    raw = state.get("raw_query", "") if isinstance(state, dict) else getattr(state, "raw_query", "")

    text = unicodedata.normalize("NFKC", raw)
    text = CONTROL_CHAR_PATTERN.sub("", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    was_truncated = len(text) > config.MAX_QUERY_LENGTH
    text = text[:config.MAX_QUERY_LENGTH]

    injection_flagged = any(
        re.search(pattern, text, re.IGNORECASE) for pattern in INJECTION_PATTERNS
    )

    return {
        "query": text,
        "_sanitize_meta": {
            "was_truncated": was_truncated,
            "injection_flagged": injection_flagged,
        },
    }