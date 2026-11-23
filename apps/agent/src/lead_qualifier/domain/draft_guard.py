"""Deterministic checks on a drafted message (plan 8.4 item 5). Pure functions, no LLM."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

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
_CURRENCY = r"US\$|USD|COP|EUR|MXN|CLP|ARS|PEN|BRL|R\$|\$|€|£"
_CURRENCY_WORDS = r"USD|EUR|COP|MXN|pesos?|dollars?|d[oó]lares|euros?|reais|soles"
_MONEY_RE = re.compile(
    rf"(?:(?:{_CURRENCY})\s?(?P<a>\d[\d.,]*))|(?:(?P<b>\d[\d.,]*)\s?(?:{_CURRENCY_WORDS})\b)",
    re.IGNORECASE,
)
# "5k", "5 mil", "5 thousand": a price in disguise whatever the currency
_SHORTHAND_RE = re.compile(
    r"(?<![\w.])(?P<n>\d+(?:[.,]\d+)?)\s?(?:k|mil|miles|thousand)\b", re.IGNORECASE
)
_UNSAFE_CHARS = {
    c for c in "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
}
_MARKDOWN_RE = re.compile(r"\*\*|__|```|^\s{0,3}#{1,6}\s|^\s*[-*]\s", re.MULTILINE)
_WORD_RE = re.compile(r"[\wÀ-ÿ'\u2019-]+")
_DOT_VARIANTS = str.maketrans({"\u3002": ".", "\uff61": ".", "\uff0e": ".", "\u2024": "."})
_OBFUSCATED_DOT_RE = re.compile(r"\s?[\[({]\s?\.\s?[\])}]\s?|\s(?:dot|punto)\s", re.IGNORECASE)
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


@dataclass(frozen=True)
class Problem:
    """A guard finding: ``code`` is a stable vocabulary safe to show a model, ``message`` is for
    the operator and may quote the offending text."""

    code: str
    message: str


def has_unsafe_chars(text: str, *, allow_newlines: bool) -> bool:
    """Control characters (header injection) and bidi controls (visual spoofing)."""
    for char in text:
        if char in _UNSAFE_CHARS:
            return True
        if unicodedata.category(char) == "Cc" and not (allow_newlines and char in "\n\r\t"):
            return True
    return False


def _normalise_for_links(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DOT_VARIANTS)
    return _OBFUSCATED_DOT_RE.sub(".", text)


def _link_problem(token: str, allowed: Iterable[str]) -> Problem | None:
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
        return Problem("unsafe_link", f"link with an unsafe address: {token[:60]}")
    host, _, port = authority.partition(":")
    if port and port != _DEFAULT_PORTS.get(scheme):
        return Problem("unsafe_link", f"link with a non-default port: {token[:60]}")
    ascii_host = _ascii_host(host)
    if ascii_host is None:
        return Problem("unsafe_link", f"link with an invalid host: {token[:60]}")
    if not _host_allowed(ascii_host, allowed):
        return Problem("disallowed_link", f"link to a domain that is not allowed: {ascii_host}")
    return None


def _language_scores(text: str) -> dict[str, int]:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return {lang: sum(w in stops for w in words) for lang, stops in _STOPWORDS.items()}


def check_draft_detailed(
    config: WorkspaceConfig,
    *,
    language: str,
    subject: str,
    body: str,
    short_body: str | None = None,
) -> list[Problem]:
    """All findings for a message as it would be sent. Empty means it passes."""
    problems: list[Problem] = []
    # short_body is sent as-is by other channels, so every content rule covers it too.
    raw = "\n".join(part for part in (subject, body, short_body) if part)
    text = _normalise_for_links(raw)
    if has_unsafe_chars(subject, allow_newlines=False) or has_unsafe_chars(
        "\n".join(p for p in (body, short_body) if p), allow_newlines=True
    ):
        problems.append(Problem("control_chars", "control or bidirectional characters in the text"))
    words = len(_WORD_RE.findall(body))
    if words > config.drafting.max_words:
        problems.append(
            Problem(
                "too_long", f"body has {words} words; the maximum is {config.drafting.max_words}"
            )
        )
    if not body.strip():
        problems.append(Problem("empty_body", "body is empty"))
    allowed = config.drafting.allowed_link_domains
    own_terms = config_words(config)
    # A mail client may read the text differently from our normalised copy (fullwidth delimiters
    # such as the fullwidth slash or at-sign), so links are checked on the raw AND normalised text.
    for candidate in dict.fromkeys((raw, text)):
        tokens = _URL_RE.findall(candidate)
        remainder = _EMAIL_RE.sub(" ", _URL_RE.sub(" ", candidate))
        tokens += [
            m.group(0)
            for m in _BARE_RE.finditer(remainder)
            if m.group(0).rstrip(".,;:!?").lower() not in own_terms
        ]
        for token in tokens:
            if not token.isascii():
                problems.append(
                    Problem(
                        "unsafe_link", f"link with look-alike or non-ASCII characters: {token[:60]}"
                    )
                )
                continue
            problem = _link_problem(token, allowed)
            if problem:
                problems.append(problem)
    allowed_emails = {
        config.profile.contact_email.lower(),
        config.notifications.owner_email.lower(),
    }
    for email in _EMAIL_RE.findall(text):
        if email.lower() not in allowed_emails:
            problems.append(
                Problem("foreign_email", f"email address that is not the business's: {email}")
            )
    if _PLACEHOLDER_RE.search(text):
        problems.append(Problem("placeholder", "unresolved placeholder text"))
    amounts = known_amounts(config)
    for match in _MONEY_RE.finditer(text):
        value = parse_amount(match.group("a") or match.group("b") or "")
        if value is not None and value not in amounts:
            problems.append(
                Problem(
                    "unknown_price", f"price {value} does not appear in the business configuration"
                )
            )
    for match in _SHORTHAND_RE.finditer(text):
        parsed = parse_amount(match.group("n"))
        if parsed is not None and parsed * 1000 not in amounts:
            problems.append(
                Problem(
                    "unknown_price",
                    f"amount {match.group(0)} does not appear in the business configuration",
                )
            )
    if short_body is not None:
        if len(short_body) > 1000:
            problems.append(
                Problem("short_body_too_long", "short_body is longer than 1,000 characters")
            )
        if _MARKDOWN_RE.search(short_body):
            problems.append(Problem("short_body_markdown", "short_body contains markdown"))
    scores = _language_scores(body)
    other = max((v, k) for k, v in scores.items() if k != language) if scores else (0, "")
    if language in scores and other[0] >= 3 and other[0] > scores[language]:
        problems.append(
            Problem(
                "wrong_language", f"the message does not look like it is written in '{language}'"
            )
        )
    unique: dict[str, Problem] = {}
    for problem in problems:
        unique.setdefault(problem.message, problem)
    return list(unique.values())


def check_draft(
    config: WorkspaceConfig,
    *,
    language: str,
    subject: str,
    body: str,
    short_body: str | None = None,
) -> list[str]:
    """Operator-facing messages of ``check_draft_detailed``."""
    return [
        p.message
        for p in check_draft_detailed(
            config, language=language, subject=subject, body=body, short_body=short_body
        )
    ]
