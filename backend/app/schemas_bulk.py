"""Request/response bodies for bulk actions on domains, hosting accounts and registrars."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

MAX_BULK_IDS = 500


class BulkDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)
    permanent: bool = False


class BulkDeleteOut(BaseModel):
    deleted: int


def unique_ids(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))
