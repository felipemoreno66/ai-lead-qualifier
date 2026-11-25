"""Turn repository rows into admin-API view models, using the workspace config for labels."""

from __future__ import annotations

from typing import Any

from lead_qualifier.domain.scoring import JUDGMENT_VALUE, Judgment
from lead_qualifier.domain.workspace import FieldType, WorkspaceConfig
from lead_qualifier.http.schemas import (
    AnswerOut,
    CitationOut,
    CriterionBreakdown,
    KbAnswerOut,
    LeadDetail,
    LeadEventOut,
    MessageOut,
    OutboxEventOut,
)


def interest_label(config: WorkspaceConfig | None, answers: dict[str, Any]) -> str | None:
    """Label of the product-interest answer: the select field whose options are product ids."""
    if config is None:
        return None
    product_ids = set(config.product_ids)
    default = config.languages.default
    for field in config.form.fields:
        if field.type is FieldType.SELECT and any(o.value in product_ids for o in field.options):
            value = answers.get(field.id)
            option = next((o for o in field.options if o.value == value), None)
            return option.label.get(default) if option else None
    return None


def answers_view(config: WorkspaceConfig | None, answers: dict[str, Any]) -> list[AnswerOut]:
    if config is None:
        return [AnswerOut(id=k, label=k, value=v, display=str(v)) for k, v in answers.items()]
    default = config.languages.default
    out: list[AnswerOut] = []
    for field in config.form.fields:
        if field.id not in answers:
            continue
        value = answers[field.id]
        display = str(value)
        if field.type is FieldType.SELECT:
            option = next((o for o in field.options if o.value == value), None)
            display = option.label.get(default, str(value)) if option else str(value)
        elif field.type is FieldType.CHECKBOX:
            display = "Yes" if value else "No"
        out.append(
            AnswerOut(
                id=field.id, label=field.label.get(default, field.id), value=value, display=display
            )
        )
    return out


def score_breakdown(
    config: WorkspaceConfig | None, qualification: dict[str, Any] | None
) -> list[CriterionBreakdown]:
    """Per-criterion points (100 in total) from the stored judgments and the config weights."""
    if config is None or not qualification:
        return []
    weights = {c.id: c for c in config.qualification.criteria}
    total = sum(c.weight for c in weights.values())
    out: list[CriterionBreakdown] = []
    for item in qualification.get("criteria") or []:
        criterion = weights.get(item.get("id"))
        try:
            judgment = Judgment(item.get("judgment"))
        except ValueError:
            continue
        if criterion is None:
            continue
        maximum = criterion.weight / total * 100
        out.append(
            CriterionBreakdown(
                id=criterion.id,
                description=criterion.description,
                judgment=judgment.value,
                points=round(maximum * JUDGMENT_VALUE[judgment], 1),
                max_points=round(maximum, 1),
                evidence=str(item.get("evidence", "")),
            )
        )
    return out


def lead_detail(
    lead: dict[str, Any],
    events: list[dict[str, Any]],
    outbox: list[dict[str, Any]],
    config: WorkspaceConfig | None,
    drafts: list[dict[str, Any]] | None = None,
    kb_answers: list[dict[str, Any]] | None = None,
) -> LeadDetail:
    product_name = None
    if config and lead["recommended_product"]:
        product = next((p for p in config.products if p.id == lead["recommended_product"]), None)
        product_name = product.name if product else None
    return LeadDetail(
        **{
            k: lead[k]
            for k in (
                "id",
                "reference",
                "workspace_slug",
                "status",
                "name",
                "email",
                "country",
                "locale",
                "source",
                "origin",
                "consent_at",
                "consent_notice_version",
                "score",
                "tier",
                "recommended_product",
                "qualification",
                "detected_language",
                "error_reason",
                "created_at",
                "updated_at",
                "qualified_at",
                "sent_at",
            )
        },
        breakdown=score_breakdown(config, lead["qualification"]),
        reasons=[str(r) for r in (lead["qualification"] or {}).get("reasons") or []],
        tier_capped=bool((lead["qualification"] or {}).get("tier_capped")),
        injection_suspected=bool(
            ((lead["qualification"] or {}).get("profile") or {}).get("injection_suspected")
        ),
        workspace_name=config.profile.name if config else lead["workspace_slug"],
        recommended_product_name=product_name,
        answers=answers_view(config, lead["answers"]),
        kb_answers=[
            KbAnswerOut(
                **{k: a[k] for k in ("question", "answer", "covered")},
                citations=[
                    CitationOut(**{k: c[k] for k in CitationOut.model_fields})
                    for c in a["citations"]
                ],
            )
            for a in kb_answers or []
        ],
        events=[LeadEventOut(**{k: e[k] for k in LeadEventOut.model_fields}) for e in events],
        outbox=[OutboxEventOut(**{k: o[k] for k in OutboxEventOut.model_fields}) for o in outbox],
        messages=[MessageOut(**{k: m[k] for k in MessageOut.model_fields}) for m in drafts or []],
    )
