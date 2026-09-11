"""Pick 'Em internals, co-located under api/ rather than scripts/.

Vercel does not bundle scripts/** with a function -- that is why
/api/odds-ingest is dead in production (ARCHITECTURE.md). Anything the
serverless handlers need at request time has to live here, the same reason
api/_action/ exists.

scoring.py is deliberately pure and stdlib-only so scripts/pickem_capture.py
can import it too: the rule that grades a game against its frozen line is
written once, and the job that stores the verdict and the endpoint that spends
it can never disagree about what it is.
"""
