from fastapi import APIRouter
from src.routers.v1 import auth, clubs, applications, members, posts, notifications, recommendations, boards, platform

router = APIRouter()

router.include_router(auth.router)
router.include_router(clubs.router)
router.include_router(applications.router)
router.include_router(members.router)
router.include_router(posts.router)
router.include_router(notifications.router)
router.include_router(recommendations.router)
router.include_router(boards.router)
router.include_router(platform.router)
