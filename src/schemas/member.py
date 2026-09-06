from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MemberResponse(BaseModel):
    user_id: str
    name: str
    student_id: str
    department: Optional[str]
    email: str
    phone: Optional[str]
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}
