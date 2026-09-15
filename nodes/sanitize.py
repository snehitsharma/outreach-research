
import re
import unicodedata

from config import config
from state import State, SanitizeMeta

INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (all )?(previous|prior|above)",
    r"system prompt",
    r"you are now",
    r"act as if",
]

CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def strip_control_chars(text: str) -> str:
    return CONTROL_CHAR_PATTERN.sub("", text)


def strip_html_tags(text: str) -> str:
    return HTML_TAG_PATTERN.sub("", text)


def collapse_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def detect_injection(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in INJECTION_PATTERNS)


def clean_text(text: str) -> str:
    text = normalize_unicode(text)
    text = strip_control_chars(text)
    text = strip_html_tags(text)
    text = collapse_whitespace(text)
    return text


def sanitize_node(state: State) -> dict:
    cleaned = clean_text(state.raw_query)

    injection_flagged = detect_injection(cleaned)

    was_truncated = len(cleaned) > config.MAX_QUERY_LENGTH
    cleaned = cleaned[:config.MAX_QUERY_LENGTH]

    goal = config.GOAL if config.GOAL else clean_text(state.goal) if state.goal else None

    return {
        "query": cleaned,
        "goal": goal,
        "sanitize_meta": SanitizeMeta(
            was_truncated=was_truncated,
            injection_flagged=injection_flagged,
        ),
    }