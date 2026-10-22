from datetime import datetime
from typing import Literal

from pydantic import BaseModel


PlatformRoleName = Literal["union_admin", "developer", "super_admin"]


class PlatformRoleCreate(BaseModel):
    user_id: str
    role: PlatformRoleName


class PlatformRoleResponse(BaseModel):
    id: str
    user_id: str
    role: PlatformRoleName
    granted_by: str | None
    granted_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}
