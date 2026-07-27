"""Daily plan endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, SessionDep
from ..models.planning import Plan
from ..schemas.plans import GeneratePlanRequest, PlanItemResponse, PlanResponse
from ..services import plans as service

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/today", response_model=PlanResponse)
def read_today(user: CurrentUser, session: SessionDep) -> PlanResponse:
    """Today's plan, generated on first request and stable thereafter."""
    plan = service.get_or_create_today(session, user.id)
    session.commit()
    return _to_response(plan)


@router.post("/generate", response_model=PlanResponse)
def generate(payload: GeneratePlanRequest, user: CurrentUser, session: SessionDep) -> PlanResponse:
    plan = service.generate_plan(session, user.id, replace_existing=payload.regenerate)
    session.commit()
    return _to_response(plan)


def _to_response(plan: Plan) -> PlanResponse:
    items = [
        PlanItemResponse(
            sequence=item.sequence,
            activity_key=item.activity_key,
            activity_type=item.activity_type,
            estimated_minutes=item.estimated_minutes,
            title=str(item.priority_components.get("title", item.activity_key)),
            kind=str(item.priority_components.get("kind", "")),
            skill_key=str(item.priority_components.get("skill_key", "")),
            domain=str(item.priority_components.get("domain", "")),
            reason_codes=list(item.reason_codes),
            explanation=str(item.priority_components.get("explanation", "")),
            priority=float(item.priority_components.get("priority", 0.0)),
            components=dict(item.priority_components.get("components", {})),
        )
        for item in plan.items
    ]

    rationale = plan.rationale or {}
    return PlanResponse(
        id=plan.id,
        plan_date=plan.plan_date,
        requested_minutes=plan.requested_minutes,
        total_minutes=sum(item.estimated_minutes for item in items),
        status=plan.status,
        engine_version=plan.engine_version,
        items=items,
        has_receptive=bool(rationale.get("has_receptive", False)),
        has_productive=bool(rationale.get("has_productive", False)),
        unmet_constraints=list(rationale.get("unmet_constraints", [])),
    )
