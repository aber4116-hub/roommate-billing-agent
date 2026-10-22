"""规则在服务层的不可变视图。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RulePayload:
    rule_version_id: UUID
    owner_person_id: UUID
    methods: dict[str, str]
