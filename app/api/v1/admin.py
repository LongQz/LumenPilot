"""Administrator endpoints used by the LumenPilot test console."""

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Request,
)

from app.api.v1.auth import get_current_admin
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.schemas.auth import AccountInfo
from app.services.account import (
    AccountRow,
    account_service,
)
from app.services.database import database_service
from app.services.lumafeed import lumafeed_service

router = APIRouter()


@router.get("/overview")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["admin"][0])
async def overview(
    request: Request,
    admin: AccountRow = Depends(get_current_admin),
) -> dict[str, Any]:
    """Return a compact operational summary for the administrator dashboard."""
    accounts = await account_service.list_accounts(limit=200)
    tasks: list[dict[str, Any]] = []
    feed_online = True
    try:
        tasks = await lumafeed_service.list_ops_tasks()
    except Exception as error:
        feed_online = False
        logger.exception("admin_lumafeed_overview_failed", error=str(error))

    return {
        "accounts": len(accounts),
        "admins": sum(1 for account in accounts if account.role == "ADMIN"),
        "sessions": await database_service.count_sessions(),
        "pending_tasks": sum(1 for task in tasks if task.get("status") == "PENDING"),
        "lumafeed_online": feed_online,
        "operator": admin.username,
    }


@router.get("/users", response_model=list[AccountInfo])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["admin"][0])
async def list_users(
    request: Request,
    _admin: AccountRow = Depends(get_current_admin),
) -> list[AccountInfo]:
    """List LumenPilot accounts without exposing password hashes."""
    return await account_service.list_accounts(limit=200)


@router.get("/tasks")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["admin"][0])
async def list_tasks(
    request: Request,
    _admin: AccountRow = Depends(get_current_admin),
) -> list[dict[str, Any]]:
    """Read recent human-confirmed LumaFeed operations tasks."""
    return await lumafeed_service.list_ops_tasks()


@router.get("/metrics")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["admin"][0])
async def platform_metrics(
    request: Request,
    days: int = 7,
    _admin: AccountRow = Depends(get_current_admin),
) -> dict[str, Any]:
    """Fetch the same aggregate metrics available to the Agent."""
    return await lumafeed_service.query_overview(days)


@router.get("/merchants")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["admin"][0])
async def merchant_risks(
    request: Request,
    limit: int = 5,
    _admin: AccountRow = Depends(get_current_admin),
) -> list[dict[str, Any]]:
    """Fetch merchant reputation risks for manual verification."""
    return await lumafeed_service.query_merchant_metrics(limit)
