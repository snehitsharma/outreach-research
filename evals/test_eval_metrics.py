# ============================================================
# evals/test_eval_metrics.py — Unit Test for LLM-as-a-Judge Metrics
# ============================================================

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from evals.metrics import evaluate_relevance, evaluate_faithfulness

def test_metrics():
    print("=== TESTING LLM-AS-A-JUDGE METRICS ===")
    
    # 1. Relevance Evaluation (Gemini LLM Judge)
    rel = evaluate_relevance(
        query="Research NVIDIA AI infrastructure developments",
        report_summary="Executive report analyzing NVIDIA H100 and B200 NVLink architecture deployments."
    )
    print("\n1. Relevance Metric (LLM Judge):")
    print(f"   Score: {rel['score']} | Reasoning: {rel['reasoning']}")

    # 2. Faithfulness Evaluation (Gemini LLM Judge)
    faith = evaluate_faithfulness(
        findings_summary="NVIDIA launched Blackwell B200 with 208 billion transistors.",
        report_summary="NVIDIA introduced Blackwell B200 featuring 208 billion transistors for AI workloads."
    )
    print("\n2. Faithfulness Metric (LLM Judge):")
    print(f"   Score: {faith['score']} | Reasoning: {faith['reasoning']}")

    print("\n[OK] Metric tests complete!")

if __name__ == "__main__":
    test_metrics()
