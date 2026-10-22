"""当前请求主体（用户 + 账本成员关系）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    household_id: UUID | None = None
    role: str | None = None
    person_id: UUID | None = None
    memberships: dict[UUID, str] = field(default_factory=dict)
    person_ids: dict[UUID, UUID | None] = field(default_factory=dict)
    session_id: UUID | None = None

    def role_for(self, household_id: UUID) -> str | None:
        if household_id in self.memberships:
            return self.memberships[household_id]
        if household_id == self.household_id:
            return self.role
        return None

    def person_for(self, household_id: UUID) -> UUID | None:
        if household_id in self.person_ids:
            return self.person_ids[household_id]
        if household_id == self.household_id:
            return self.person_id
        return None
