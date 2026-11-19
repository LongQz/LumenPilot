"""MySQL-backed LumenPilot account service.

Credentials live in LumaFeed's MySQL database in a dedicated table. PostgreSQL
remains the store for chat sessions, checkpoints, long-term memory and vectors,
so account authentication does not affect the Agent persistence layer.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import bcrypt
import pymysql
from pymysql.cursors import DictCursor

from app.core.config import (
    Environment,
    settings,
)
from app.core.logging import logger
from app.schemas.auth import AccountInfo


@dataclass(slots=True)
class AccountRow:
    """Internal account row containing the bcrypt password hash."""

    id: int
    email: str
    username: str | None
    password_hash: str
    role: str
    active: bool
    created_at: datetime
    last_login_at: datetime | None


class AccountService:
    """Create, authenticate and list LumenPilot accounts."""

    table_name = "tb_lumenpilot_account"

    async def initialize(self) -> None:
        """Create the account table and seed local administrator accounts."""
        await asyncio.to_thread(self._initialize_sync)

    def _connect(self) -> pymysql.Connection:
        """Open a short-lived MySQL connection for one account operation."""
        return pymysql.connect(
            host=settings.AUTH_MYSQL_HOST,
            port=settings.AUTH_MYSQL_PORT,
            user=settings.AUTH_MYSQL_USER,
            password=settings.AUTH_MYSQL_PASSWORD,
            database=settings.AUTH_MYSQL_DB,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=5,
        )

    def _initialize_sync(self) -> None:
        """Create and seed the account table without blocking the event loop."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS `{self.table_name}` (
                        `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `email` VARCHAR(191) NOT NULL,
                        `username` VARCHAR(64) NOT NULL,
                        `password_hash` VARCHAR(255) NOT NULL,
                        `role` VARCHAR(16) NOT NULL DEFAULT 'USER',
                        `active` TINYINT(1) NOT NULL DEFAULT 1,
                        `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        `last_login_at` DATETIME NULL,
                        PRIMARY KEY (`id`),
                        UNIQUE KEY `uk_lumenpilot_account_email` (`email`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.statistics
                    WHERE table_schema = DATABASE()
                      AND table_name = %s
                      AND index_name = 'uk_lumenpilot_account_username'
                    LIMIT 1
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone():
                    cursor.execute(f"ALTER TABLE `{self.table_name}` DROP INDEX `uk_lumenpilot_account_username`")
                if settings.ENVIRONMENT != Environment.PRODUCTION:
                    self._seed_admins(cursor)
            connection.commit()
        logger.info("lumenpilot_account_table_ready", table=self.table_name)

    def _seed_admins(self, cursor: Any) -> None:
        """Insert local administrator accounts when they do not exist."""
        admins = [
            ("admin.qzh@lumafeed.local", "qzh-admin", "Admin123!", "ADMIN"),
            ("admin.ops@lumafeed.local", "ops-admin", "OpsAdmin123!", "ADMIN"),
            ("admin.audit@lumafeed.local", "audit-admin", "Audit123!", "ADMIN"),
        ]
        for email, username, password, role in admins:
            cursor.execute(
                f"SELECT `id` FROM `{self.table_name}` WHERE `email` = %s",
                (email,),
            )
            if cursor.fetchone():
                continue
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            cursor.execute(
                f"""
                INSERT INTO `{self.table_name}`
                    (`email`, `username`, `password_hash`, `role`, `active`)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (email, username, password_hash, role),
            )

    async def import_legacy_users(self, users: list[dict[str, Any]]) -> int:
        """Copy existing PostgreSQL users into the new MySQL credential store.

        Existing bcrypt hashes can be migrated without knowing the plaintext
        password, preserving accounts created before the account table existed.
        """
        return await asyncio.to_thread(self._import_legacy_users_sync, users)

    def _import_legacy_users_sync(self, users: list[dict[str, Any]]) -> int:
        """Insert missing legacy users and return the imported count."""
        imported = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for user in users:
                    email = str(user.get("email") or "").lower()
                    password_hash = str(user.get("password_hash") or "")
                    if not email or not password_hash:
                        continue
                    cursor.execute(
                        f"SELECT `id` FROM `{self.table_name}` WHERE `email` = %s LIMIT 1",
                        (email,),
                    )
                    if cursor.fetchone():
                        continue
                    username = str(user.get("username") or email.split("@")[0])[:64]
                    cursor.execute(
                        f"""
                        INSERT INTO `{self.table_name}`
                            (`email`, `username`, `password_hash`, `role`, `active`)
                        VALUES (%s, %s, %s, 'USER', 1)
                        """,
                        (email, username, password_hash),
                    )
                    imported += 1
            connection.commit()
        if imported:
            logger.info("lumenpilot_legacy_accounts_imported", count=imported)
        return imported

    async def register(self, email: str, username: str | None, password_hash: str) -> AccountRow:
        """Create a regular user account."""
        return await asyncio.to_thread(self._register_sync, email, username, password_hash)

    def _register_sync(self, email: str, username: str | None, password_hash: str) -> AccountRow:
        """Persist a regular account and return its internal row."""
        safe_username = (username or email.split("@")[0]).strip()[:64]
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO `{self.table_name}`
                            (`email`, `username`, `password_hash`, `role`, `active`)
                        VALUES (%s, %s, %s, 'USER', 1)
                        """,
                        (email.lower(), safe_username, password_hash),
                    )
                    account_id = cursor.lastrowid
                connection.commit()
        except pymysql.err.IntegrityError as error:
            raise ValueError("Email or username is already registered") from error

        row = self._get_by_id_sync(int(account_id))
        if row is None:
            raise RuntimeError("Account was created but could not be loaded")
        logger.info("lumenpilot_account_created", account_id=row.id, role=row.role)
        return row

    async def authenticate(self, email: str, password: str) -> AccountRow | None:
        """Verify a password and record the successful sign-in time."""
        return await asyncio.to_thread(self._authenticate_sync, email, password)

    def _authenticate_sync(self, email: str, password: str) -> AccountRow | None:
        """Verify credentials against the bcrypt hash stored in MySQL."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT * FROM `{self.table_name}` WHERE `email` = %s LIMIT 1",
                    (email.lower(),),
                )
                raw = cursor.fetchone()
                if not raw or not bool(raw["active"]):
                    return None
                if not bcrypt.checkpw(password.encode("utf-8"), str(raw["password_hash"]).encode("utf-8")):
                    return None
                cursor.execute(
                    f"UPDATE `{self.table_name}` SET `last_login_at` = NOW() WHERE `id` = %s",
                    (raw["id"],),
                )
                raw["last_login_at"] = datetime.now()
            connection.commit()
        return self._to_row(raw)

    async def get_by_email(self, email: str) -> AccountRow | None:
        """Load an account by normalized email."""
        return await asyncio.to_thread(self._get_by_email_sync, email)

    def _get_by_email_sync(self, email: str) -> AccountRow | None:
        """Load an account by email from MySQL."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT * FROM `{self.table_name}` WHERE `email` = %s LIMIT 1",
                    (email.lower(),),
                )
                raw = cursor.fetchone()
        return self._to_row(raw) if raw else None

    def _get_by_id_sync(self, account_id: int) -> AccountRow | None:
        """Load an account by its MySQL primary key."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT * FROM `{self.table_name}` WHERE `id` = %s LIMIT 1",
                    (account_id,),
                )
                raw = cursor.fetchone()
        return self._to_row(raw) if raw else None

    async def list_accounts(self, limit: int = 100) -> list[AccountInfo]:
        """Return safe account records for the admin console."""
        return await asyncio.to_thread(self._list_accounts_sync, limit)

    def _list_accounts_sync(self, limit: int) -> list[AccountInfo]:
        """Load account records without exposing password hashes."""
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT * FROM `{self.table_name}`
                    ORDER BY `created_at` DESC
                    LIMIT %s
                    """,
                    (safe_limit,),
                )
                rows = cursor.fetchall()
        return [self._to_info(self._to_row(row)) for row in rows]

    async def count_accounts(self) -> int:
        """Count all LumenPilot accounts."""
        return await asyncio.to_thread(self._count_accounts_sync)

    def _count_accounts_sync(self) -> int:
        """Read the total account count from MySQL."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS `count` FROM `{self.table_name}`")
                raw = cursor.fetchone()
        return int(raw["count"]) if raw else 0

    def _to_row(self, raw: dict[str, Any]) -> AccountRow:
        """Convert a MySQL mapping to the internal account row."""
        return AccountRow(
            id=int(raw["id"]),
            email=str(raw["email"]),
            username=str(raw["username"]) if raw.get("username") else None,
            password_hash=str(raw["password_hash"]),
            role=str(raw["role"]),
            active=bool(raw["active"]),
            created_at=raw["created_at"],
            last_login_at=raw.get("last_login_at"),
        )

    def _to_info(self, row: AccountRow) -> AccountInfo:
        """Convert an internal row to the public schema."""
        return AccountInfo(
            id=row.id,
            email=row.email,
            username=row.username,
            role=row.role,
            active=row.active,
            created_at=row.created_at,
            last_login_at=row.last_login_at,
        )


account_service = AccountService()
