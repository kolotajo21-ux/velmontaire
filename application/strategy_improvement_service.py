from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from backend.application.strategy_management_service import StrategyManagementService


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    proposal_id: str
    strategy_id: str
    base_version_id: str
    request_text: str
    status: str
    questions: tuple[str, ...]
    blockers: tuple[str, ...]
    proposed_schema: dict[str, Any] | None
    changes: tuple[str, ...]


class StrategyImprovementService:
    """
    Product-facing strategy revision workflow.

    User intent:
        "Добавь фильтр сессии"
        "Хочу вход только после FVG"
        "Чего не хватает моей ТС?"

    Safety invariants:
    - proposals are pinned to the current immutable version;
    - AI suggestions never silently modify the active strategy;
    - unresolved proposals cannot be applied;
    - applying creates a NEW immutable version;
    - the new version is not activated automatically;
    - stale proposals fail closed.
    """

    def __init__(
        self,
        *,
        strategies: StrategyManagementService,
        reviser: Any,
    ) -> None:
        self.strategies = strategies
        self.reviser = reviser
        self._proposals: dict[str, tuple[str, ImprovementProposal]] = {}

    def propose(
        self,
        *,
        user_id: str,
        strategy_id: str,
        request_text: str,
    ) -> ImprovementProposal:
        request_text = str(request_text).strip()
        if not request_text:
            raise ValueError("improvement_request_required")

        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )
        base_schema = self._schema(active.schema_json)

        raw = self.reviser.propose(
            source_text=active.source_text,
            schema=base_schema,
            request_text=request_text,
        )
        proposal = self._normalize(
            strategy_id=strategy_id,
            base_version_id=active.version_id,
            request_text=request_text,
            raw=raw,
        )
        self._proposals[proposal.proposal_id] = (user_id, proposal)
        return proposal

    def answer(
        self,
        *,
        user_id: str,
        proposal_id: str,
        answers: dict[str, Any],
    ) -> ImprovementProposal:
        owner, current = self._owned(user_id, proposal_id)
        if not answers:
            raise ValueError("improvement_answers_required")

        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=current.strategy_id,
        )
        if active.version_id != current.base_version_id:
            raise RuntimeError("improvement_proposal_is_stale")

        raw = self.reviser.answer(
            source_text=active.source_text,
            schema=self._schema(active.schema_json),
            request_text=current.request_text,
            answers=answers,
        )
        updated = self._normalize(
            strategy_id=current.strategy_id,
            base_version_id=current.base_version_id,
            request_text=current.request_text,
            raw=raw,
            proposal_id=proposal_id,
        )
        self._proposals[proposal_id] = (owner, updated)
        return updated

    def apply(
        self,
        *,
        user_id: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        _, proposal = self._owned(user_id, proposal_id)
        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=proposal.strategy_id,
        )

        if active.version_id != proposal.base_version_id:
            raise RuntimeError("improvement_proposal_is_stale")
        if proposal.status != "READY":
            raise RuntimeError("improvement_proposal_not_ready")
        if proposal.questions or proposal.blockers:
            raise RuntimeError("improvement_proposal_unresolved")
        if proposal.proposed_schema is None:
            raise RuntimeError("improvement_schema_missing")

        created = self.strategies.create_version(
            user_id=user_id,
            strategy_id=proposal.strategy_id,
            source_text=active.source_text,
            schema_json=json.dumps(
                proposal.proposed_schema,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        return created

    def get(self, *, user_id: str, proposal_id: str) -> ImprovementProposal:
        return self._owned(user_id, proposal_id)[1]

    def _owned(self, user_id: str, proposal_id: str):
        item = self._proposals.get(proposal_id)
        if item is None or item[0] != user_id:
            raise PermissionError("improvement_proposal_not_owned")
        return item

    @classmethod
    def _normalize(
        cls,
        *,
        strategy_id: str,
        base_version_id: str,
        request_text: str,
        raw: Any,
        proposal_id: str | None = None,
    ) -> ImprovementProposal:
        def get(name: str, default: Any):
            return raw.get(name, default) if isinstance(raw, dict) else getattr(raw, name, default)

        schema = get("proposed_schema", None)
        questions = tuple(str(x) for x in get("questions", []) or [])
        blockers = tuple(str(x) for x in get("blockers", []) or [])
        changes = tuple(str(x) for x in get("changes", []) or [])
        status = get("status", "NEEDS_CLARIFICATION")
        if hasattr(status, "value"):
            status = status.value

        return ImprovementProposal(
            proposal_id=proposal_id or f"proposal_{uuid.uuid4().hex}",
            strategy_id=strategy_id,
            base_version_id=base_version_id,
            request_text=request_text,
            status=str(status),
            questions=questions,
            blockers=blockers,
            proposed_schema=schema,
            changes=changes,
        )

    @staticmethod
    def _schema(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
