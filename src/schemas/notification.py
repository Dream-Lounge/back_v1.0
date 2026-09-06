from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class NotificationResponse(BaseModel):
    id: str
    noti_type: str
    message: str
    payload: Optional[Any]
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
