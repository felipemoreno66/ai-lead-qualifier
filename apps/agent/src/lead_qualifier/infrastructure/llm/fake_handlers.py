"""Rule-based extract and qualify handlers for the fake provider (plan 7.3).

Demo workspace only: the rules key on the Northwind form fields (program, budget, availability,
career_goal) and fall back to neutral judgments when a field is missing. They read the same rendered
prompt a real model would see (``<lead_submission>`` and
``<workspace_context>``), so output is deterministic, explainable and meaningful for the keyless
demo. They never follow instructions found in lead text: they only match fixed keywords on
specific form fields.
"""

from __future__ import annotations

import json
import re
from typing import Any

from lead_qualifier.infrastructure.llm.fake import Handler
from lead_qualifier.ports.llm import StructuredRequest

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_INJECTION_RE = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above)|disregard .{0,20}instruction|system prompt"
    r"|reveal .{0,30}(prompt|instruction)|score me|give me .{0,20}(100|free|scholarship)"
    r"|ignora .{0,20}instruccion|olvida .{0,20}instruccion|puntaje de 100|dame .{0,20}beca",
    re.IGNORECASE,
)
_LANG_WORDS = {
    "es": (
        "quiero",
        "para",
        "mi ",
        "carrera",
        "desarrollo",
        "trabajo",
        "cuándo",
        "cuando",
        "hay ",
        "estoy",
        "también",
        "programación",
        "empleo",
        "datos",
        "¿",
    ),
    "pt": (
        "quero",
        "para ",
        "minha",
        "carreira",
        "trabalho",
        "você",
        "preciso",
        "não",
        "obrigad",
        "desenvolvimento",
        "emprego",
        "olá",
    ),
    "en": ("want", "the ", "my ", "career", "job", "work", "learn", "and ", "how ", "when "),
}
_TECH_WORDS = (
    "code",
    "coding",
    "develop",
    "software",
    "web",
    "program",
    "data",
    "python",
    "react",
    "ai",
    "machine learning",
    "engineer",
    "tech",
    "app",
    "desarroll",
    "programaci",
    "datos",
    "ia ",
    "ingenier",
    "tecnolog",
    "empleo",
    "carrera",
    "career",
    "dados",
    "carreira",
)
_DATA_WORDS = ("data", "datos", "dados", "python", "machine learning", " ai", " ia", "analy", "sql")
_MENTOR_WORDS = ("mentor", "interview", "entrevista", "portfolio", "portafolio")
_START_WORDS = ("start", "empez", "comenz", "cohort", "cohorte", "next month", "soon", "ya ", "now")
_PRIOR_WORDS = (
    "learn",
    "course",
    "curso",
    "self-taught",
    "autodidact",
    "studied",
    "estudi",
    "tutorial",
    "aprend",
)
_BUDGET_UPPER = {"lt-500": 500, "500-2500": 2500, "2500-5000": 5000, "gt-5000": 10**9}
_HOURS_UPPER = {"lt-5h": 5, "5-10h": 10, "10-20h": 20, "gt-20h": 40}


def _tag(content: str, name: str) -> dict[str, Any]:
    match = re.search(rf"<{name}>\n(.*?)\n</{name}>", content, re.DOTALL)
    if match is None:
        raise ValueError(f"prompt has no <{name}> block")
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def _text(lead: dict[str, Any], *, include_free_text: bool = True) -> str:
    answers = lead.get("answers", {})
    parts = [answers.get("career_goal")]
    if include_free_text:
        parts += [lead.get("free_text"), answers.get("looking_for")]
    return " ".join(str(p) for p in parts if p).strip()


def _has(text: str, words: tuple[str, ...]) -> bool:
    low = f" {text.lower()} "
    return any(w in low for w in words)


