# ============================================================
# llm_clients.py — Clean 3-Tier Gemini Client with Rate-Limit Handling
# ============================================================

import os
import time
import re
from typing import TypeVar, Type
from dotenv import load_dotenv
import google.generativeai as genai
from pydantic import BaseModel

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

T = TypeVar("T", bound=BaseModel)


def _clean_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema

    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        non_null = [s for s in schema["anyOf"] if isinstance(s, dict) and s.get("type") != "null"]
        if non_null:
            return _clean_schema(non_null[0])

    cleaned = {}
    for k, v in schema.items():
        if k in ("default", "title", "description", "$defs", "$ref", "anyOf"):
            continue
        if isinstance(v, dict):
            cleaned[k] = _clean_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [_clean_schema(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v
    return cleaned


class GeminiClient:
    """Wrapper around Gemini model enforcing structured (Pydantic) outputs with rate-limit retry."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = genai.GenerativeModel(model_name) if GEMINI_API_KEY else None

    def generate(self, prompt: str, response_model: Type[T], max_retries: int = 5) -> T:
        if not self._model:
            return response_model.model_construct()

        cleaned_schema = _clean_schema(response_model.model_json_schema())

        for attempt in range(max_retries + 1):
            try:
                # Small inter-call spacing to respect 15 RPM free tier limits
                time.sleep(0.3)
                response = self._model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema=cleaned_schema,
                    ),
                )
                return response_model.model_validate_json(response.text)
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "ResourceExhausted" in err_str or "Quota" in err_str) and attempt < max_retries:
                    # Extract suggested delay or default to exponential backoff
                    match = re.search(r"Please retry in (\d+\.?\d*)s", err_str)
                    wait_sec = float(match.group(1)) + 1.0 if match else (attempt + 1) * 6
                    print(f"[GeminiClient RateLimit] Model {self.model_name} rate limited. Retrying in {wait_sec:.1f}s...")
                    time.sleep(wait_sec)
                    continue

                print(f"[GeminiClient] Error on model {self.model_name}: {e}")
                break

        return response_model.model_construct()


# 3-Tier Model Clients
cheap_llm = GeminiClient(os.environ.get("GEMINI_MODEL_CHEAP", "gemini-1.5-flash"))
mid_llm = GeminiClient(os.environ.get("GEMINI_MODEL_MID", "gemini-1.5-flash"))
strong_llm = GeminiClient(os.environ.get("GEMINI_MODEL_STRONG", "gemini-1.5-pro"))

# Standard alias for backward compatibility
three_tier_llm = cheap_llm