
from state import State
from schemas import Finding, ResolverDecision, VerifierStatus
from tools import cross_encoder
from config import config


def reranker_node(state: State) -> dict:
    # 1. Start with everything verifier passed clean
    surviving: list[Finding] = list(state.verified_findings or [])  

    # 2. Add back whatever resolver decided to keep/reprioritize
    for penalty in state.resolved_penalties or []:
        if penalty.resolver_decision == ResolverDecision.DISCARD:
            continue  

        f = Finding(
            id=penalty.id,
            researcher_id="resolved",  # origin ambiguous post-resolution, mark explicitly
            claim=penalty.claim,
            src_link=penalty.src_link,
            snippet=penalty.snippet,
            confidence="medium",
            verifier_status=VerifierStatus.VERIFIED,
        )
        surviving.append(f)

    if not surviving:
        return {"reranked": []}

    # 3. Score relevance to the original query via cross-encoder
    try:
        scores = cross_encoder.score(
            query=state.query,
            documents=[f.claim for f in surviving],
        )
    except Exception:
        scores = [1.0] * len(surviving)

    # 4. Reprioritized items get a score penalty — they survived, but with less trust
    
    reprioritized_ids = {
        p.id for p in state.resolved_penalties or []
        if p.resolver_decision == ResolverDecision.REPRIORITIZE
    }

    scored = [
        (f, score * config.REPRIORITIZE_PENALTY_WEIGHT if f.id in reprioritized_ids else score)
        for f, score in zip(surviving, scores)
    ]

    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)

    return {"reranked": [f for f, _ in ranked]}