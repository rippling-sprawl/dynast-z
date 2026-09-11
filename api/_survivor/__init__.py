"""Survivor internals, co-located under api/ for the same reason api/_pickem/
and api/_action/ are: Vercel does not bundle scripts/** with a function, so
anything a serverless handler needs at request time has to live here.

rules.py is pure and stdlib-only. store.py is the Supabase layer, and it leans
on api/_pickem/store.py rather than restating it -- the board both games are
played on is pickem_games, and there is no version of "which games have kicked
off" that should be answered twice.
"""
