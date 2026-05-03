import re
import unicodedata

from config import DefaultsConfig, LocationClause
from models import Job, Profile

# Implicit reject list: any seniority field that contains one of these as a word
# is rejected, unless the term is also explicitly listed in defaults.seniority.
_SENIOR_REJECTS: tuple[str, ...] = (
    "senior",
    "lead",
    "principal",
    "staff",
    "head",
    "starszy",
)


def match_job(job: Job, profile: Profile, defaults: DefaultsConfig) -> bool:
    """Return True iff the listing matches the profile's keywords AND the
    global default seniority and location filters. Pure function — no I/O."""
    return (
        _matches_keywords(job, profile)
        and _matches_seniority(job, defaults)
        and _matches_location(job, defaults)
    )


def _matches_keywords(job: Job, profile: Profile) -> bool:
    if not profile.keywords:
        return False
    haystack = _norm(job.title)
    return any(_norm(kw) in haystack for kw in profile.keywords)


def _matches_seniority(job: Job, defaults: DefaultsConfig) -> bool:
    if job.seniority is None:
        return True
    seniority = _norm(job.seniority)
    allowed = {_norm(s) for s in defaults.seniority}
    for term in _SENIOR_REJECTS:
        if term in allowed:
            continue
        if _has_word(seniority, term):
            return False
    return True


def _matches_location(job: Job, defaults: DefaultsConfig) -> bool:
    if not defaults.locations:
        return True
    haystack = _norm(job.location)
    return any(_clause_matches(haystack, clause) for clause in defaults.locations)


def _clause_matches(haystack: str, clause: LocationClause) -> bool:
    target = clause.city or clause.country
    if not target:
        return False
    if not _has_word(haystack, _norm(target)):
        return False
    if not clause.modes:
        return True
    return any(_has_word(haystack, _norm(mode)) for mode in clause.modes)


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm(s: str) -> str:
    return _strip_diacritics(s).casefold()


def _has_word(haystack: str, needle: str) -> bool:
    """Word-boundary match on already-normalized strings. Avoids false positives
    from short tokens (e.g. country code 'PL' inside 'Pleszew')."""
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
