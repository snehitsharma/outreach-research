import os
import re
import time
from typing import TypeVar, Type

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel


load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    """LangChain Gemini wrapper with Pydantic structured output."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = (
            ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=GEMINI_API_KEY,
                temperature=0,
            )
            if GEMINI_API_KEY
            else None
        )

    def generate(self, prompt: str, response_model: Type[T], max_retries: int = 5) -> T:
        if not self._model:
            return response_model.model_construct()

        structured_model = self._model.with_structured_output(response_model)
        for attempt in range(max_retries + 1):
            try:
                time.sleep(0.3)
                response = structured_model.invoke(prompt)
                if isinstance(response, response_model):
                    return response
                return response_model.model_validate(response)
            except Exception as e:
                err_str = str(e)
                if (
                    "429" in err_str
                    or "ResourceExhausted" in err_str
                    or "Quota" in err_str
                ) and attempt < max_retries:
                    match = re.search(r"Please retry in (\d+\.?\d*)s", err_str)
                    wait_sec = float(match.group(1)) + 1.0 if match else (attempt + 1) * 6
                    print(
                        f"[GeminiClient RateLimit] Model {self.model_name} rate limited. "
                        f"Retrying in {wait_sec:.1f}s..."
                    )
                    time.sleep(wait_sec)
                    continue

                print(f"[GeminiClient] Error on model {self.model_name}: {e}")
                break

        return response_model.model_construct()


light_llm = GeminiClient(os.environ.get("GEMINI_MODEL_CHEAP", "gemini-1.5-flash"))
mid_llm = GeminiClient(os.environ.get("GEMINI_MODEL_MID", "gemini-1.5-flash"))
strong_llm = GeminiClient(os.environ.get("GEMINI_MODEL_STRONG", "gemini-1.5-pro"))


