"""Shared library for the Action Network book endpoints.

Underscore-prefixed so Vercel does not route it as a function, and inside api/
so it is bundled with the functions that import it -- scripts/** is not, which
is why /api/odds-ingest is dead in production.
"""
