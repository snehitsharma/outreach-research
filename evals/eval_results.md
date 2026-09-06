# 📊 Autonomous Research Swarm — Benchmark Evaluation Results

## Overall Metric Summary
- **Mean Answer Relevance**: `0.7 / 1.00`
- **Mean Fact Faithfulness**: `0.8 / 1.00`
- **Mean Apollo Contact Precision**: `0.33 / 1.00`

## Benchmark Test Case Breakdown

| ID | Query | Intent Mode | Time (s) | Findings | Contacts | Relevance | Faithfulness | Apollo Precision |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `eval_01` | Research NVIDIA AI infrastructure d... | Sales Outreach | 333.98s | 156 | 161 | `0.4` | `1.0` | `0.0` |
| `eval_02` | Analyze the technical architecture,... | General Research | 1026.35s | 118 | 4 | `0.85` | `1.0` | `1.0` |
| `eval_03` | Investigate Snowflake Data Cloud fe... | Sales Outreach | 1792.59s | 0 | 0 | `0.85` | `0.4` | `0.0` |

## Detailed Evaluation Traces
### Test Case `eval_01`
- **Query**: Research NVIDIA AI infrastructure developments and identify key engineering leadership contacts to reach out to
- **Relevance Reasoning**: The executive report introduces NVIDIA's AI infrastructure developments and mentions key engineering executives, but it acts merely as an introduction/abstract rather than delivering the actual research findings and specific leadership contacts requested by the query.
- **Apollo Precision Reasoning**: 0 of 161 contacts enriched with verified Apollo API emails.

### Test Case `eval_02`
- **Query**: Analyze the technical architecture, consensus model, and performance of Solana vs Ethereum 2.0
- **Relevance Reasoning**: Report directly answers target research query.
- **Apollo Precision Reasoning**: N/A (General Research)

### Test Case `eval_03`
- **Query**: Investigate Snowflake Data Cloud features and discover VP of Engineering contacts
- **Relevance Reasoning**: Report directly answers target research query.
- **Apollo Precision Reasoning**: No contacts identified.
