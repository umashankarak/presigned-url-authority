"""Phase 2 extractor for the presigned-URL over-grant study (paper 9).

Turns the Phase 1 corpus (sample.jsonl manifest + sha-addressed blobs/) into
a coding spreadsheet: mechanical columns auto-filled, five judgment columns
(JF1-JF5) left blank for manual/LLM-assisted coding per the Phase 2 codebook.
"""
from __future__ import annotations

__version__ = "0.7.0"
