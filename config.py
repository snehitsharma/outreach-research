class Config:
    MAX_QUERY_LENGTH = 500  #used by sanitize.py
    MIN_QUERY_LENGTH = 3 #minimum length of query after sanitization, used by guardrail.py

    MAX_ANGLES = 6 #max-number of research angles to generate in planner.py
    MIN_ANGLES = 3 #minimum number of research angles to generate in planner.py

    MAX_ACTIONS = 5 #max-number of actions can take for generate in researcher.py the more actions, the better the answer, the more cost

    MAX_RETRY_ROUNDS = 2 #used by verifier.py, max number of times to retry research if verifier finds issues

    MAX_RESOLVER_ACTIONS = 3   # resolver.py smaller budget than researcher — targeted, not exploratory
    MAX_PENALTIES_TO_RESOLVE = 3   # resolver.py cap how many flagged items get the expensive treatment

    REPRIORITIZE_PENALTY_WEIGHT = 0.7   # downweight, don't fully trust a resolved/contested claim

    FOLLOW_UP_DELAY_DAYS = 3 #followup.py
config = Config()