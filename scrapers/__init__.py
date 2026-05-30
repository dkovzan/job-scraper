"""Scraper registry. Each module exposes a ``fetch() -> list[Job]`` callable;
adding a new source is one entry below."""

from __future__ import annotations

from collections.abc import Callable

from models import Job

from . import bulldogjob, justjoin, linkedin, nofluffjobs, pracuj, theprotocol

SCRAPERS: list[Callable[[], list[Job]]] = [
    justjoin.fetch,
    nofluffjobs.fetch,
    bulldogjob.fetch,
    theprotocol.fetch,
    pracuj.fetch,
    linkedin.fetch,
]
