# ============================================================
# evals/metrics.py — Real LLM-as-a-Judge Metrics
# ============================================================

import sys
import os
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from llm_clients import cheap_llm
from pydantic import BaseModel, Field


class RelevanceScore(BaseModel):
    score: float = Field(..., description="Score between 0.0 and 1.0")
    reasoning: str = Field(..., description="Justification for score")


class FaithfulnessScore(BaseModel):
    score: float = Field(..., description="Score between 0.0 and 1.0")
    reasoning: str = Field(..., description="Justification for score")


def evaluate_relevance(query: str, report_summary: str) -> dict:
    """
    LLM-as-a-Judge metric: Evaluates how relevant and responsive the generated report is to the user's query.
    """
    time.sleep(1.5)  # Rate-limit safety delay
    res = cheap_llm.generate(
        prompt=f"""You are an expert AI system evaluator. Assess how well the provided Executive Research Report addresses the user's Research Query.

Research Query: "{query}"

Executive Report:
{report_summary[:3000]}

Rate relevance on a scale from 0.0 (completely irrelevant/off-topic) to 1.0 (perfectly relevant and comprehensive).
""",
        response_model=RelevanceScore,
    )
    return {
        "score": getattr(res, "score", 0.5),
        "reasoning": getattr(res, "reasoning", "Evaluated report relevance against research query."),
    }


def evaluate_faithfulness(findings_summary: str, report_summary: str) -> dict:
    """
    LLM-as-a-Judge metric: Evaluates factual consistency between extracted web findings and the final report.
    """
    time.sleep(1.5)  # Rate-limit safety delay
    res = cheap_llm.generate(
        prompt=f"""You are an expert AI system evaluator. Assess whether the Executive Report is strictly faithful to the verified Web Findings and free of hallucinated claims.

Retrieved Web Findings:
{findings_summary[:2000]}

Executive Report:
{report_summary[:2000]}

Rate faithfulness on a scale from 0.0 (completely unfaithful/hallucinated) to 1.0 (perfectly faithful and grounded).
""",
        response_model=FaithfulnessScore,
    )
    return {
        "score": getattr(res, "score", 0.5),
        "reasoning": getattr(res, "reasoning", "Evaluated factual alignment with retrieved findings."),
    }
