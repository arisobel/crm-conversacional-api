"""Criação do primeiro usuário administrativo, sem SQL manual.

Uso:

    python -m crm_api.admin_cli create-user \\
        --email admin@empresa.com.br --name "Nome Sobrenome" --role ADMIN

A senha é lida de `CRM_SEED_PASSWORD` ou, na ausência dela, solicitada pelo
terminal sem eco. Ela nunca é aceita por argumento de linha de comando, que
ficaria visível na lista de processos e no histórico do shell.
"""

import argparse
import asyncio
import os
import sys
import uuid
from getpass import getpass

from sqlalchemy import select

from crm_api.core.config import get_settings
from crm_api.core.database import create_session_factory
from crm_api.core.passwords import WeakPassword, hash_password, validate_password_policy
from crm_api.models.customer import Tenant
from crm_api.models.user import User, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.services.auth import normalize_email

_PASSWORD_ENV = "CRM_SEED_PASSWORD"


def _read_password() -> str:
    from_env = os.environ.get(_PASSWORD_ENV)
    if from_env:
        return from_env
    password = getpass("Senha: ")
    if password != getpass("Confirme a senha: "):
        raise SystemExit("as senhas não conferem")
    return password


async def _create_user(email: str, full_name: str, role: UserRole) -> None:
    settings = get_settings()
    normalized_email = normalize_email(email)

    password = _read_password()
    try:
        validate_password_policy(
            password,
            email=normalized_email,
            min_length=settings.password_min_length,
        )
    except WeakPassword as error:
        raise SystemExit(f"senha rejeitada: {error}") from error

    engine, session_factory = create_session_factory(settings)
    try:
        async with session_factory() as session:
            tenant = await session.scalar(
                select(Tenant).where(Tenant.slug == settings.tenant_slug)
            )
            if tenant is None:
                raise SystemExit(f"tenant '{settings.tenant_slug}' não encontrado")

            existing = await session.scalar(
                select(User).where(
                    User.tenant_id == tenant.id, User.email == normalized_email
                )
            )
            if existing is not None:
                raise SystemExit(f"usuário '{normalized_email}' já existe neste tenant")

            user = User(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                full_name=full_name,
                email=normalized_email,
                password_hash=hash_password(password),
                role=role,
            )
            session.add(user)
            AuditRepository(session).record(
                action="USER_CREATED",
                entity="users",
                tenant_id=tenant.id,
                entity_id=user.id,
                after={"email": normalized_email, "role": role.value, "source": "admin_cli"},
            )
            await session.commit()
            print(f"usuário {normalized_email} criado com papel {role.value}")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crm-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-user", help="cria um usuário do portal")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument(
        "--role",
        default=UserRole.ADMIN.value,
        choices=[role.value for role in UserRole],
    )

    arguments = parser.parse_args(argv)
    asyncio.run(_create_user(arguments.email, arguments.name, UserRole(arguments.role)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