def _language(text: str, locale: str | None) -> str:
    low = text.lower()
    scores = {lang: sum(low.count(w) for w in words) for lang, words in _LANG_WORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0 or scores[best] == sorted(scores.values())[-2]:
        return locale if locale and len(locale) == 2 else "en"
    return best


def extract(req: StructuredRequest[Any]) -> dict[str, Any]:
    lead = _tag(req.messages[0].content, "lead_submission")
    text = _text(lead)
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
    questions = [s for s in sentences if s.endswith("?") or s.startswith("¿")][:5]
    goal = str(lead.get("answers", {}).get("career_goal") or text or "No goal stated.")
    return {
        "normalized_name": " ".join(w.capitalize() for w in str(lead.get("name", "")).split())[
            :120
        ],
        "detected_language": _language(text, lead.get("locale")),
        "goal_summary": goal.strip()[:300],
        "questions": questions,
        "injection_suspected": bool(_INJECTION_RE.search(text)),
    }


def _hours_needed(product: dict[str, Any]) -> int:
    match = re.search(r"(\d+)\s*h\s*/\s*week", str(product.get("duration") or ""))
    return int(match.group(1)) if match else 5


def _recommend(
    answers: dict[str, Any], goal: str, products: list[dict[str, Any]]
) -> dict[str, Any]:
    by_id = {p["id"]: p for p in products}
    chosen = answers.get("program")
    if chosen in by_id:
        return by_id[chosen]
    for words, product_id in ((_MENTOR_WORDS, "mentorship-1on1"), (_DATA_WORDS, "data-ai-course")):
        if product_id in by_id and _has(goal, words):
            return by_id[product_id]
    return by_id.get("fullstack-bootcamp", products[0])


def _judge(
    criterion: str, lead: dict[str, Any], product: dict[str, Any], profile: dict[str, Any]
) -> tuple[str, str]:
    answers = lead.get("answers", {})
    # Free text flagged as an injection attempt is ignored, so it can neither help nor hurt.
    goal = _text(lead, include_free_text=not profile.get("injection_suspected"))
    if criterion == "goal_fit":
        specific = answers.get("program") not in (None, "not-sure")
        if _has(goal, _TECH_WORDS):
            return (
                ("met", f"Clear tech goal matching {product['name']}.")
                if specific
                else ("partial", f"Tech goal, but no program chosen; {product['name']} fits best.")
            )
        return "unmet", "The stated goal is not related to the programs offered."
    if criterion == "budget_fit":
        upper = _BUDGET_UPPER.get(str(answers.get("budget")))
        amount = (product.get("price") or {}).get("amount")
        if upper is None or not amount:
            return "partial", "Budget or price unknown."
        ratio = upper / amount
        if ratio >= 1:
            return "met", f"Stated budget covers {product['name']}."
        if ratio >= 0.2:
            return "partial", f"Budget covers {product['name']} only through a payment plan."
        return "unmet", f"Stated budget is far below the price of {product['name']}."
    if criterion == "availability_fit":
        upper = _HOURS_UPPER.get(str(answers.get("availability")))
        need = _hours_needed(product)
        if upper is None:
            return "partial", "Weekly availability not stated."
        if upper >= need:
            return "met", f"Weekly time matches the workload of {product['name']}."
        if upper * 2 >= need:
            return "partial", f"Weekly time is tight for {product['name']}."
        return "unmet", f"Weekly time is far below the workload of {product['name']}."
    if criterion == "readiness":
        signals = sum(
            [
                bool(profile.get("questions")),
                _has(goal, _START_WORDS),
                _has(goal, _PRIOR_WORDS),
                len(goal) > 120,
            ]
        )
        if signals >= 2:
            return "met", "Several commitment signals (questions, timing or prior learning)."
        if signals == 1:
            return "partial", "Some signs of commitment, no start date."
        return "unmet", "No visible signs of commitment."
    if criterion == "reachable":
        ok = bool(_EMAIL_RE.match(str(lead.get("email", "")))) and bool(lead.get("country"))
        return ("met", "Valid email and a country.") if ok else ("unmet", "Missing contact data.")
    return "partial", "No rule for this criterion in the fake provider."


def qualify(req: StructuredRequest[Any]) -> dict[str, Any]:
    content = req.messages[0].content
    lead = _tag(content, "lead_submission")
    profile = _tag(content, "lead_profile")
    context = _tag(content, "workspace_context")
    trusted_text = _text(lead, include_free_text=not profile.get("injection_suspected"))
    product = _recommend(
        lead.get("answers", {}),
        trusted_text,
        context.get("products") or [{"id": "unknown", "name": "the program", "summary": ""}],
    )
    criteria = []
    for criterion in context.get("criteria", []):
        judgment, evidence = _judge(criterion["id"], lead, product, profile)
        criteria.append({"id": criterion["id"], "judgment": judgment, "evidence": evidence})
    order = {"met": 0, "partial": 1, "unmet": 2}
    reasons = [c["evidence"] for c in sorted(criteria, key=lambda c: order[c["judgment"]])][:3]
    return {"criteria": criteria, "recommended_product": product["id"], "reasons": reasons}


_COPY: dict[str, dict[str, str]] = {
    "en": {
        "subject": "Your application to {business}",
        "hello": "Hi {name},",
        "intro": "Thank you for applying to {business}. Based on your application, the best fit"
        " for you looks like the {product}: {summary}",
        "price": "It costs USD {amount} ({note}).",
        "price_plain": "It costs USD {amount}.",
        "next_hot": "Spots fill quickly, so the best next step is to talk this week.",
        "next_warm": "We would be glad to answer your questions and help you decide.",
        "next_cold": "There is no rush: we can help you find the right starting point.",
        "close": "{cta}.",
    },
    "es": {
        "subject": "Tu solicitud a {business}",
        "hello": "Hola {name},",
        "intro": "Gracias por postularte a {business}. Según tu solicitud, la mejor opción para ti"
        " parece ser {product}: {summary}",
        "price": "Cuesta USD {amount} ({note}).",
        "price_plain": "Cuesta USD {amount}.",
        "next_hot": "Los cupos se llenan rápido, así que lo mejor es hablar esta semana.",
        "next_warm": "Con gusto resolvemos tus dudas y te ayudamos a decidir.",
        "next_cold": "No hay prisa: podemos ayudarte a encontrar el punto de partida adecuado.",
        "close": "{cta}.",
    },
}


def draft(req: StructuredRequest[Any]) -> dict[str, Any]:
    """A short templated email in the lead's language. It never quotes free text from the lead."""
    content = req.messages[0].content
    lead = _tag(content, "lead_submission")
    ctx = _tag(content, "draft_context")
    copy = _COPY.get(ctx["language"], _COPY["en"])
    first = re.sub(r"[^A-Za-zÀ-ÿ'-]", "", str(lead.get("name", "")).split(" ")[0])[:30]
    product = ctx["product"]
    price = product.get("price") or {}
    parts = [copy["hello"].format(name=first.capitalize() or "there")]
    parts.append(
        copy["intro"].format(
            business=ctx["business"], product=product["name"], summary=product["summary"]
        )
    )
    if price.get("amount") is not None:
        key = "price" if price.get("note") else "price_plain"
        parts.append(copy[key].format(amount=price["amount"], note=price.get("note")))
    parts.append(copy[f"next_{ctx['tier']}"])
    parts.append(copy["close"].format(cta=ctx["call_to_action"].rstrip(".")))
    parts.append(ctx["signature"])
    body = "\n\n".join(parts)
    return {
        "subject": copy["subject"].format(business=ctx["business"]),
        "body": body,
        "short_body": " ".join(parts[:-1])[:1000],
    }


FAKE_HANDLERS: dict[str, Handler] = {"extract": extract, "qualify": qualify, "draft": draft}
