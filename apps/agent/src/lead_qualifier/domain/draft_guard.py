"""Deterministic checks on a drafted message (plan 8.4 item 5). Pure functions, no LLM."""

from __future__ import annotations

import re
from collections.abc import Iterable

from lead_qualifier.domain.workspace import WorkspaceConfig

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)
# A bare domain such as ``evil.com`` or ``evil.com/x``: dotted labels ending in an alphabetic TLD.
_BARE_RE = re.compile(r"(?<![\w@.-])(?:[^\W_]+(?:-[^\W_]+)*\.)+[^\W\d_]{2,}(?![\w@-])(?:[/?#]\S*)?")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PLACEHOLDER_RE = re.compile(
    r"\[[^\]\n]{1,60}\]|\{\{[^}]*\}\}|\{[A-Za-z_ ]{1,30}\}|<[A-Z_ ]{2,30}>|TODO|lorem ipsum|XXX",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?:(?:US\$|USD|COP|EUR|MXN|\$|€)\s?(?P<a>\d[\d.,]*))|(?:(?P<b>\d[\d.,]*)\s?(?:USD|EUR|dollars|dólares|dolares|euros))",
    re.IGNORECASE,
)
_MARKDOWN_RE = re.compile(r"\*\*|__|```|^\s{0,3}#{1,6}\s|^\s*[-*]\s", re.MULTILINE)
_WORD_RE = re.compile(r"[\wÀ-ÿ'\u2019-]+")
_STOPWORDS = {
    "en": {
        "the",
        "and",
        "you",
        "your",
        "for",
        "with",
        "this",
        "that",
        "our",
        "are",
        "will",
        "have",
    },
    "es": {"el", "la", "los", "las", "y", "tu", "para", "con", "que", "una", "por", "nuestro"},
    "pt": {"o", "os", "as", "e", "você", "para", "com", "que", "uma", "por", "nosso", "sua"},
}


def parse_amount(text: str) -> int | None:
    """``4,900`` / ``4.900`` / ``4900.50`` -> whole units; None if it is not a number."""
    cleaned = text.strip(".,")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", cleaned):
        return int(re.sub(r"[.,]", "", cleaned))
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", cleaned):
        return int(float(cleaned.replace(",", ".")))
    return None


def known_amounts(config: WorkspaceConfig) -> set[int]:
    """Every price fact in the workspace config: product amounts and numbers in price notes."""
    found: set[int] = set()
    for product in config.products:
        if product.price is None:
            continue
        if product.price.amount is not None:
            found.add(product.price.amount)
        for number in re.findall(r"\d[\d.,]*", product.price.note or ""):
            parsed = parse_amount(number)
            if parsed is not None:
                found.add(parsed)
    return found


def _ascii_host(host: str) -> str | None:
    """Lower-case IDNA (punycode) form of ``host``, or None when it is not a plain hostname."""
    try:
        ascii_host = host.strip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return ascii_host if _HOST_RE.match(ascii_host) and ".." not in ascii_host else None


def _host_allowed(host: str, allowed: Iterable[str]) -> bool:
    for domain in allowed:
        base = _ascii_host(domain.removeprefix("www."))
        if base and (host.removeprefix("www.") == base or host.endswith("." + base)):
            return True
    return False


def config_words(config: WorkspaceConfig) -> set[str]:
    """Dotted terms the business itself uses (``Node.js``): not links, even though they look like
    domains."""
    text = " ".join(
        f"{p.name} {p.summary} {p.duration or ''} {p.price.note if p.price else ''}"
        for p in config.products
    )
    return {w.strip(".,;:!?()").lower() for w in text.split() if "." in w.strip(".,;:!?()")}


def _link_problem(token: str, allowed: Iterable[str]) -> str | None:
    """None when the link is acceptable, otherwise why not. The authority is split the way a
    browser does (``/``, ``\\``, ``?``, ``#``) and anything that could make parsers disagree about
    the host (userinfo, escapes, odd ports, non-hostname characters) is rejected outright."""
    scheme = "https"
    rest = token.rstrip(".,;:!?")
    if "://" in rest:
        scheme, rest = rest.split("://", 1)
        scheme = scheme.lower()
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if any(c in authority for c in "\\@%") or authority != authority.strip():
        return f"link with an unsafe address: {token[:60]}"
    host, _, port = authority.partition(":")
    if port and port != _DEFAULT_PORTS.get(scheme):
        return f"link with a non-default port: {token[:60]}"
    ascii_host = _ascii_host(host)
    if ascii_host is None:
        return f"link with an invalid host: {token[:60]}"
    if not _host_allowed(ascii_host, allowed):
        return f"link to a domain that is not allowed: {ascii_host}"
    return None


def _language_scores(text: str) -> dict[str, int]:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return {lang: sum(w in stops for w in words) for lang, stops in _STOPWORDS.items()}


def check_draft(
    config: WorkspaceConfig,
    *,
    language: str,
    subject: str,
    body: str,
    short_body: str | None = None,
) -> list[str]:
    """Return human-readable problems; an empty list means the draft passes."""
    problems: list[str] = []
    # short_body is sent as-is by other channels, so every content rule covers it too.
    text = "\n".join(part for part in (subject, body, short_body) if part)
    words = len(_WORD_RE.findall(body))
    if words > config.drafting.max_words:
        problems.append(f"body has {words} words; the maximum is {config.drafting.max_words}")
    if not body.strip():
        problems.append("body is empty")
    allowed = config.drafting.allowed_link_domains
    tokens = _URL_RE.findall(text)
    remainder = _EMAIL_RE.sub(" ", _URL_RE.sub(" ", text))
    own_terms = config_words(config)
    tokens += [
        m.group(0)
        for m in _BARE_RE.finditer(remainder)
        if m.group(0).rstrip(".,;:!?").lower() not in own_terms
    ]
    for token in tokens:
        problem = _link_problem(token, allowed)
        if problem:
            problems.append(problem)
    allowed_emails = {
        config.profile.contact_email.lower(),
        config.notifications.owner_email.lower(),
    }
    for email in _EMAIL_RE.findall(text):
        if email.lower() not in allowed_emails:
            problems.append(f"email address that is not the business's: {email}")
    if _PLACEHOLDER_RE.search(text):
        problems.append("unresolved placeholder text")
    amounts = known_amounts(config)
    for match in _MONEY_RE.finditer(text):
        value = parse_amount(match.group("a") or match.group("b") or "")
        if value is not None and value not in amounts:
            problems.append(f"price {value} does not appear in the business configuration")
    if short_body is not None:
        if len(short_body) > 1000:
            problems.append("short_body is longer than 1,000 characters")
        if _MARKDOWN_RE.search(short_body):
            problems.append("short_body contains markdown")
    scores = _language_scores(body)
    other = max((v, k) for k, v in scores.items() if k != language) if scores else (0, "")
    if language in scores and other[0] >= 3 and other[0] > scores[language]:
        problems.append(f"the message does not look like it is written in '{language}'")
    return list(dict.fromkeys(problems))
