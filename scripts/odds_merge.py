#!/usr/bin/env python3
"""
Orchestration layer shared by the CLI parsers and the serverless ingest endpoint
(api/odds-ingest.py). Given one pasted Recorder bundle it detects the book and
runs the same pure merge/apply functions the CLI scripts use — but against
in-memory state instead of files, so it works on Vercel's read-only filesystem.

State model (plain JSON, what the store holds — see api/odds-ingest.py):
    fd        : {layout, attachments}        — views/odds.html primary feed
    dk        : DK native {sports, leagues, events, markets, selections, ...}
    score     : {stat_file: wrapped_doc}     — one entry per data/score/<stat>.json
    outrights : {markets, milestones}        — shared award/futures, all books

Every merge is additive: a partial bundle never deletes another book, market,
candidate, or field. A PUT of any single book's bundle updates that book's prop
feed plus its column in the shared outrights doc, leaving the other books intact.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import sort_doc                       # noqa: E402
from parse_fd_import import merge_fd                        # noqa: E402
from parse_dk_import import merge_dk_props                  # noqa: E402
from parse_score_import import merge_score                  # noqa: E402
from parse_fd_outrights import apply_fd_outrights           # noqa: E402
from parse_dk_outrights import apply_dk_outrights           # noqa: E402
from parse_score_outrights import apply_score_outrights     # noqa: E402

BOOKS = ("fd", "dk", "score")


def empty_state():
    return {"fd": {"layout": {}, "attachments": {}},
            "dk": None,
            "score": {},
            "outrights": {"markets": {}, "milestones": {}}}


def detect_book(bundle):
    """Identify which sportsbook a Recorder bundle came from, or None. Matches the
    host/page first, then falls back to scanning the captured request URLs."""
    parts = [str(bundle.get("host") or ""), str(bundle.get("page") or "")]
    for c in (bundle.get("captures") or []):
        u = c.get("url")
        if u:
            parts.append(u)
    hay = " ".join(parts).lower()
    if "fanduel" in hay:
        return "fd"
    if "draftkings" in hay:
        return "dk"
    if "thescore" in hay:
        return "score"
    return None


def _outrights(state):
    doc = state.get("outrights") or {"markets": {}, "milestones": {}}
    doc.setdefault("markets", {})
    doc.setdefault("milestones", {})
    return doc


def ingest(bundle, state=None, book=None):
    """Merge one Recorder bundle into `state` (defaults to empty_state()) and
    return (state, summary). `book` overrides auto-detection. summary carries the
    per-book parser summaries and `changed_keys`: the state keys the caller should
    persist. Raises ValueError if the book can't be determined."""
    state = state or empty_state()
    captures = bundle.get("captures", []) if isinstance(bundle, dict) else []
    book = book or detect_book(bundle)
    if book not in BOOKS:
        raise ValueError("Could not determine sportsbook from bundle "
                         "(expected FanDuel, DraftKings, or theScore).")

    doc = _outrights(state)
    summary = {"book": book}

    if book == "fd":
        fd = state.get("fd") or {"layout": {}, "attachments": {}}
        fd, summary["props"] = merge_fd(fd, captures)
        summary["outrights"] = apply_fd_outrights(doc, fd)
        state["fd"] = fd

    elif book == "dk":
        dk, summary["props"] = merge_dk_props(state.get("dk"), captures)
        summary["outrights"] = apply_dk_outrights(doc, captures)
        state["dk"] = dk

    elif book == "score":
        existing = state.get("score") or {}
        out_by_stat, summary["props"] = merge_score(existing, captures)
        # Additive: keep every prior stat, overlay only the ones this bundle changed.
        state["score"] = {**existing, **out_by_stat}
        summary["outrights"] = apply_score_outrights(doc, captures)

    state["outrights"] = sort_doc(doc)
    # Persist the touched book's prop feed and the shared outrights doc.
    summary["changed_keys"] = [book, "outrights"]
    return state, summary


if __name__ == "__main__":
    # Smoke test: rebuild full state from the three local import bundles and
    # report what each contributes. Does not write any files.
    import json
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state = empty_state()
    for name in ("fd", "dk", "score"):
        path = os.path.join(ROOT, "data", "imports", name + ".json")
        if not os.path.exists(path):
            print("skip %s (no bundle)" % name)
            continue
        bundle = json.load(open(path))
        state, s = ingest(bundle, state)
        print("ingested %-5s -> changed %s" % (s["book"], s["changed_keys"]))
    mk = state["outrights"]["markets"]
    print("\noutrights markets: %d" % len(mk))
    print("score stats: %s" % ", ".join(sorted(state["score"])))
    print("dk markets: %d, fd markets: %d" % (
        len((state["dk"] or {}).get("markets", [])),
        len(state["fd"]["attachments"].get("markets", {}))))
