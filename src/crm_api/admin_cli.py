"""Operações administrativas que não têm tela, sem SQL manual.

    python -m crm_api.admin_cli create-user \\
        --email admin@empresa.com.br --name "Nome Sobrenome" --role ADMIN

    python -m crm_api.admin_cli purge-interactions [--days N] [--dry-run]

    python -m crm_api.admin_cli seed-fibers

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
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository
from crm_api.repositories.textile import TextileRepository
from crm_api.repositories.users import UserRepository
from crm_api.services.auth import normalize_email
from crm_api.services.interactions import InteractionService, RetentionNotConfigured
from crm_api.services.textile import TextileService

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


async def _purge_interactions(days: int | None, dry_run: bool) -> None:
    settings = get_settings()
    retencao = days if days is not None else settings.interaction_retention_days
    if retencao is None:
        raise SystemExit(
            "retenção não definida: informe --days ou CRM_INTERACTION_RETENTION_DAYS"
        )

    engine, session_factory = create_session_factory(settings)
    try:
        async with session_factory() as session:
            tenant = await session.scalar(
                select(Tenant).where(Tenant.slug == settings.tenant_slug)
            )
            if tenant is None:
                raise SystemExit(f"tenant '{settings.tenant_slug}' não encontrado")

            service = InteractionService(
                session=session,
                interactions=InteractionRepository(session),
                portfolio=CustomerPortfolioRepository(session),
                audit=AuditRepository(session),
            )
            try:
                removidas = await service.purge(
                    tenant_id=tenant.id, retention_days=retencao
                )
            except RetentionNotConfigured as error:
                raise SystemExit(str(error)) from error

            if dry_run:
                # O expurgo já rodou dentro da transação; desfazê-la devolve o
                # número real de linhas atingidas sem apagar nada.
                await session.rollback()
                print(f"[dry-run] {removidas} interações seriam removidas ({retencao} dias)")
                return
            await session.commit()
            print(f"{removidas} interações removidas (retenção de {retencao} dias)")
    finally:
        await engine.dispose()


async def _seed_fibers() -> int:
    """Semeia as fibras reconhecidas pelo tenant.

    Idempotente: rodar de novo não duplica nem sobrescreve. O que já existe é
    deixado como está, inclusive se alguém tiver corrigido o nome pela mão — o
    seed semeia, não normaliza.
    """
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    try:
        async with session_factory() as session:
            tenant = await session.scalar(
                select(Tenant).where(Tenant.slug == settings.tenant_slug)
            )
            if tenant is None:
                raise SystemExit(f"tenant '{settings.tenant_slug}' não encontrado")

            servico = TextileService(
                textile=TextileRepository(session), audit=AuditRepository(session)
            )
            criadas = await servico.seed_fibers(tenant_id=tenant.id)
            await session.commit()

            if not criadas:
                print("nenhuma fibra nova; o cadastro já estava completo")
                return 0
            for fibra in criadas:
                print(f"{fibra.code:<4} {fibra.name}")
            print(f"{len(criadas)} fibra(s) cadastrada(s)")
            return 0
    finally:
        await engine.dispose()


async def _check_whatsapp_identities() -> int:
    """Prova que um telefone não é usuário e contato de cliente ao mesmo tempo.

    A invariante atravessa duas tabelas e nenhum índice a alcança. Os serviços
    de escrita a garantem no cadastro; este comando é o que a verifica depois,
    contra o que já está gravado — inclusive o que entrou antes da `0009`.

    Reporta também os usuários sem telefone: com a autorização do representante
    digitada no painel do Gateway, um cadastro sem número aqui produz um
    representante que o Gateway atende e o CRM não reconhece.
    """
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    try:
        async with session_factory() as session:
            tenant = await session.scalar(
                select(Tenant).where(Tenant.slug == settings.tenant_slug)
            )
            if tenant is None:
                raise SystemExit(f"tenant '{settings.tenant_slug}' não encontrado")

            users = UserRepository(session)
            colisoes = await users.list_whatsapp_collisions(tenant.id)
            sem_telefone = await users.list_active_without_whatsapp(tenant.id)

            for telefone in colisoes:
                print(f"COLISÃO {telefone} é usuário do portal e contato de cliente")
            for nome, email in sem_telefone:
                print(f"SEM WHATSAPP {nome} <{email}> não será reconhecido pelo CRM")

            if not colisoes and not sem_telefone:
                print("nenhuma divergência de identidade de WhatsApp")
                return 0
            # Colisão é erro; ausência de telefone é aviso. Só a primeira
            # justifica falhar um agendamento.
            return 1 if colisoes else 0
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

    purge = subparsers.add_parser(
        "purge-interactions", help="remove interações fora da política de retenção"
    )
    purge.add_argument("--days", type=int, default=None)
    purge.add_argument("--dry-run", action="store_true")

    subparsers.add_parser(
        "check-whatsapp-identities",
        help="verifica colisões de telefone entre usuários e contatos de cliente",
    )

    subparsers.add_parser(
        "seed-fibers",
        help="cadastra as fibras têxteis reconhecidas pelo tenant (idempotente)",
    )

    arguments = parser.parse_args(argv)
    if arguments.command == "purge-interactions":
        asyncio.run(_purge_interactions(arguments.days, arguments.dry_run))
        return 0
    if arguments.command == "check-whatsapp-identities":
        return asyncio.run(_check_whatsapp_identities())
    if arguments.command == "seed-fibers":
        return asyncio.run(_seed_fibers())

    asyncio.run(_create_user(arguments.email, arguments.name, UserRole(arguments.role)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
