# ============================================================
# evals/run_evals.py — Benchmark Evaluation Suite Runner
# ============================================================

import json
import os
import sys
import time
import uuid

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from graph import build_graph
from langgraph.checkpoint.memory import MemorySaver
from evals.metrics import evaluate_relevance, evaluate_faithfulness


def run_evaluations():
    print("=" * 60)
    print("[EVALSUITE] Running Swarm Benchmark Evaluation Suite")
    print("=" * 60)

    dataset_path = os.path.join(os.path.dirname(__file__), "eval_dataset.json")
    if not os.path.exists(dataset_path):
        print(f"Error: Dataset file not found at {dataset_path}")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)

    results = []

    for idx, test_case in enumerate(dataset, 1):
        job_id = f"eval_job_{uuid.uuid4().hex[:6]}"
        config_dict = {"configurable": {"thread_id": job_id}}

        print(f"\n[{idx}/{len(dataset)}] Test Case: {test_case['id']} | Query: '{test_case['query'][:50]}...'")

        initial_state = {
            "job_id": job_id,
            "raw_query": test_case["query"],
            "query": "",
            "goal": test_case.get("goal"),
            "guardrail_passed": False,
        }

        start_time = time.time()
        graph.invoke(initial_state, config=config_dict)
        execution_time = round(time.time() - start_time, 2)

        state = graph.get_state(config_dict)
        values = state.values

        report_data = values.get("report")
        report_summary = ""
        if report_data:
            report_summary = getattr(report_data, "summary", None) or (report_data.get("summary") if isinstance(report_data, dict) else str(report_data))

        findings = values.get("findings") or []
        findings_str = "\n".join([str(getattr(f, "claim", f)) for f in findings[:10]])

        print("  Evaluating LLM-as-a-Judge metrics (Relevance & Faithfulness)...")
        rel_eval = evaluate_relevance(test_case["query"], report_summary or "No report generated.")
        faith_eval = evaluate_faithfulness(findings_str or "No web findings", report_summary or "No report generated.")

        res_item = {
            "id": test_case["id"],
            "query": test_case["query"],
            "is_sales_outreach": values.get("is_sales_outreach", False),
            "execution_time_sec": execution_time,
            "findings_count": len(findings),
            "relevance_score": rel_eval["score"],
            "relevance_reasoning": rel_eval["reasoning"],
            "faithfulness_score": faith_eval["score"],
            "faithfulness_reasoning": faith_eval["reasoning"],
        }
        results.append(res_item)

        print(f"  -> Relevance: {rel_eval['score']} | Faithfulness: {faith_eval['score']}")

        # Pacing delay between evaluation queries to strictly adhere to Gemini Free Tier (15 RPM)
        if idx < len(dataset):
            print("  -> Pacing delay (6s) to prevent API rate limit...")
            time.sleep(6.0)

    # Generate Markdown Evaluation Summary
    markdown_results = _generate_eval_markdown(results)
    out_path = os.path.join(os.path.dirname(__file__), "eval_results.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown_results)

    print("\n" + "=" * 60)
    print(f"[OK] Evaluation Suite Complete! Report saved to: {out_path}")
    print("=" * 60)


def _generate_eval_markdown(results: list[dict]) -> str:
    avg_rel = round(sum(r["relevance_score"] for r in results) / len(results), 2)
    avg_faith = round(sum(r["faithfulness_score"] for r in results) / len(results), 2)

    lines = [
        "# 📊 Autonomous Research Swarm — Benchmark Evaluation Results",
        "",
        "## Overall Metric Summary",
        f"- **Mean Answer Relevance**: `{avg_rel} / 1.00`",
        f"- **Mean Fact Faithfulness**: `{avg_faith} / 1.00`",
        "",
        "## Benchmark Test Case Breakdown",
        "",
        "| ID | Query | Intent Mode | Time (s) | Findings | Relevance | Faithfulness |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in results:
        intent = "Sales Outreach" if r["is_sales_outreach"] else "General Research"
        lines.append(
            f"| `{r['id']}` | {r['query'][:35]}... | {intent} | {r['execution_time_sec']}s | {r['findings_count']} | `{r['relevance_score']}` | `{r['faithfulness_score']}` |"
        )

    lines.extend([
        "",
        "## Detailed LLM-as-a-Judge Evaluation Traces",
    ])

    for r in results:
        lines.extend([
            f"### Test Case `{r['id']}`",
            f"- **Query**: {r['query']}",
            f"- **Relevance Reasoning**: {r['relevance_reasoning']}",
            f"- **Faithfulness Reasoning**: {r['faithfulness_reasoning']}",
            "",
        ])

    return "\n".join(lines)


if __name__ == "__main__":
    run_evaluations()
