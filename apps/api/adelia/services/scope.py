"""Scope — whose record a read is about.

The audit's line on the architecture was that `profile_id` "se escribe en cinco
tablas y no se lee en ninguna consulta": documents, chunks, entities, briefings
and consent_events all carry the column, the upload path validates it and
writes it, and then every read filtered on `user_id` alone. A mother with two
children therefore got one merged vault: her newborn's question was answered
with her four-year-old's chunks, and the briefing she printed for the
paediatrician mixed both.

`Scope` is the one object that travels down the read paths (retrieval,
structured query, briefing assembly, the document list) so the filter is
written once and applied identically everywhere.

Backward compatibility is the pattern `telegram_diary.has_diary_for` already
uses, and it is deliberate rather than lenient: rows written before profiles
existed (and rows a surface still writes without one, such as an email import)
carry `profile_id IS NULL`. Dropping them would silently empty the history of
every v0.1 account, so a scoped read returns "this profile OR not yet assigned
to any profile". Only a row that explicitly belongs to ANOTHER profile is
excluded, which is exactly the leak the audit found.

A `Scope` with `profile_id=None` is the pre-profile behaviour, unchanged: the
whole user's record.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa


@dataclass(frozen=True)
class Scope:
    """Tenancy for one read: always a user, optionally one of her profiles."""

    user_id: UUID
    profile_id: UUID | None = None

    @classmethod
    def whole_user(cls, user_id: UUID) -> "Scope":
        """Every profile of this user. What every read did before profiles."""
        return cls(user_id=user_id, profile_id=None)

    def where(self, model: Any) -> list:
        """SQL conditions for `model` (Document, Chunk, Entity, Briefing...).

        Returns a list so callers can splat it into `.where(*scope.where(X))`
        alongside their own conditions.
        """
        conditions: list = [model.user_id == self.user_id]
        if self.profile_id is not None:
            conditions.append(
                sa.or_(
                    model.profile_id == self.profile_id,
                    model.profile_id.is_(None),
                )
            )
        return conditions

    def __str__(self) -> str:  # log-friendly, no PII beyond the ids
        return f"user={self.user_id} profile={self.profile_id or 'all'}"
