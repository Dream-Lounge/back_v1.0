from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.dependencies import require_super_admin
from src.db.session import get_db
from src.schemas.platform import PlatformRoleCreate, PlatformRoleResponse
from src.services import platform_service

router = APIRouter(prefix="/platform/roles", tags=["platform"])


@router.get("", response_model=list[PlatformRoleResponse])
def list_platform_roles(
    db: Session = Depends(get_db), current_user=Depends(require_super_admin)
):
    return platform_service.list_roles(db)


@router.post("", response_model=PlatformRoleResponse, status_code=status.HTTP_201_CREATED)
def grant_platform_role(
    body: PlatformRoleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    try:
        return platform_service.grant_role(db, current_user.id, body.user_id, body.role)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/{role_id}", response_model=PlatformRoleResponse)
def revoke_platform_role(
    role_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    try:
        return platform_service.revoke_role(db, current_user.id, role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
