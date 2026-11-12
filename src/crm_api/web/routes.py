"""Páginas do portal do representante.

Camada fina: cada rota valida o CSRF, chama os mesmos serviços que a API usa e
traduz o resultado em redirecionamento. Nenhuma regra de negócio vive aqui.
"""

import csv
import hashlib
import io
import re
import tempfile
import uuid
from calendar import Calendar
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, build_auth_service
from crm_api.api.scoping import scope_for
from crm_api.core.config import Settings
from crm_api.core.database import get_session
from crm_api.core.numbers import InvalidDecimal, parse_decimal
from crm_api.core.passwords import WeakPassword
from crm_api.core.states import InvalidStateCode, normalize_state_code
from crm_api.imports.price_table import import_price_table
from crm_api.models.assistant_settings import (
    AssistantOrganizationSettings,
    AssistantRepresentativeCapability,
    AssistantRepresentativeSettings,
    ConversationBehaviorSettings,
)
from crm_api.models.customer import Customer, Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.customer_intake import CustomerIntake, IntakeStatus
from crm_api.models.interaction import (
    GATEWAY_SOURCE,
    NOTE_CHANNELS,
    CustomerInteraction,
    InteractionDirection,
)
from crm_api.models.pricing import AvailabilityStatus, PriceList, PriceListSourceFile
from crm_api.models.reminder import (
    ReminderKind,
    ReminderOrigin,
    ReminderStatus,
    RepresentativeReminder,
)
from crm_api.models.tax import IcmsRule
from crm_api.models.user import User, UserRole
from crm_api.models.whatsapp_connection import WhatsappConnectionStatus
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.catalog import CatalogRepository, ProductFilters
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customer_intakes import CustomerIntakeRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.repositories.price_lists import PriceListRepository
from crm_api.repositories.reminders import ReminderRepository
from crm_api.repositories.users import SessionRepository, UserRepository
from crm_api.repositories.whatsapp_campaigns import WhatsappCampaignRepository
from crm_api.repositories.whatsapp_connections import WhatsappConnectionRepository
from crm_api.services.assistant_monitoring import assistant_monitoring_snapshot
from crm_api.services.assistant_policy import REPRESENTATIVE_CAPABILITIES
from crm_api.services.auth import AuthenticationFailed, normalize_email
from crm_api.services.catalog import (
    ArticleNotFound,
    BasePriceRequired,
    CatalogService,
    DuplicateFamily,
    DuplicateGroup,
    DuplicateSku,
    FamilyNotFound,
    FamilyRequired,
    GroupNotFound,
    GroupRequired,
    IncompleteArticle,
    InvalidBasePrice,
    ProductNotInCatalog,
    SkuLocked,
)
from crm_api.services.customer_admin import (
    ContactNotFound,
    CustomerAdminService,
    DefaultLocationRequired,
    DuplicateDocument,
    DuplicatePreferredProduct,
    DuplicateWhatsapp,
    LocationNotFound,
    PreferredProductNotFound,
    ProductNotFound,
)
from crm_api.services.customer_intake import (
    BlankField,
    CustomerIntakeService,
    IntakeAlreadyResolved,
    IntakeNotFound,
)
from crm_api.services.customer_intake import (
    WhatsappAlreadyUsed as IntakeWhatsappAlreadyUsed,
)
from crm_api.services.customer_price_list import (
    CustomerPriceListService,
    LocationUnavailable,
    PricesUnavailable,
)
from crm_api.services.customers import InvalidWhatsappNumber
from crm_api.services.gateway_whatsapp_onboarding import (
    GatewayOnboardingError,
    GatewayWhatsappOnboardingClient,
)
from crm_api.services.icms import (
    AmbiguousIcmsRule,
    ConversionMode,
    IcmsResolver,
    IcmsRuleNotFound,
    InvalidTaxRate,
    OriginNotConfigured,
)
from crm_api.services.interactions import (
    EmptyNote,
    InteractionService,
    NotEditable,
    NoteNotFound,
    NoteNotOwned,
    UnknownNoteChannel,
)
from crm_api.services.portfolio import CustomerNotInScope, InvalidOwner, PortfolioService
from crm_api.services.price_publication import (
    BatchNotFound,
    BatchNotPublishable,
    PricePublicationService,
)
from crm_api.services.users import (
    EmailAlreadyUsed,
    UnsafeUserChange,
    UserNotFound,
    UserService,
    WhatsappAlreadyUsed,
    WrongCurrentPassword,
)
from crm_api.services.whatsapp_connections import (
    ConnectionForbidden,
    ConnectionNotFound,
    WhatsappConnectionService,
    retry_action_for,
)
from crm_api.web.csrf import CSRF_FIELD_NAME, csrf_is_valid
from crm_api.web.dependencies import LOGIN_PATH, PortalRedirect, portal_user
from crm_api.web.rendering import redirect, render

router = APIRouter(prefix="/portal", tags=["Portal"])

_MANAGEMENT_ROLES = (UserRole.ADMIN, UserRole.MANAGER)
_CustomerForm = Annotated[str | None, Form()]

# Recortes de "quem falou comigo recentemente" oferecidos pelo filtro. Calculados
# na requisição para que a janela acompanhe o dia, não o momento do import.
_JANELAS_DE_CONTATO = {"30": 30, "90": 90}

# Quantas interações a ficha mostra antes de exigir paginação.
_TIMELINE_NA_FICHA = 20

# Mapeia exceções de domínio para códigos de mensagem. Uma tabela em vez de
# `except` repetido em cada rota: acrescentar um erro novo é uma linha aqui.
_CODIGOS: list[tuple[type[Exception], str]] = [
    (CustomerNotInScope, "nao-encontrado"),
    (ContactNotFound, "nao-encontrado"),
    (LocationNotFound, "nao-encontrado"),
    (UserNotFound, "nao-encontrado"),
    (PreferredProductNotFound, "nao-encontrado"),
    (BatchNotFound, "nao-encontrado"),
    (FamilyNotFound, "nao-encontrado"),
    (ArticleNotFound, "nao-encontrado"),
    (IncompleteArticle, "artigo-incompleto"),
    (DuplicateSku, "sku-duplicado"),
    (DuplicateFamily, "familia-duplicada"),
    (SkuLocked, "sku-travado"),
    (FamilyRequired, "familia-obrigatoria"),
    (BasePriceRequired, "preco-obrigatorio"),
    (InvalidBasePrice, "preco-invalido"),
    (InvalidDecimal, "preco-invalido"),
    (InvalidStateCode, "uf-invalida"),
    (DuplicateDocument, "documento-duplicado"),
    (DuplicateWhatsapp, "telefone-duplicado"),
    (IntakeWhatsappAlreadyUsed, "telefone-em-uso"),
    (IntakeNotFound, "nao-encontrado"),
    (IntakeAlreadyResolved, "intake-ja-resolvido"),
    (BlankField, "campo-obrigatorio"),
    (InvalidWhatsappNumber, "telefone-invalido"),
    (DefaultLocationRequired, "padrao-obrigatoria"),
    (InvalidOwner, "titular-invalido"),
    (EmailAlreadyUsed, "email-duplicado"),
    # A colisão que atravessa `users` e `customer_contacts`. A API interna já a
    # traduzia para 409; o portal não a conhecia e caía no `raise` final de
    # `_codigo_do_erro`, virando 500 numa recusa de negócio correta.
    (WhatsappAlreadyUsed, "telefone-em-uso"),
    (WeakPassword, "senha-fraca"),
    (UnsafeUserChange, "alteracao-insegura"),
    (ProductNotFound, "produto-inexistente"),
    (DuplicatePreferredProduct, "preferido-duplicado"),
    (BatchNotPublishable, "lote-nao-publicavel"),
    (IcmsRuleNotFound, "sem-regra-icms"),
    (AmbiguousIcmsRule, "regra-ambigua"),
    (OriginNotConfigured, "sem-origem"),
    (LocationUnavailable, "sem-localidade"),
    (PricesUnavailable, "sem-competencia"),
    (InvalidTaxRate, "aliquota-invalida"),
    (WrongCurrentPassword, "senha-atual-errada"),
    (GroupRequired, "grupo-sem-nome"),
    (DuplicateGroup, "grupo-duplicado"),
    (GroupNotFound, "grupo-inexistente"),
    (ProductNotInCatalog, "produto-inexistente"),
    (EmptyNote, "nota-vazia"),
    (UnknownNoteChannel, "nota-meio-invalido"),
    (NoteNotFound, "nota-inexistente"),
    (NotEditable, "nota-nao-editavel"),
    (NoteNotOwned, "nota-de-outro"),
]


def _janela_de_contato(contato: str | None) -> datetime | None:
    dias = _JANELAS_DE_CONTATO.get(contato or "")
    return None if dias is None else datetime.now(UTC) - timedelta(days=dias)


def _codigo_do_erro(error: Exception) -> str:
    for tipo, codigo in _CODIGOS:
        if isinstance(error, tipo):
            return codigo
    raise error


# Moradia definitiva em `web/rendering.py`, compartilhada com o roteador de
# campanhas. Os nomes privados continuam aqui como alias para não reescrever as
# dezenas de chamadas deste módulo.
_redirect = redirect
_render = render


def _admin_service(request: Request, session: AsyncSession) -> CustomerAdminService:
    return CustomerAdminService(
        portfolio=CustomerPortfolioRepository(session),
        admin=CustomerAdminRepository(session),
        audit=AuditRepository(session),
    )


def _catalog_service(session: AsyncSession) -> CatalogService:
    return CatalogService(catalog=CatalogRepository(session), audit=AuditRepository(session))


def _portfolio_service(session: AsyncSession) -> PortfolioService:
    return PortfolioService(
        portfolio=CustomerPortfolioRepository(session),
        users=UserRepository(session),
        audit=AuditRepository(session),
    )


def _user_service(request: Request, session: AsyncSession) -> UserService:
    return UserService(
        users=UserRepository(session),
        sessions=SessionRepository(session),
        audit=AuditRepository(session),
        settings=request.app.state.settings,
    )


def _price_list_service(request: Request, session: AsyncSession) -> CustomerPriceListService:
    return CustomerPriceListService(
        portfolio=CustomerPortfolioRepository(session),
        admin=CustomerAdminRepository(session),
        entries=PriceEntryRepository(session),
        resolver=IcmsResolver(IcmsRuleRepository(session)),
        settings=request.app.state.settings,
    )


def _interaction_service(session: AsyncSession) -> InteractionService:
    return InteractionService(
        session=session,
        interactions=InteractionRepository(session),
        portfolio=CustomerPortfolioRepository(session),
        audit=AuditRepository(session),
    )


def _intake_service(request: Request, session: AsyncSession) -> CustomerIntakeService:
    """Mesmo serviço da porta interna; o portal só apresenta a fila.

    Aceitar por aqui não pode ganhar uma segunda implementação de criação
    de cliente. O serviço reaproveita o cadastro comercial, que já garante
    localidade padrão, carteira, telefone canônico e auditoria.
    """
    admin = CustomerAdminRepository(session)
    audit = AuditRepository(session)
    return CustomerIntakeService(
        intakes=CustomerIntakeRepository(session),
        admin=admin,
        users=UserRepository(session),
        customers=CustomerAdminService(
            portfolio=CustomerPortfolioRepository(session), admin=admin, audit=audit
        ),
        audit=audit,
    )


def _publication_service(session: AsyncSession) -> PricePublicationService:
    return PricePublicationService(
        session=session,
        entries=PriceEntryRepository(session),
        audit=AuditRepository(session),
    )


def _whatsapp_connection_service(
    request: Request, session: AsyncSession
) -> WhatsappConnectionService:
    return WhatsappConnectionService(
        connections=WhatsappConnectionRepository(session),
        users=UserRepository(session),
        audit=AuditRepository(session),
        gateway=GatewayWhatsappOnboardingClient(request.app.state.settings),
    )


async def _designaveis(session: AsyncSession, tenant_id: uuid.UUID) -> list[User]:
    return await UserRepository(session).list_users(tenant_id, active=True, limit=200, offset=0)


# ------------------------------------------------------------------ sessão


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def raiz() -> RedirectResponse:
    return RedirectResponse("/portal/home", status_code=303)


@router.get("/login", include_in_schema=False)
async def pagina_login(
    request: Request,
    m: Annotated[str | None, Query()] = None,
    expirada: Annotated[str | None, Query()] = None,
) -> Response:
    return _render(
        request, "login.html", {"email": None}, mensagem=m or ("expirada" if expirada else None)
    )


@router.post("/login", include_in_schema=False)
async def submeter_login(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    settings: Settings = request.app.state.settings
    if not csrf_is_valid(request, csrf_token):
        return _render(request, "login.html", {"email": email}, mensagem="csrf", status_code=400)

    normalizado = normalize_email(email)
    chave = f"{request.client.host if request.client else 'unknown'}|{normalizado}"
    if not request.app.state.login_rate_limiter.allow(chave):
        return _render(
            request, "login.html", {"email": email}, mensagem="muitas-tentativas", status_code=429
        )

    service = build_auth_service(request, session)
    try:
        emitida = await service.authenticate(
            tenant_slug=settings.tenant_slug,
            email=normalizado,
            password=password,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthenticationFailed:
        # A auditoria da tentativa e a contagem de falhas precisam sobreviver.
        await session.commit()
        return _render(
            request, "login.html", {"email": email}, mensagem="credenciais", status_code=401
        )

    await session.commit()
    resposta = _redirect("/portal/home")
    resposta.set_cookie(
        key=settings.session_cookie_name,
        value=emitida.token,
        max_age=settings.session_absolute_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    return resposta


@router.post("/logout", include_in_schema=False)
async def submeter_logout(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    settings: Settings = request.app.state.settings
    if csrf_is_valid(request, csrf_token):
        await build_auth_service(request, session).logout(
            session_id=current_user.session_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
        )
        await session.commit()

    resposta = _redirect(LOGIN_PATH)
    resposta.delete_cookie(key=settings.session_cookie_name, path="/")
    return resposta


# ---------------------------------------------------------------- carteira


@router.get("/home", include_in_schema=False)
async def pagina_inicio(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    portfolio = CustomerPortfolioRepository(session)
    scope = scope_for(current_user)
    total = await portfolio.count_customers(scope, CustomerFilters())
    active = await portfolio.count_customers(scope, CustomerFilters(active=True))
    without_contact = await portfolio.count_customers(scope, CustomerFilters(interacted=False))
    return _render(request, "home.html", {
        "total_clientes": total, "clientes_ativos": active,
        "clientes_sem_interacao": without_contact,
    }, current_user=current_user)


@router.get("/customers", include_in_schema=False)
async def pagina_carteira(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    busca: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    situacao: Annotated[str | None, Query()] = None,
    titular: Annotated[str | None, Query()] = None,
    contato: Annotated[str | None, Query()] = None,
    secao: Annotated[str | None, Query()] = None,
    mes: Annotated[str | None, Query()] = None,
    dia: Annotated[str | None, Query()] = None,
    agenda_view: Annotated[str | None, Query()] = None,
    intake_id: Annotated[uuid.UUID | None, Query(alias="intake")] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    pode_gerir = current_user.role in _MANAGEMENT_ROLES
    filtros = CustomerFilters(
        state_code=uf.strip().upper() if uf and uf.strip() else None,
        active={"ativos": True, "inativos": False}.get(situacao or ""),
        assigned={"com": True, "sem": False}.get(titular or "") if pode_gerir else None,
        search=busca.strip() if busca and busca.strip() else None,
        interacted=False if contato == "sem" else None,
        interacted_since=_janela_de_contato(contato),
    )
    linhas, total = await _portfolio_service(session).list_customers(
        scope_for(current_user), filtros, limit=200, offset=0
    )
    ultimas = await _interaction_service(session).last_interactions(
        current_user.tenant_id, [cliente.id for cliente, _ in linhas]
    )
    intakes, total_intakes = await _intake_service(request, session).queue(
        scope_for(current_user), actor_role=current_user.role
    )
    selected_intake = next(
        (row for row in intakes if intake_id is not None and row[0].id == intake_id),
        intakes[0] if intakes else None,
    )
    # A fila exibida acima é paginada; os totais por representante não podem
    # depender das primeiras 50 linhas, ou a carteira ficaria menor justamente
    # quando houvesse mais cadastros aguardando conferência.
    pending_by_owner = {
        owner_id: int(count)
        for owner_id, count in (
            await session.execute(
                select(
                    CustomerIntake.created_by_user_id,
                    func.count(CustomerIntake.id),
                )
                .where(
                    CustomerIntake.tenant_id == current_user.tenant_id,
                    CustomerIntake.status == IntakeStatus.PENDING,
                )
                .group_by(CustomerIntake.created_by_user_id)
            )
        ).all()
    }
    sao_paulo = ZoneInfo("America/Sao_Paulo")
    agora_local = datetime.now(UTC).astimezone(sao_paulo)
    hoje = agora_local.date()
    try:
        cursor_mes = (
            datetime.strptime(f"{mes}-01", "%Y-%m-%d").date()
            if mes
            else hoje.replace(day=1)
        )
    except ValueError:
        cursor_mes = hoje.replace(day=1)
    proximo_mes = (cursor_mes.replace(day=28) + timedelta(days=4)).replace(day=1)
    mes_inicio_utc = datetime.combine(cursor_mes, datetime.min.time(), sao_paulo).astimezone(UTC)
    mes_fim_utc = datetime.combine(proximo_mes, datetime.min.time(), sao_paulo).astimezone(UTC)
    try:
        dia_selecionado = date.fromisoformat(dia) if dia else hoje
    except ValueError:
        dia_selecionado = hoje
    if dia_selecionado < cursor_mes or dia_selecionado >= proximo_mes:
        dia_selecionado = cursor_mes

    agenda_query = (
        select(RepresentativeReminder, Customer, User)
        .join(Customer, Customer.id == RepresentativeReminder.customer_id)
        .join(User, User.id == RepresentativeReminder.representative_user_id)
        .where(
            RepresentativeReminder.tenant_id == current_user.tenant_id,
            RepresentativeReminder.status.in_(
                (ReminderStatus.PENDING_CONFIRMATION.value, ReminderStatus.CONFIRMED.value)
            ),
            RepresentativeReminder.due_at >= mes_inicio_utc,
            RepresentativeReminder.due_at < mes_fim_utc,
        )
        .order_by(RepresentativeReminder.due_at)
        .limit(100)
    )
    if not pode_gerir:
        agenda_query = agenda_query.where(
            RepresentativeReminder.representative_user_id == current_user.user_id
        )
    agenda_rows = (await session.execute(agenda_query)).all()
    agenda = [
        {
            "reminder": reminder,
            "customer": customer,
            "representative": representative,
            "due_local": (
                reminder.due_at.replace(tzinfo=UTC)
                if reminder.due_at.tzinfo is None
                else reminder.due_at
            ).astimezone(sao_paulo),
        }
        for reminder, customer, representative in agenda_rows
    ]
    agenda_do_dia = [item for item in agenda if item["due_local"].date() == dia_selecionado]
    notificacoes = [
        item for item in agenda
        if item["due_local"] >= agora_local and item["reminder"].notified_at is None
    ]
    contagem_por_dia: dict[date, int] = {}
    for item in agenda:
        data_item = item["due_local"].date()
        contagem_por_dia[data_item] = contagem_por_dia.get(data_item, 0) + 1
    calendario = [
        [
            {
                "date": data,
                "iso": data.isoformat(),
                "day": data.day,
                "in_month": data.month == cursor_mes.month,
                "today": data == hoje,
                "selected": data == dia_selecionado,
                "count": contagem_por_dia.get(data, 0),
            }
            for data in semana
        ]
        for semana in Calendar(firstweekday=6).monthdatescalendar(cursor_mes.year, cursor_mes.month)
    ]
    ids_visiveis = [cliente.id for cliente, _ in linhas]
    contatos_ativos = 0
    if ids_visiveis:
        contatos_ativos = int(await session.scalar(
            select(func.count(CustomerContact.id)).where(
                CustomerContact.tenant_id == current_user.tenant_id,
                CustomerContact.customer_id.in_(ids_visiveis),
                CustomerContact.active.is_(True),
            )
        ) or 0)
    nomes_meses = (
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    )
    sete_dias = hoje + timedelta(days=7)
    representantes = await UserRepository(session).list_users(
        current_user.tenant_id,
        role=UserRole.REPRESENTATIVE,
        active=True,
        limit=200,
        offset=0,
    )
    if not pode_gerir:
        representantes = [item for item in representantes if item.id == current_user.user_id]
    representantes_resumo = []
    for representante in representantes:
        clientes_rep = int(await session.scalar(
            select(func.count(Customer.id)).where(
                Customer.tenant_id == current_user.tenant_id,
                Customer.owner_user_id == representante.id,
            )
        ) or 0)
        contatos_rep = int(await session.scalar(
            select(func.count(CustomerContact.id))
            .join(Customer, Customer.id == CustomerContact.customer_id)
            .where(
                Customer.tenant_id == current_user.tenant_id,
                Customer.owner_user_id == representante.id,
                CustomerContact.active.is_(True),
            )
        ) or 0)
        uf_rep = await session.scalar(
            select(Customer.state_code)
            .where(
                Customer.tenant_id == current_user.tenant_id,
                Customer.owner_user_id == representante.id,
            )
            .order_by(Customer.state_code)
            .limit(1)
        )
        pending_rep = pending_by_owner.get(representante.id, 0)
        representantes_resumo.append({
            "id": str(representante.id),
            "name": representante.full_name,
            "state_code": uf_rep or "—",
            # Um intake pendente já pertence à fila comercial do representante,
            # embora ainda não seja cliente ativo nem autorize o telefone.
            "customers": clientes_rep + pending_rep,
            "confirmed_customers": clientes_rep,
            "contacts": contatos_rep,
            "pending_intakes": pending_rep,
        })
    if pode_gerir:
        sem_titular = int(await session.scalar(
            select(func.count(Customer.id)).where(
                Customer.tenant_id == current_user.tenant_id,
                Customer.owner_user_id.is_(None),
            )
        ) or 0)
        sem_titular_contatos = int(await session.scalar(
            select(func.count(CustomerContact.id))
            .join(Customer, Customer.id == CustomerContact.customer_id)
            .where(
                Customer.tenant_id == current_user.tenant_id,
                Customer.owner_user_id.is_(None),
                CustomerContact.active.is_(True),
            )
        ) or 0)
        representantes_resumo.append({
            "id": "sem-titular", "name": "Sem titular", "state_code": "—",
            "customers": sem_titular, "confirmed_customers": sem_titular,
            "contacts": sem_titular_contatos,
            "pending_intakes": 0,
        })
    if busca and busca.strip():
        termo_representante = busca.strip().casefold()
        representantes_resumo = [
            item for item in representantes_resumo
            if termo_representante in item["name"].casefold()
        ]
    if uf and uf.strip():
        uf_representante = uf.strip().upper()
        representantes_resumo = [
            item for item in representantes_resumo
            if item["state_code"] == uf_representante
        ]
    return _render(
        request,
        "customers.html",
        {
            "clientes": [
                {
                    "customer_id": cliente.id,
                    "legal_name": cliente.legal_name,
                    "trade_name": cliente.trade_name,
                    "state_code": cliente.state_code,
                    "active": cliente.active,
                    "owner": dono,
                    "ultima_interacao": ultimas.get(cliente.id),
                }
                for cliente, dono in linhas
            ],
            "total": total,
            "portfolio_total": total + total_intakes,
            "intakes": intakes,
            "selected_intake": selected_intake,
            "total_intakes": total_intakes,
            "agenda": agenda,
            "agenda_do_dia": agenda_do_dia,
            "notificacoes": notificacoes,
            "agenda_view": "notificacoes" if agenda_view == "notificacoes" else "agenda",
            "total_agenda": len(agenda),
            "contatos_ativos": contatos_ativos,
            "compromissos_hoje": sum(1 for item in agenda if item["due_local"].date() == hoje),
            "compromissos_sete_dias": sum(
                1 for item in agenda if hoje <= item["due_local"].date() <= sete_dias
            ),
            "calendario": calendario,
            "mes_titulo": f"{nomes_meses[cursor_mes.month]} {cursor_mes.year}",
            "mes_atual": cursor_mes.strftime("%Y-%m"),
            "mes_anterior": (cursor_mes - timedelta(days=1)).strftime("%Y-%m"),
            "mes_seguinte": proximo_mes.strftime("%Y-%m"),
            "dia_selecionado": dia_selecionado,
            "hoje": hoje,
            "secao": secao if secao in {"pre-cadastros", "agenda"} else "clientes",
            "filtros": {
                "busca": busca,
                "uf": uf,
                "situacao": situacao,
                "titular": titular,
                "contato": contato,
            },
            "pode_gerir": pode_gerir,
            "somente_minha": not pode_gerir,
            "representantes_resumo": representantes_resumo,
        },
        current_user=current_user,
        mensagem=m,
    )


@router.get("/customers/representantes/{owner_key}", include_in_schema=False)
async def pagina_carteira_do_representante(
    owner_key: str,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    busca: Annotated[str | None, Query()] = None,
    situacao: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    pode_gerir = current_user.role in _MANAGEMENT_ROLES
    owner = None
    if owner_key == "sem-titular":
        if not pode_gerir:
            return _redirect("/portal/customers", "sem-permissao")
        scope = PortfolioScope(tenant_id=current_user.tenant_id, owner_user_id=None)
        assigned = False
        owner_name = "Sem titular"
    else:
        try:
            owner_id = uuid.UUID(owner_key)
        except ValueError:
            return _redirect("/portal/customers", "nao-encontrado")
        if not pode_gerir and owner_id != current_user.user_id:
            return _redirect("/portal/customers", "sem-permissao")
        owner = await UserRepository(session).get_in_tenant(current_user.tenant_id, owner_id)
        if owner is None or owner.role is not UserRole.REPRESENTATIVE:
            return _redirect("/portal/customers", "nao-encontrado")
        scope = PortfolioScope(tenant_id=current_user.tenant_id, owner_user_id=owner_id)
        assigned = None
        owner_name = owner.full_name

    filtros = CustomerFilters(
        active={"ativos": True, "inativos": False}.get(situacao or ""),
        assigned=assigned,
        search=busca.strip() if busca and busca.strip() else None,
    )
    linhas, total = await _portfolio_service(session).list_customers(
        scope, filtros, limit=300, offset=0
    )
    ids = [customer.id for customer, _ in linhas]
    contatos = int(await session.scalar(
        select(func.count(CustomerContact.id)).where(
            CustomerContact.tenant_id == current_user.tenant_id,
            CustomerContact.customer_id.in_(ids) if ids else CustomerContact.id.is_(None),
            CustomerContact.active.is_(True),
        )
    ) or 0)
    ativos = sum(1 for customer, _ in linhas if customer.active)
    pending_intakes = []
    pending_total = 0
    if owner is not None:
        pending_total = await CustomerIntakeRepository(session).count(
            current_user.tenant_id,
            author_user_id=owner.id,
            status=IntakeStatus.PENDING,
        )
        pending_rows = await CustomerIntakeRepository(session).list(
            current_user.tenant_id,
            author_user_id=owner.id,
            status=IntakeStatus.PENDING,
            limit=300,
            offset=0,
        )
        if situacao in (None, "", "pendentes"):
            pending_intakes = [
                row
                for row in pending_rows
                if not busca or busca.casefold() in row[0].legal_name.casefold()
            ]
    visible_customer_rows = [] if situacao == "pendentes" else linhas
    return _render(
        request,
        "representative_portfolio.html",
        {
            "owner": owner,
            "owner_name": owner_name,
            "owner_key": owner_key,
            "clientes": [
                {"customer": customer, "owner": customer_owner}
                for customer, customer_owner in visible_customer_rows
            ],
            "total": total,
            "portfolio_total": total + pending_total,
            "visible_customer_total": len(visible_customer_rows),
            "pending_total": pending_total,
            "contatos": contatos,
            "ativos": ativos,
            "pending_intakes": pending_intakes,
            "busca": busca,
            "situacao": situacao,
        },
        current_user=current_user,
        mensagem=m,
    )


@router.post("/customers/reminders", include_in_schema=False)
async def criar_compromisso_manual(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    customer_id: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "",
    due_local: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/customers", "csrf")
    try:
        customer_uuid = uuid.UUID(customer_id)
        customer, _ = await _portfolio_service(session).get_customer(
            scope_for(current_user), customer_uuid
        )
        reminder_kind = ReminderKind(kind)
        local_value = datetime.fromisoformat(due_local)
        if local_value.tzinfo is None:
            local_value = local_value.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
        due_at = local_value.astimezone(UTC)
        now = datetime.now(UTC)
        if due_at <= now or due_at > now + timedelta(days=366) or not note.strip():
            raise ValueError
    except (ValueError, CustomerNotInScope):
        return _redirect("/portal/customers", "compromisso-invalido")

    representative_user_id = customer.owner_user_id or current_user.user_id
    due_local_value = due_at.astimezone(ZoneInfo("America/Sao_Paulo"))
    slot_start = due_local_value.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    if await ReminderRepository(session).find_slot_conflict(
        current_user.tenant_id,
        representative_user_id,
        slot_start,
        slot_start + timedelta(hours=1),
    ):
        return _redirect("/portal/customers", "compromisso-conflito")

    reminder = RepresentativeReminder(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        representative_user_id=representative_user_id,
        customer_id=customer.id,
        customer_contact_id=None,
        origin=ReminderOrigin.REPRESENTATIVE.value,
        kind=reminder_kind.value,
        status=ReminderStatus.CONFIRMED.value,
        note=note.strip()[:1000],
        due_at=due_at,
        timezone="America/Sao_Paulo",
        source_wamid=f"portal:{uuid.uuid4()}",
        source_line_reference=None,
    )
    session.add(reminder)
    AuditRepository(session).record(
        action="reminder.created",
        entity="representative_reminder",
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.user_id,
        entity_id=reminder.id,
        after={
            "customer_id": str(customer.id),
            "kind": reminder.kind,
            "due_at": due_at.isoformat(),
        },
    )
    await session.commit()
    return _redirect(
        f"/portal/customers?mes={due_at.astimezone(ZoneInfo('America/Sao_Paulo')):%Y-%m}",
        "compromisso-criado",
    )


@router.post("/customers/reminders/{reminder_id}/status", include_in_schema=False)
async def atualizar_compromisso_manual(
    reminder_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/customers", "csrf")
    statement = select(RepresentativeReminder).where(
        RepresentativeReminder.id == reminder_id,
        RepresentativeReminder.tenant_id == current_user.tenant_id,
    )
    if current_user.role not in _MANAGEMENT_ROLES:
        statement = statement.where(
            RepresentativeReminder.representative_user_id == current_user.user_id
        )
    reminder = await session.scalar(statement)
    if reminder is None:
        return _redirect("/portal/customers", "nao-encontrado")
    if status not in {ReminderStatus.COMPLETED.value, ReminderStatus.CANCELLED.value}:
        return _redirect("/portal/customers", "compromisso-invalido")
    before = reminder.status
    reminder.status = status
    reminder.updated_at = datetime.now(UTC)
    AuditRepository(session).record(
        action="reminder.status.updated",
        entity="representative_reminder",
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.user_id,
        entity_id=reminder.id,
        before={"status": before},
        after={"status": status},
    )
    await session.commit()
    return _redirect("/portal/customers", "compromisso-atualizado")


@router.get("/customers/novo", include_in_schema=False)
async def pagina_novo_cliente(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    pode_gerir = current_user.role in _MANAGEMENT_ROLES
    return _render(
        request,
        "customer_new.html",
        {
            "dados": {},
            "pode_gerir": pode_gerir,
            "representantes": await _designaveis(session, current_user.tenant_id)
            if pode_gerir
            else [],
        },
        current_user=current_user,
        mensagem=m,
    )


@router.post("/customers/novo", include_in_schema=False)
async def criar_cliente(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    legal_name: Annotated[str, Form()],
    state_code: Annotated[str, Form()],
    customer_type: Annotated[str, Form()] = "COMPANY",
    trade_name: _CustomerForm = None,
    document_number: _CustomerForm = None,
    owner_user_id: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/customers/novo", "csrf")

    try:
        cliente = await _admin_service(request, session).create_customer(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
            legal_name=legal_name,
            customer_type=customer_type,
            state_code=state_code,
            trade_name=trade_name,
            document_number=document_number,
            owner_user_id=uuid.UUID(owner_user_id) if owner_user_id else None,
        )
    except Exception as error:  # noqa: BLE001 — reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect("/portal/customers/novo", _codigo_do_erro(error))

    await session.commit()
    return _redirect(f"/portal/customers/{cliente.id}", "cliente-criado")


# ---------------------------------------------------------- pré-cadastros


async def _salvar_pre_cadastro(
    request: Request,
    session: AsyncSession,
    current_user: CurrentUser,
    intake_id: uuid.UUID,
    *,
    legal_name: str | None,
    trade_name: str | None,
    document_number: str | None,
    state_code: str | None,
    whatsapp_e164: str | None,
    contact_name: str | None,
    preferred_products_text: str | None,
    confirmed_field: str | None = None,
) -> None:
    await _intake_service(request, session).update_pending(
        current_user.tenant_id,
        intake_id,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role,
        legal_name=legal_name,
        trade_name=trade_name,
        document_number=document_number,
        state_code=state_code,
        whatsapp_e164=whatsapp_e164,
        contact_name=contact_name,
        preferred_products_text=preferred_products_text,
        confirmed_field=confirmed_field,
        request_id=request.headers.get("x-request-id"),
    )


@router.post("/intakes/{intake_id}/save", include_in_schema=False)
async def salvar_pre_cadastro(
    request: Request,
    intake_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    legal_name: _CustomerForm = None,
    trade_name: _CustomerForm = None,
    document_number: _CustomerForm = None,
    state_code: _CustomerForm = None,
    whatsapp_e164: _CustomerForm = None,
    contact_name: _CustomerForm = None,
    preferred_products_text: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers?secao=pre-cadastros&intake={intake_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    try:
        await _salvar_pre_cadastro(
            request,
            session,
            current_user,
            intake_id,
            legal_name=legal_name,
            trade_name=trade_name,
            document_number=document_number,
            state_code=state_code,
            whatsapp_e164=whatsapp_e164,
            contact_name=contact_name,
            preferred_products_text=preferred_products_text,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))
    await session.commit()
    return _redirect(destino, "intake-salvo")


@router.post("/intakes/{intake_id}/confirm-field", include_in_schema=False)
async def confirmar_campo_pre_cadastro(
    request: Request,
    intake_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    confirmed_field: Annotated[str, Form()],
    legal_name: _CustomerForm = None,
    trade_name: _CustomerForm = None,
    document_number: _CustomerForm = None,
    state_code: _CustomerForm = None,
    whatsapp_e164: _CustomerForm = None,
    contact_name: _CustomerForm = None,
    preferred_products_text: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers?secao=pre-cadastros&intake={intake_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    try:
        await _salvar_pre_cadastro(
            request,
            session,
            current_user,
            intake_id,
            legal_name=legal_name,
            trade_name=trade_name,
            document_number=document_number,
            state_code=state_code,
            whatsapp_e164=whatsapp_e164,
            contact_name=contact_name,
            preferred_products_text=preferred_products_text,
            confirmed_field=confirmed_field,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))
    await session.commit()
    return _redirect(destino, "intake-campo-confirmado")


@router.get("/intakes", include_in_schema=False)
async def pagina_pre_cadastros(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    """Compatibilidade: a fila agora é uma divisão da Carteira."""
    destino = "/portal/customers?secao=pre-cadastros"
    if m:
        destino += f"&m={m}"
    return RedirectResponse(destino, status_code=303)


@router.post("/intakes/{intake_id}/accept", include_in_schema=False)
async def aceitar_pre_cadastro(
    request: Request,
    intake_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    legal_name: _CustomerForm = None,
    state_code: _CustomerForm = None,
    trade_name: _CustomerForm = None,
    document_number: _CustomerForm = None,
    whatsapp_e164: _CustomerForm = None,
    contact_name: _CustomerForm = None,
    preferred_products_text: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/customers?secao=pre-cadastros", "csrf")

    try:
        await _salvar_pre_cadastro(
            request,
            session,
            current_user,
            intake_id,
            legal_name=legal_name,
            trade_name=trade_name,
            document_number=document_number,
            state_code=state_code,
            whatsapp_e164=whatsapp_e164,
            contact_name=contact_name,
            preferred_products_text=preferred_products_text,
        )
        intake = await _intake_service(request, session).accept(
            current_user.tenant_id,
            intake_id,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
            legal_name=legal_name,
            state_code=state_code,
            trade_name=trade_name,
            document_number=document_number,
            contact_name=contact_name,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect("/portal/customers?secao=pre-cadastros", _codigo_do_erro(error))

    await session.commit()
    # O CHECK da tabela exige customer_id em todo intake ACCEPTED. Mantemos a
    # guarda para que uma regressão nessa invariante não produza uma URL /None.
    if intake.customer_id is None:
        raise RuntimeError("accepted customer intake has no customer")
    return _redirect(f"/portal/customers/{intake.customer_id}", "intake-aceito")


@router.post("/intakes/{intake_id}/reject", include_in_schema=False)
async def rejeitar_pre_cadastro(
    request: Request,
    intake_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    reason: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/customers?secao=pre-cadastros", "csrf")

    try:
        await _intake_service(request, session).reject(
            current_user.tenant_id,
            intake_id,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
            reason=reason,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect("/portal/customers?secao=pre-cadastros", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/customers?secao=pre-cadastros", "intake-rejeitado")


@router.get("/customers/{customer_id}", include_in_schema=False)
async def pagina_cliente(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    aba: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    escopo = scope_for(current_user)
    servico = _admin_service(request, session)
    portfolio = CustomerPortfolioRepository(session)

    encontrado = await portfolio.get_customer(escopo, customer_id)
    if encontrado is None:
        return _redirect("/portal/customers", "nao-encontrado")
    cliente, dono = encontrado
    contatos = await servico.list_contacts(escopo, customer_id)
    contato_assistente = next((item for item in contatos if item.active and item.is_primary), None)
    contato_assistente = contato_assistente or next(
        (item for item in contatos if item.active), None
    )
    estado_assistente = "INDISPONIVEL"
    if dono is not None and contato_assistente is not None:
        conexao_assistente = await WhatsappConnectionRepository(session).get_for_representative(
            current_user.tenant_id, dono.id
        )
        if (
            conexao_assistente is not None
            and conexao_assistente.status is WhatsappConnectionStatus.CONNECTED
            and conexao_assistente.gateway_line_reference
        ):
            try:
                estado_assistente = await GatewayWhatsappOnboardingClient(
                    request.app.state.settings
                ).handoff_status(
                    gateway_line_reference=conexao_assistente.gateway_line_reference,
                    contact_phone_e164=contato_assistente.whatsapp_e164,
                )
            except Exception:  # A ficha do cliente não pode depender do Gateway para abrir.
                estado_assistente = "INDISPONIVEL"

    pode_gerir = current_user.role in _MANAGEMENT_ROLES
    interacoes, total_interacoes = await _interaction_service(session).timeline(
        escopo, customer_id, limit=_TIMELINE_NA_FICHA, offset=0
    )
    preferidos = await servico.list_preferred_products(escopo, customer_id)
    ja_preferidos = {produto.id for _, produto, _ in preferidos}

    # Um preferido sem preço na competência simplesmente não sai na lista, e
    # sem aviso ninguém descobre por quê — é o que acontece com o artigo que
    # acabou de ser cadastrado e cujo lote ainda não foi publicado.
    entradas = PriceEntryRepository(session)
    competencia = await entradas.latest_month(current_user.tenant_id, at=datetime.now(UTC).date())
    com_preco = (
        {
            entrada.product_id
            for entrada, _, _ in await entradas.list_items_for_products(
                current_user.tenant_id, competencia, list(ja_preferidos)
            )
        }
        if competencia
        else set()
    )

    # As campanhas de que este cliente participou. O escopo é o mesmo da lista
    # de campanhas: um representante vê as de que é responsável, mesmo na ficha
    # de um cliente seu — quem criou a campanha é que responde por ela.
    campanhas_do_cliente = await WhatsappCampaignRepository(session).campaigns_of_customer(
        current_user.tenant_id,
        customer_id,
        representative_user_id=(
            current_user.user_id if current_user.role is UserRole.REPRESENTATIVE else None
        ),
    )

    return _render(
        request,
        "customer_detail.html",
        {
            "cliente": cliente,
            "aba": aba if aba in {"cadastro", "produtos", "historico"} else "cadastro",
            "titular": dono,
            "campanhas": campanhas_do_cliente,
            "contatos": contatos,
            "estado_assistente": estado_assistente,
            "localidades": await servico.list_locations(escopo, customer_id),
            "preferidos": preferidos,
            "catalogo": [
                (produto, familia)
                for produto, familia in await CustomerAdminRepository(session).list_products(
                    current_user.tenant_id
                )
                if produto.id not in ja_preferidos
            ],
            "familias": await CatalogRepository(session).list_families(current_user.tenant_id)
            if pode_gerir
            else [],
            "competencia": competencia,
            "sem_preco": ja_preferidos - com_preco,
            "interacoes": interacoes,
            "total_interacoes": total_interacoes,
            "timeline_truncada": total_interacoes > len(interacoes),
            "meios_de_nota": NOTE_CHANNELS,
            # Quem pode corrigir cada nota. O autor corrige a dele; gestão
            # corrige qualquer uma. A tela só esconde o que o serviço recusaria.
            "pode_editar_nota": (
                lambda nota: nota.actor_user_id == current_user.user_id or pode_gerir
            ),
            "pode_gerir": pode_gerir,
            "representantes": await _designaveis(session, current_user.tenant_id)
            if pode_gerir
            else [],
        },
        current_user=current_user,
        mensagem=m,
    )


@router.post("/customers/{customer_id}/assistant/resume", include_in_schema=False)
async def retomar_assistente_do_cliente(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Comando do portal; a sessão nunca é enviada ao Gateway."""
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    escopo = scope_for(current_user)
    encontrado = await CustomerPortfolioRepository(session).get_customer(escopo, customer_id)
    if encontrado is None:
        return _redirect("/portal/customers", "nao-encontrado")
    cliente, titular = encontrado
    if titular is None:
        return _redirect(destino, "assistente-sem-titular")

    conexao = await WhatsappConnectionRepository(session).get_for_representative(
        current_user.tenant_id, titular.id
    )
    contatos = await _admin_service(request, session).list_contacts(escopo, customer_id)
    contato = next((item for item in contatos if item.active and item.is_primary), None)
    contato = contato or next((item for item in contatos if item.active), None)
    if (
        conexao is None
        or conexao.status is not WhatsappConnectionStatus.CONNECTED
        or not conexao.gateway_line_reference
        or contato is None
    ):
        return _redirect(destino, "assistente-indisponivel")

    try:
        status = await GatewayWhatsappOnboardingClient(request.app.state.settings).resume_handoff(
            gateway_line_reference=conexao.gateway_line_reference,
            contact_phone_e164=contato.whatsapp_e164,
            idempotency_key=uuid.uuid4().hex,
        )
    except Exception as error:  # o Gateway é externo ao portal; a tela fica utilizável.
        request.app.logger.warning("portal handoff resume failed: %s", error)
        return _redirect(destino, "assistente-indisponivel")
    return _redirect(
        destino,
        "assistente-retomado" if status == "RESUMED" else "assistente-ja-ativo",
    )


@router.post("/customers/{customer_id}/notas", include_in_schema=False)
async def registrar_nota(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    summary: Annotated[str, Form()],
    channel: Annotated[str, Form()],
    direction: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}?aba=historico"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _interaction_service(session).register_note(
            scope=scope_for(current_user),
            customer_id=customer_id,
            author_user_id=current_user.user_id,
            summary=summary,
            channel=channel,
            direction=InteractionDirection(direction) if direction else None,
        )
    except ValueError:
        await session.rollback()
        return _redirect(destino, "nota-sentido-invalido")
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "nota-registrada")


@router.post("/customers/{customer_id}/notas/{note_id}", include_in_schema=False)
async def editar_nota(
    request: Request,
    customer_id: uuid.UUID,
    note_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    summary: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}?aba=historico"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _interaction_service(session).edit_note(
            scope=scope_for(current_user),
            note_id=note_id,
            editor_user_id=current_user.user_id,
            editor_role=current_user.role,
            summary=summary,
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "nota-corrigida")


@router.post("/customers/{customer_id}", include_in_schema=False)
async def salvar_cliente(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    legal_name: Annotated[str, Form()],
    state_code: Annotated[str, Form()],
    customer_type: Annotated[str, Form()] = "COMPANY",
    trade_name: _CustomerForm = None,
    document_number: _CustomerForm = None,
    active: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _admin_service(request, session).update_customer(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            legal_name=legal_name,
            customer_type=customer_type,
            trade_name=trade_name or "",
            document_number=document_number or "",
            state_code=state_code,
            # Checkbox ausente no corpo significa desmarcado.
            active=active == "1",
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "cliente-salvo")


@router.post("/customers/{customer_id}/owner", include_in_schema=False)
async def alterar_titular(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_user_id: _CustomerForm = None,
    reason: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect(destino, "sem-permissao")

    try:
        resultado = await _portfolio_service(session).assign_owner(
            scope_for(current_user),
            customer_id,
            owner_user_id=uuid.UUID(owner_user_id) if owner_user_id else None,
            actor_user_id=current_user.user_id,
            reason=reason or None,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "titular-alterado" if resultado.changed else "titular-sem-mudanca")


# ---------------------------------------------------------------- contatos


@router.post("/customers/{customer_id}/contacts", include_in_schema=False)
async def criar_contato(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str, Form()],
    whatsapp_e164: Annotated[str, Form()],
    is_primary: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _admin_service(request, session).create_contact(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            name=name,
            whatsapp_e164=whatsapp_e164,
            is_primary=is_primary == "1",
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "contato-criado")


@router.post("/customers/{customer_id}/contacts/{contact_id}", include_in_schema=False)
async def salvar_contato(
    request: Request,
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    argumentos: dict[str, bool] = {
        "principal": {"is_primary": True},
        "desativar": {"active": False},
        "ativar": {"active": True},
    }.get(acao, {})
    if not argumentos:
        return _redirect(destino, "nao-encontrado")

    try:
        await _admin_service(request, session).update_contact(
            scope_for(current_user),
            customer_id,
            contact_id,
            actor_user_id=current_user.user_id,
            **argumentos,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "contato-salvo")


# ------------------------------------------------------------- localidades


@router.post("/customers/{customer_id}/locations", include_in_schema=False)
async def criar_localidade(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    label: Annotated[str, Form()],
    state_code: Annotated[str, Form()],
    city: _CustomerForm = None,
    is_default: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _admin_service(request, session).create_location(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            label=label,
            state_code=state_code,
            city=city,
            is_default=is_default == "1",
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "localidade-criada")


@router.post("/customers/{customer_id}/locations/{location_id}", include_in_schema=False)
async def salvar_localidade(
    request: Request,
    customer_id: uuid.UUID,
    location_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    argumentos: dict[str, bool] = {
        "padrao": {"is_default": True},
        "desativar": {"active": False},
        "ativar": {"active": True},
    }.get(acao, {})
    if not argumentos:
        return _redirect(destino, "nao-encontrado")

    try:
        await _admin_service(request, session).update_location(
            scope_for(current_user),
            customer_id,
            location_id,
            actor_user_id=current_user.user_id,
            **argumentos,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "localidade-salva")


# ----------------------------------------------------------- central do assistente

_ASSISTANT_CAPABILITIES = {
    "CRM_REP_SEARCH_PRICE_ITEMS": "Consultar preços de produtos",
    "CRM_REP_LOOKUP_CUSTOMER": "Consultar clientes",
    "CRM_REP_LIST_PORTFOLIO_CUSTOMERS": "Listar e filtrar minha carteira",
    "CRM_REP_GET_CUSTOMER_PRICE_LIST": "Consultar tabela de preços do cliente",
    "CRM_REP_GET_CUSTOMER_CONVERSATION_SUMMARY": "Resumir conversa do cliente",
    "CRM_REP_CREATE_CUSTOMER_INTAKE": "Criar pré-cadastros de clientes",
    "CRM_REP_CREATE_REMINDER": "Criar compromissos e lembretes pessoais",
    "CRM_REP_UPDATE_PRICES": "Propor e confirmar atualizações de preços",
}

_BEHAVIOR_DEFAULT_INSTRUCTIONS = (
    "Converse de forma natural e objetiva. Não repita saudações ou o nome da pessoa "
    "a cada mensagem. Considere as mensagens recentes da conversa. Se não entender, "
    "peça esclarecimento sobre o pedido; não sugira uma tabela ou ação sem relação. "
    "Após uma pausa longa, uma saudação de retorno pode ser apropriada."
)
_BEHAVIOR_TONES = {"cordial", "objetivo", "consultivo"}
_BEHAVIOR_BOTS = {"ASSISTANT", "COEXISTENCE"}


@router.get("/assistant", include_in_schema=False)
async def pagina_assistente(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    tenant_id = current_user.tenant_id
    organization = await session.get(AssistantOrganizationSettings, tenant_id)
    users = (await session.scalars(select(User).where(
        User.tenant_id == tenant_id, User.role == UserRole.REPRESENTATIVE
    ).order_by(User.full_name))).all()
    settings = (await session.scalars(select(AssistantRepresentativeSettings).where(
        AssistantRepresentativeSettings.tenant_id == tenant_id
    ))).all()
    capabilities = (await session.scalars(select(AssistantRepresentativeCapability).where(
        AssistantRepresentativeCapability.tenant_id == tenant_id
    ))).all()
    behaviors = (await session.scalars(select(ConversationBehaviorSettings).where(
        ConversationBehaviorSettings.tenant_id == tenant_id
    ))).all()
    monitoring = await assistant_monitoring_snapshot(session, tenant_id)
    gateway_status = None
    gateway_error = None
    try:
        gateway_status = await GatewayWhatsappOnboardingClient(
            request.app.state.settings
        ).status_overview()
    except GatewayOnboardingError as error:
        gateway_error = str(error)
    selected: dict[uuid.UUID, set[str]] = {user.id: set() for user in users}
    for capability in capabilities:
        if capability.user_id in selected:
            selected[capability.user_id].add(capability.capability_id)
    return _render(request, "assistant.html", {
        "organization": organization,
        "users": users,
        "enabled": {setting.user_id: setting.enabled for setting in settings},
        "selected": selected,
        "capabilities": _ASSISTANT_CAPABILITIES,
        "behaviors": {behavior.bot_kind: behavior for behavior in behaviors},
        "default_instructions": _BEHAVIOR_DEFAULT_INSTRUCTIONS,
        "monitoring": monitoring,
        "gateway_status": gateway_status,
        "gateway_error": gateway_error,
        "enabled_representatives": sum(setting.enabled for setting in settings),
    }, current_user=current_user, mensagem=m)


@router.get("/assistant/unresolved", include_in_schema=False)
async def pagina_mensagens_nao_entendidas(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Exibe lacunas reais de compreensão sem depender de procurar logs."""
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    candidates = list(
        await session.scalars(
            select(CustomerInteraction)
            .where(
                CustomerInteraction.tenant_id == current_user.tenant_id,
                CustomerInteraction.source == GATEWAY_SOURCE,
                CustomerInteraction.direction == InteractionDirection.OUTBOUND,
                CustomerInteraction.payload.is_not(None),
            )
            .order_by(CustomerInteraction.occurred_at.desc())
            .limit(500)
        )
    )
    outcomes = {"FALLBACK", "RECOVERY", "OUT_OF_SCOPE"}
    unresolved = [
        interaction
        for interaction in candidates
        if (interaction.payload or {}).get("outcome") in outcomes
    ][:100]
    source_refs = {
        interaction.external_ref.rsplit(":out:", 1)[0]
        for interaction in unresolved
        if ":out:" in interaction.external_ref
    }
    inbound = {
        interaction.external_ref: interaction
        for interaction in await session.scalars(
            select(CustomerInteraction).where(
                CustomerInteraction.tenant_id == current_user.tenant_id,
                CustomerInteraction.source == GATEWAY_SOURCE,
                CustomerInteraction.external_ref.in_(source_refs),
            )
        )
    } if source_refs else {}
    customer_ids = {item.customer_id for item in unresolved if item.customer_id}
    actor_ids = {item.actor_user_id for item in unresolved if item.actor_user_id}
    customers = {
        item.id: item.legal_name
        for item in await session.scalars(select(Customer).where(Customer.id.in_(customer_ids)))
    } if customer_ids else {}
    actors = {
        item.id: item.full_name
        for item in await session.scalars(select(User).where(User.id.in_(actor_ids)))
    } if actor_ids else {}
    rows = []
    for response in unresolved:
        source_ref = response.external_ref.rsplit(":out:", 1)[0]
        message = inbound.get(source_ref)
        rows.append({
            "occurred_at": (message or response).occurred_at,
            "speaker": customers.get(response.customer_id)
            or actors.get(response.actor_user_id)
            or "Contato identificado",
            "message": message.summary if message else "Mensagem original indisponível",
            "response": response.summary,
            "outcome": (response.payload or {}).get("outcome"),
        })
    return _render(
        request,
        "assistant_unresolved.html",
        {"rows": rows},
        current_user=current_user,
    )


@router.post("/assistant/behavior/{bot_kind}", include_in_schema=False)
async def salvar_comportamento(
    bot_kind: str,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
    tone: Annotated[str, Form()] = "cordial",
    instructions: Annotated[str, Form()] = "",
    context_minutes: Annotated[int, Form()] = 120,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/assistant", "csrf")
    instructions = instructions.strip()
    if (bot_kind not in _BEHAVIOR_BOTS or tone not in _BEHAVIOR_TONES
            or not instructions or len(instructions) > 4000
            or not 15 <= context_minutes <= 1440):
        return _redirect("/portal/assistant", "comportamento-invalido")
    behavior = await session.get(ConversationBehaviorSettings, (current_user.tenant_id, bot_kind))
    before = None if behavior is None else {
        "tone": behavior.tone, "instructions": behavior.instructions,
        "context_minutes": behavior.context_minutes,
    }
    if behavior is None:
        behavior = ConversationBehaviorSettings(tenant_id=current_user.tenant_id, bot_kind=bot_kind)
        session.add(behavior)
    behavior.tone = tone
    behavior.instructions = instructions
    behavior.context_minutes = context_minutes
    behavior.updated_at = datetime.now(UTC)
    AuditRepository(session).record(
        action="conversation.behavior.updated", entity="conversation_behavior_settings",
        tenant_id=current_user.tenant_id, actor_user_id=current_user.user_id,
        before=before, after={"bot_kind": bot_kind, "tone": tone,
                              "instructions": instructions, "context_minutes": context_minutes},
    )
    await session.commit()
    return _redirect("/portal/assistant", "assistente-salvo")


@router.post("/assistant/organization", include_in_schema=False)
async def salvar_assistente_organizacao(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
    enabled: Annotated[bool, Form()] = False,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/assistant", "csrf")
    organization = await session.get(AssistantOrganizationSettings, current_user.tenant_id)
    before = organization.enabled if organization else False
    if organization is None:
        organization = AssistantOrganizationSettings(tenant_id=current_user.tenant_id)
        session.add(organization)
    organization.enabled = enabled
    organization.updated_at = datetime.now(UTC)
    AuditRepository(session).record(
        action="assistant.organization.updated", entity="assistant_organization_settings",
        tenant_id=current_user.tenant_id, actor_user_id=current_user.user_id,
        entity_id=current_user.tenant_id, before={"enabled": before}, after={"enabled": enabled},
    )
    await session.commit()
    return _redirect("/portal/assistant", "assistente-salvo")


@router.post("/assistant/representatives/{user_id}", include_in_schema=False)
async def salvar_assistente_representante(
    user_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
    enabled: Annotated[bool, Form()] = False,
    capabilities: Annotated[list[str] | None, Form()] = None,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/assistant", "csrf")
    tenant_id = current_user.tenant_id
    user = await session.scalar(select(User).where(
        User.id == user_id, User.tenant_id == tenant_id, User.role == UserRole.REPRESENTATIVE
    ))
    chosen = set(capabilities or [])
    if user is None or not chosen <= REPRESENTATIVE_CAPABILITIES:
        return _redirect("/portal/assistant", "nao-encontrado")
    representative = await session.get(AssistantRepresentativeSettings, (tenant_id, user_id))
    previous = (await session.scalars(select(AssistantRepresentativeCapability.capability_id).where(
        AssistantRepresentativeCapability.tenant_id == tenant_id,
        AssistantRepresentativeCapability.user_id == user_id,
    ))).all()
    before = {"enabled": representative.enabled if representative else False,
              "capabilities": sorted(previous)}
    if representative is None:
        representative = AssistantRepresentativeSettings(tenant_id=tenant_id, user_id=user_id)
        session.add(representative)
        await session.flush()
    representative.enabled = enabled
    representative.updated_at = datetime.now(UTC)
    await session.execute(delete(AssistantRepresentativeCapability).where(
        AssistantRepresentativeCapability.tenant_id == tenant_id,
        AssistantRepresentativeCapability.user_id == user_id,
    ))
    session.add_all([AssistantRepresentativeCapability(
        tenant_id=tenant_id, user_id=user_id, capability_id=capability
    ) for capability in sorted(chosen)])
    AuditRepository(session).record(
        action="assistant.representative.updated", entity="assistant_representative_settings",
        tenant_id=tenant_id, actor_user_id=current_user.user_id, entity_id=user_id,
        before=before, after={"enabled": enabled, "capabilities": sorted(chosen)},
    )
    await session.commit()
    return _redirect("/portal/assistant", "assistente-salvo")


# ----------------------------------------------------------- representantes


@router.get("/users", include_in_schema=False)
async def pagina_usuarios(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
    aba: Annotated[str, Query()] = "representantes",
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    usuarios, _ = await _user_service(request, session).list_users(
        tenant_id=current_user.tenant_id, limit=200, offset=0
    )
    if aba not in {"representantes", "usuarios"}:
        aba = "representantes"
    representantes = [usuario for usuario in usuarios if usuario.role is UserRole.REPRESENTATIVE]
    usuarios_internos = [
        usuario for usuario in usuarios if usuario.role is not UserRole.REPRESENTATIVE
    ]
    return _render(
        request,
        "users.html",
        {
            "aba": aba,
            "representantes": representantes,
            "usuarios_internos": usuarios_internos,
            "tamanho_minimo_senha": request.app.state.settings.password_min_length,
        },
        current_user=current_user,
        mensagem=m,
    )


@router.get("/whatsapp/{user_id}", include_in_schema=False)
async def pagina_whatsapp_do_representante(
    user_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if current_user.role is UserRole.REPRESENTATIVE and current_user.user_id != user_id:
        return _redirect("/portal/customers", "sem-permissao")
    if current_user.role not in (UserRole.REPRESENTATIVE, UserRole.ADMIN, UserRole.MANAGER):
        return _redirect("/portal/customers", "sem-permissao")
    try:
        representative = await UserRepository(session).get_in_tenant(
            current_user.tenant_id, user_id
        )
        if representative is None or representative.role is not UserRole.REPRESENTATIVE:
            raise ConnectionNotFound
        connection = await _whatsapp_connection_service(request, session).get(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            role=current_user.role,
            representative_id=user_id,
            refresh=False,
        )
    except (ConnectionNotFound, ConnectionForbidden):
        return _redirect("/portal/customers", "nao-encontrado")
    return _render(
        request,
        "whatsapp_connection.html",
        {
            "representative": representative,
            "connection": connection,
            "retry_action": retry_action_for(connection),
        },
        current_user=current_user,
    )


@router.post("/users", include_in_schema=False)
async def criar_usuario(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    full_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[str, Form()] = UserRole.REPRESENTATIVE.value,
    whatsapp_e164: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/users", "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        await _user_service(request, session).create(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            full_name=full_name,
            email=email,
            password=password,
            role=UserRole(role),
            whatsapp_e164=whatsapp_e164 or None,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect("/portal/users", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/users", "usuario-criado")


@router.post("/users/{user_id}", include_in_schema=False)
async def salvar_usuario(
    request: Request,
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/users", "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    if acao not in {"ativar", "desativar"}:
        return _redirect("/portal/users", "nao-encontrado")

    try:
        await _user_service(request, session).set_active(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            active=acao == "ativar",
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect("/portal/users", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/users", "usuario-salvo")


@router.post("/users/{user_id}/editar", include_in_schema=False)
async def editar_usuario(
    request: Request,
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    full_name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    whatsapp_e164: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Edita nome, papel e WhatsApp de um usuário do portal.

    O formulário manda os três campos sempre, com os valores atuais
    preenchidos, então isto é substituição e não remendo. É o que permite
    **limpar** o WhatsApp — a API não consegue, porque o schema dela valida o
    campo contra E.164 e não tem como expressar "apague".
    """
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/users", "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        papel = UserRole(role)
    except ValueError:
        return _redirect("/portal/users", "papel-invalido")

    try:
        await _user_service(request, session).update(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            full_name=full_name,
            # String vazia apaga; `None` deixaria o telefone como está, e o
            # formulário não teria como remover um número digitado errado.
            whatsapp_e164=(whatsapp_e164 or "").strip(),
            role=papel,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect("/portal/users", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/users", "usuario-salvo")


@router.post("/users/{user_id}/password", include_in_schema=False)
async def redefinir_senha(
    request: Request,
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Redefinição pelo `ADMIN`, para quem esqueceu a senha.

    Não exige a senha antiga — quem esqueceu não a tem. O que a torna segura é
    a alçada: só `ADMIN` chega aqui, e a operação derruba todas as sessões do
    usuário e limpa o bloqueio por tentativas.
    """
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/users", "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        await _user_service(request, session).set_password(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            password=password,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect("/portal/users", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/users", "senha-redefinida")


@router.get("/minha-senha", include_in_schema=False)
async def pagina_minha_senha(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    """Troca da própria senha. Aberta a qualquer papel, inclusive representante."""
    return _render(
        request,
        "my_password.html",
        {"minimo": request.app.state.settings.password_min_length},
        current_user=current_user,
        mensagem=m,
    )


@router.post("/minha-senha", include_in_schema=False)
async def trocar_minha_senha(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = "/portal/minha-senha"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    # Conferida aqui e não no serviço: é erro de digitação no formulário, não
    # regra de negócio, e o serviço não deveria conhecer o segundo campo.
    if new_password != confirm_password:
        return _redirect(destino, "senha-nao-confere")

    try:
        await _user_service(request, session).change_own_password(
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            session_id=current_user.session_id,
            current_password=current_password,
            new_password=new_password,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        # O commit é preciso mesmo na recusa: a tentativa errada é auditada, e
        # um rollback aqui apagaria justamente o registro que interessa.
        codigo = _codigo_do_erro(error)
        if isinstance(error, WrongCurrentPassword):
            await session.commit()
        else:
            await session.rollback()
        return _redirect(destino, codigo)

    await session.commit()
    return _redirect(destino, "senha-trocada")


# --------------------------------------------------- produtos preferidos


@router.post("/customers/{customer_id}/preferred", include_in_schema=False)
async def incluir_preferido(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    product_id: Annotated[str, Form()],
    customer_alias: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}?aba=produtos"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _admin_service(request, session).add_preferred_product(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            product_id=uuid.UUID(product_id),
            customer_alias=customer_alias,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "preferido-adicionado")


@router.post("/customers/{customer_id}/preferred/{preferred_id}", include_in_schema=False)
async def salvar_preferido(
    request: Request,
    customer_id: uuid.UUID,
    preferred_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"/portal/customers/{customer_id}?aba=produtos"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    argumentos: dict = {
        "remover": {"active": False},
        "reincluir": {"active": True},
        "subir": {"move": -1},
        "descer": {"move": 1},
    }.get(acao, {})
    if not argumentos:
        return _redirect(destino, "nao-encontrado")

    try:
        await _admin_service(request, session).update_preferred_product(
            scope_for(current_user),
            customer_id,
            preferred_id,
            actor_user_id=current_user.user_id,
            **argumentos,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "preferido-salvo")


@router.post("/customers/{customer_id}/articles", include_in_schema=False)
async def cadastrar_artigo(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sku: Annotated[str, Form()],
    commercial_name: Annotated[str, Form()],
    availability: Annotated[str, Form()] = AvailabilityStatus.AVAILABLE.value,
    family_id: _CustomerForm = None,
    family_name: _CustomerForm = None,
    specification: _CustomerForm = None,
    unit: _CustomerForm = None,
    base_price: _CustomerForm = None,
    customer_alias: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Cria o artigo e o inclui entre os preferidos do cliente, na mesma transação.

    As duas coisas andam juntas porque é uma operação só do ponto de vista de
    quem está na tela: o artigo foi cadastrado *porque* faltava para este
    cliente. Cadastrar sem incluir deixaria o usuário repetindo o passo que ele
    já tinha começado.
    """
    destino = f"/portal/customers/{customer_id}?aba=produtos"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect(destino, "sem-permissao")

    try:
        preco = (
            parse_decimal(base_price, field="base_price")
            if base_price and base_price.strip()
            else None
        )
        disponibilidade = AvailabilityStatus(availability)
        familia = uuid.UUID(family_id) if family_id else None
    except (InvalidDecimal, ValueError) as error:
        await session.rollback()
        return _redirect(
            destino, "preco-invalido" if isinstance(error, InvalidDecimal) else "artigo-invalido"
        )

    try:
        criado = await _catalog_service(session).create_article(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            sku=sku,
            commercial_name=commercial_name,
            family_id=familia,
            family_name=family_name,
            specification=specification,
            unit=unit or "KG",
            base_price=preco,
            availability=disponibilidade,
            request_id=request.headers.get("x-request-id"),
        )
        await _admin_service(request, session).add_preferred_product(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            product_id=criado.product.id,
            customer_alias=customer_alias,
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "artigo-cadastrado")


# ----------------------------------------------------- lista de preço


def _csv_da_lista(resolvida) -> Response:
    """Exporta a lista resolvida.

    Escrito com BOM em UTF-8: sem ele o Excel em português abre o arquivo na
    codificação da máquina e transforma cada acento em ruído. O separador é o
    ponto e vírgula, como no CSV de importação.
    """
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow(
        [
            "sku",
            "familia",
            "produto",
            "especificacao",
            "unidade",
            "disponibilidade",
            "preco_base",
            "aliquota_destino",
            "preco_final",
            "chegada_prevista",
            "observacao",
        ]
    )
    for item in resolvida.items:
        escritor.writerow(
            [
                item.sku,
                item.family_name,
                item.display_name,
                item.specification or "",
                item.unit,
                item.availability,
                _numero(item.base_price),
                _numero(item.tax_rate),
                _numero(item.final_price),
                item.expected_arrival_date.isoformat() if item.expected_arrival_date else "",
                item.notes or item.arrival_note or "",
            ]
        )

    praca = f"-{resolvida.destination_state}" if resolvida.destination_state else ""
    nome = f"lista-{resolvida.customer.id}-{resolvida.reference_month:%Y%m}{praca}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


def _numero(valor) -> str:
    """Decimal com vírgula, que é o que a planilha em pt-BR espera."""
    return "" if valor is None else f"{valor}".replace(".", ",")


@router.get("/customers/{customer_id}/price-list", include_in_schema=False)
async def pagina_lista_de_preco(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    mes: Annotated[str | None, Query()] = None,
    formato: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    escopo = scope_for(current_user)
    encontrado = await CustomerPortfolioRepository(session).get_customer(escopo, customer_id)
    if encontrado is None:
        return _redirect("/portal/customers", "nao-encontrado")
    cliente, _ = encontrado

    settings: Settings = request.app.state.settings
    tenant = await UserRepository(session).get_tenant(settings.tenant_slug)
    contexto = {
        "cliente": cliente,
        "localidades": await CustomerAdminRepository(session).list_locations(customer_id),
        "location_id": location_id,
        "mes": mes,
        "competencias": await PriceEntryRepository(session).list_months(current_user.tenant_id),
        "origem": tenant.origin_state_code if tenant else None,
        # Sem conversão (ADR-032) a tela não fala de UF, localidade nem alíquota.
        "converte": ConversionMode(settings.icms_conversion_mode) is not ConversionMode.NONE,
        "resolvida": None,
    }

    try:
        resolvida = await _price_list_service(request, session).resolve(
            escopo,
            customer_id,
            origin_state=tenant.origin_state_code if tenant else None,
            location_id=location_id,
            month=_competencia(mes),
        )
    except Exception as error:  # noqa: BLE001
        # A tela continua de pé mostrando o motivo: quem gera a lista precisa
        # saber o que cadastrar, e um redirecionamento perderia a seleção.
        return _render(
            request,
            "price_list.html",
            contexto,
            current_user=current_user,
            mensagem=_codigo_do_erro(error),
        )

    if formato == "csv":
        return _csv_da_lista(resolvida)

    contexto["resolvida"] = resolvida
    return _render(
        request,
        "price_list.html",
        contexto,
        current_user=current_user,
        mensagem=m,
    )


def _competencia(mes: str | None) -> date | None:
    """Converte `AAAA-MM` da query string em primeiro dia do mês."""
    if not mes:
        return None
    try:
        ano, mes_numero = mes.split("-")
        return date(int(ano), int(mes_numero), 1)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------- matriz de ICMS


@router.get("/icms-rules", include_in_schema=False)
async def pagina_icms(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    settings: Settings = request.app.state.settings
    tenant = await UserRepository(session).get_tenant(settings.tenant_slug)
    return _render(
        request,
        "icms_rules.html",
        {
            "regras": await IcmsRuleRepository(session).list_rules(current_user.tenant_id),
            "origem": tenant.origin_state_code if tenant else None,
            "hoje": date.today(),
        },
        current_user=current_user,
        mensagem=m,
    )


@router.post("/icms-rules", include_in_schema=False)
async def criar_regra_icms(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    origin_state: Annotated[str, Form()],
    destination_state: Annotated[str, Form()],
    tax_rate: Annotated[str, Form()],
    valid_from: Annotated[str, Form()],
    priority: Annotated[str, Form()] = "100",
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/icms-rules", "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        regra = IcmsRule(
            id=uuid.uuid4(),
            tenant_id=current_user.tenant_id,
            origin_state=normalize_state_code(origin_state),
            destination_state=normalize_state_code(destination_state),
            tax_rate=Decimal(tax_rate.replace(",", ".")),
            valid_from=date.fromisoformat(valid_from),
            priority=int(priority),
        )
    except (InvalidOperation, ValueError) as error:
        await session.rollback()
        return _redirect(
            "/portal/icms-rules",
            "uf-invalida" if isinstance(error, InvalidStateCode) else "aliquota-invalida",
        )

    IcmsRuleRepository(session).add(regra)
    AuditRepository(session).record(
        action="ICMS_RULE_CREATED",
        entity="icms_rules",
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.user_id,
        entity_id=regra.id,
        after={
            "origin_state": regra.origin_state,
            "destination_state": regra.destination_state,
            "tax_rate": str(regra.tax_rate),
            "valid_from": regra.valid_from.isoformat(),
            "source": "portal",
        },
    )
    await session.commit()
    return _redirect("/portal/icms-rules", "regra-criada")


# --------------------------------------------------------------- catálogo


_SITUACOES_DO_ARTIGO = {"ativos": True, "inativos": False, "todos": None}


@router.get("/products", include_in_schema=False)
async def pagina_produtos(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    busca: Annotated[str | None, Query()] = None,
    familia: Annotated[str | None, Query()] = None,
    situacao: Annotated[str, Query()] = "ativos",
    sem_preco: Annotated[str | None, Query()] = None,
    aba: Annotated[str, Query()] = "catalogo",
    mes: Annotated[str | None, Query()] = None,
    editar: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    # Leitura aberta a qualquer papel desde a `0013`: o representante precisa
    # ver o catálogo para etiquetar artigo em grupo. Escrever artigo e família
    # continua com a gestão — errar um grupo muda o público de um disparo,
    # errar uma família muda o que **todo** cliente vê na tabela dele.
    pode_gerir = current_user.role in _MANAGEMENT_ROLES

    catalogo = CatalogRepository(session)
    competencia = await PriceEntryRepository(session).latest_month(
        current_user.tenant_id, at=datetime.now(UTC).date()
    )
    filtros = ProductFilters(
        search=busca or None,
        family_id=uuid.UUID(familia) if familia else None,
        active=_SITUACOES_DO_ARTIGO.get(situacao, True),
        without_price=bool(sem_preco),
    )

    if aba not in {"catalogo", "tabelas", "cadastros"}:
        aba = "catalogo"
    if aba == "tabelas" and current_user.role is not UserRole.ADMIN:
        aba = "catalogo"

    linhas = await catalogo.list_products(current_user.tenant_id, filtros, month=competencia)
    entradas = PriceEntryRepository(session)
    competencias = await entradas.list_months(current_user.tenant_id) if pode_gerir else []
    selecionada = _competencia(mes) or (competencias[0] if competencias else competencia)
    lotes = (
        await PriceListRepository(session).list_batches(current_user.tenant_id)
        if current_user.role is UserRole.ADMIN
        else []
    )
    autores_ids = {lote.created_by for lote in lotes if lote.created_by}
    autores_lotes = {}
    if autores_ids:
        autores_lotes = {
            usuario.id: usuario.full_name
            for usuario in await session.scalars(
                select(User).where(
                    User.tenant_id == current_user.tenant_id,
                    User.id.in_(autores_ids),
                )
            )
        }
    anexos_lotes = {}
    if lotes:
        anexos_lotes = {
            anexo.price_list_id: anexo
            for anexo in await session.scalars(
                select(PriceListSourceFile).where(
                    PriceListSourceFile.tenant_id == current_user.tenant_id,
                    PriceListSourceFile.price_list_id.in_([lote.id for lote in lotes]),
                )
            )
        }
    revisoes = (
        await entradas.list_revisions_with_product(current_user.tenant_id, selecionada)
        if selecionada and current_user.role is UserRole.ADMIN
        else []
    )
    revisoes_por_produto: dict[uuid.UUID, list] = {}
    for revisao, produto in revisoes:
        revisoes_por_produto.setdefault(produto.id, []).append(revisao)
    return _render(
        request,
        "products.html",
        {
            "linhas": linhas,
            "familias": await catalogo.list_families(current_user.tenant_id, active=None),
            "contagem_por_familia": await catalogo.count_products_by_family(current_user.tenant_id),
            "grupos": await catalogo.list_groups(current_user.tenant_id, active=None),
            "contagem_por_grupo": await catalogo.count_products_by_group(current_user.tenant_id),
            "grupos_do_artigo": await catalogo.groups_of_products(
                current_user.tenant_id, [linha.product.id for linha in linhas]
            ),
            "competencia": competencia,
            "busca": busca or "",
            "familia_escolhida": familia or "",
            "situacao": situacao,
            "sem_preco": bool(sem_preco),
            # Qual linha abre já em modo de edição, depois do redirecionamento.
            "editando": editar or "",
            "pode_gerir": pode_gerir,
            "aba": aba,
            "lotes": lotes,
            "autores_lotes": autores_lotes,
            "anexos_lotes": anexos_lotes,
            "competencias": competencias,
            "selecionada": selecionada,
            "itens_tabela": await entradas.list_items(current_user.tenant_id, selecionada)
            if selecionada and current_user.role is UserRole.ADMIN
            else [],
            "revisoes": revisoes,
            "revisoes_por_produto": revisoes_por_produto,
        },
        current_user=current_user,
        mensagem=m,
    )


def _filtros_na_volta(busca: str | None, familia: str | None, situacao: str | None) -> str:
    """Preserva os filtros no redirecionamento do POST.

    Sem isso, salvar um artigo encontrado por busca joga o usuário de volta na
    lista inteira, e ele perde o lugar onde estava trabalhando.
    """
    partes = [
        f"{chave}={valor}"
        for chave, valor in (("busca", busca), ("familia", familia), ("situacao", situacao))
        if valor
    ]
    return "/portal/products" + ("?" + "&".join(partes) if partes else "")


@router.post("/products", include_in_schema=False)
async def criar_produto(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sku: Annotated[str, Form()],
    commercial_name: Annotated[str, Form()],
    family_id: _CustomerForm = None,
    family_name: _CustomerForm = None,
    specification: _CustomerForm = None,
    unit: _CustomerForm = None,
    availability: _CustomerForm = None,
    base_price: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Cadastra o artigo; o preço do mês é opcional aqui.

    Diferente do modal da ficha, esta tela é o catálogo: cadastrar artigo que
    ainda não tem preço é caso normal, porque o preço costuma chegar na
    importação da tabela do mês.
    """
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/products", "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        preco = (
            parse_decimal(base_price, field="base_price")
            if base_price and base_price.strip()
            else None
        )
        disponibilidade = AvailabilityStatus(availability) if availability else None
        familia = uuid.UUID(family_id) if family_id else None
    except (InvalidDecimal, ValueError) as error:
        await session.rollback()
        return _redirect(
            "/portal/products",
            "preco-invalido" if isinstance(error, InvalidDecimal) else "artigo-invalido",
        )

    servico = _catalog_service(session)
    try:
        produto, _, _ = await servico.create_product(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            sku=sku,
            commercial_name=commercial_name,
            family_id=familia,
            family_name=family_name,
            specification=specification,
            unit=unit or "KG",
            request_id=request.headers.get("x-request-id"),
        )
        if disponibilidade is not None:
            await servico.add_draft_price(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                product=produto,
                base_price=preco,
                availability=disponibilidade,
                request_id=request.headers.get("x-request-id"),
            )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect("/portal/products", _codigo_do_erro(error))

    await session.commit()
    return _redirect(
        "/portal/products", "artigo-com-rascunho" if disponibilidade else "artigo-criado"
    )


@router.post("/products/{product_id}", include_in_schema=False)
async def salvar_produto(
    request: Request,
    product_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()] = "salvar",
    commercial_name: _CustomerForm = None,
    sku: _CustomerForm = None,
    family_id: _CustomerForm = None,
    specification: _CustomerForm = None,
    unit: _CustomerForm = None,
    busca: _CustomerForm = None,
    familia: _CustomerForm = None,
    situacao: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = _filtros_na_volta(busca, familia, situacao)
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect("/portal/customers", "sem-permissao")

    servico = _catalog_service(session)
    try:
        if acao in {"ativar", "desativar"}:
            await servico.set_product_active(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                product_id=product_id,
                active=acao == "ativar",
                request_id=request.headers.get("x-request-id"),
            )
            codigo = "artigo-ativado" if acao == "ativar" else "artigo-desativado"
        else:
            await servico.update_product(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                product_id=product_id,
                commercial_name=commercial_name or "",
                family_id=uuid.UUID(family_id) if family_id else None,
                sku=sku,
                specification=specification,
                unit=unit,
                request_id=request.headers.get("x-request-id"),
            )
            codigo = "artigo-salvo"
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, codigo)


@router.post("/product-groups", include_in_schema=False)
async def criar_grupo_de_artigo(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str, Form()],
    busca: _CustomerForm = None,
    familia: _CustomerForm = None,
    situacao: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Criar grupo é aberto a qualquer papel, inclusive representante.

    O grupo é do tenant, não de quem o criou: "poliéster" que significasse
    coisas diferentes por representante tornaria o público de um disparo
    imprevisível. A autoria fica registrada só para auditoria.
    """
    destino = _filtros_na_volta(busca, familia, situacao)
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")

    try:
        await _catalog_service(session).create_group(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            name=name,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "grupo-criado")


@router.post("/product-groups/{group_id}", include_in_schema=False)
async def alterar_grupo_de_artigo(
    request: Request,
    group_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()],
    name: _CustomerForm = None,
    busca: _CustomerForm = None,
    familia: _CustomerForm = None,
    situacao: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Renomear e desativar. **Só a gestão** — diferente de criar e etiquetar.

    Renomear um grupo muda o significado de tudo o que já foi etiquetado com
    ele, e desativar tira o grupo de circulação. Criar um grupo novo não
    desfaz o trabalho de ninguém; mexer num existente, sim.
    """
    destino = _filtros_na_volta(busca, familia, situacao)
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect("/portal/customers", "sem-permissao")
    if acao not in {"renomear", "ativar", "desativar"}:
        return _redirect(destino, "nao-encontrado")

    servico = _catalog_service(session)
    try:
        if acao == "renomear":
            await servico.rename_group(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                group_id=group_id,
                name=name or "",
                request_id=request.headers.get("x-request-id"),
            )
        else:
            await servico.set_group_active(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                group_id=group_id,
                active=acao == "ativar",
                request_id=request.headers.get("x-request-id"),
            )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "grupo-salvo")


@router.post("/products/{product_id}/groups", include_in_schema=False)
async def etiquetar_artigo(
    request: Request,
    product_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()],
    group_id: Annotated[str, Form()],
    busca: _CustomerForm = None,
    familia: _CustomerForm = None,
    situacao: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Põe e tira etiqueta. Aberto a qualquer papel, inclusive representante."""
    destino = _filtros_na_volta(busca, familia, situacao)
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    if acao not in {"incluir", "remover"}:
        return _redirect(destino, "nao-encontrado")

    try:
        grupo = uuid.UUID(group_id)
    except ValueError:
        return _redirect(destino, "nao-encontrado")

    servico = _catalog_service(session)
    try:
        if acao == "incluir":
            await servico.add_product_to_group(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                group_id=grupo,
                product_id=product_id,
                request_id=request.headers.get("x-request-id"),
            )
        else:
            await servico.remove_product_from_group(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.user_id,
                group_id=grupo,
                product_id=product_id,
                request_id=request.headers.get("x-request-id"),
            )
    except Exception as error:  # noqa: BLE001 -- reclassificado por _codigo_do_erro
        await session.rollback()
        return _redirect(destino, _codigo_do_erro(error))

    await session.commit()
    return _redirect(destino, "etiqueta-salva")


@router.post("/families", include_in_schema=False)
async def criar_familia(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str, Form()],
    display_order: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/products", "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        await _catalog_service(session).create_family(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            name=name,
            display_order=int(display_order) if display_order else None,
            request_id=request.headers.get("x-request-id"),
        )
    except ValueError:
        await session.rollback()
        return _redirect("/portal/products", "ordem-invalida")
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect("/portal/products", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/products", "familia-criada")


@router.post("/families/{family_id}", include_in_schema=False)
async def salvar_familia(
    request: Request,
    family_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    acao: Annotated[str, Form()] = "salvar",
    name: _CustomerForm = None,
    display_order: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/products", "csrf")
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        argumentos: dict = {
            "ativar": {"active": True},
            "desativar": {"active": False},
        }.get(
            acao,
            {"name": name, "display_order": int(display_order) if display_order else None},
        )
        await _catalog_service(session).update_family(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            family_id=family_id,
            request_id=request.headers.get("x-request-id"),
            **argumentos,
        )
    except ValueError:
        await session.rollback()
        return _redirect("/portal/products", "ordem-invalida")
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect("/portal/products", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/products", "familia-salva")


# ------------------------------------------------------- tabela do mês


@router.get("/prices", include_in_schema=False)
async def pagina_tabelas(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mes: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    destino = "/portal/products?aba=tabelas"
    if mes:
        destino += f"&mes={mes}"
    if m:
        destino += f"&m={m}"
    return RedirectResponse(destino, status_code=303)


@router.get("/prices/export", include_in_schema=False)
async def exportar_tabela_atualizacao(
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mes: Annotated[str | None, Query()] = None,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    entradas = PriceEntryRepository(session)
    competencia = _competencia(mes) or await entradas.latest_month(
        current_user.tenant_id, at=datetime.now(UTC).date()
    )
    itens = await entradas.list_items(current_user.tenant_id, competencia) if competencia else []
    arquivo = io.StringIO()
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(
        [
            "family_name", "family_order", "sku", "commercial_name", "specification",
            "availability", "base_price", "expected_arrival_date", "arrival_note",
            "display_order", "notes",
        ]
    )
    for entrada, produto, familia in itens:
        escritor.writerow(
            [
                familia.name,
                familia.display_order,
                produto.sku,
                produto.commercial_name,
                produto.specification or "",
                entrada.availability.value,
                str(entrada.base_price),
                entrada.expected_arrival_date.isoformat() if entrada.expected_arrival_date else "",
                entrada.arrival_note or "",
                entrada.display_order,
                entrada.notes or "",
            ]
        )
    nome = (
        f"tabela-atualizacao-{competencia:%Y-%m}.csv"
        if competencia
        else "tabela-atualizacao.csv"
    )
    return Response(
        arquivo.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/prices/batches/{batch_id}/source-file", include_in_schema=False)
async def baixar_arquivo_original_do_lote(
    batch_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    anexo = await session.scalar(
        select(PriceListSourceFile)
        .join(PriceList, PriceList.id == PriceListSourceFile.price_list_id)
        .where(
            PriceListSourceFile.price_list_id == batch_id,
            PriceListSourceFile.tenant_id == current_user.tenant_id,
            PriceList.tenant_id == current_user.tenant_id,
        )
    )
    if anexo is None:
        return _redirect("/portal/products?aba=tabelas", "anexo-nao-encontrado")
    nome_original = Path(anexo.filename).name[:255] or "arquivo"
    nome_ascii = re.sub(r"[^A-Za-z0-9._-]", "_", nome_original) or "arquivo"
    return Response(
        content=anexo.content,
        media_type=anexo.mime_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{nome_ascii}"; '
                f"filename*=UTF-8''{quote(nome_original)}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Price-Source-SHA256": anexo.sha256,
        },
    )


@router.post("/prices/import", include_in_schema=False)
async def importar_tabela_portal(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    arquivo: Annotated[UploadFile, File()],
    nome: Annotated[str, Form()],
    referencia: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = "/portal/products?aba=tabelas"
    if not csrf_is_valid(request, csrf_token):
        return _redirect(destino, "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")
    competencia = _competencia(referencia)
    conteudo = await arquivo.read(5_000_001)
    if (
        competencia is None
        or not nome.strip()
        or len(conteudo) > 5_000_000
        or not (arquivo.filename or "").lower().endswith(".csv")
    ):
        return _redirect(destino, "tabela-invalida")

    caminho = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as temporario:
            temporario.write(conteudo)
            caminho = temporario.name
        tenant_slug = await session.scalar(
            select(Tenant.slug).where(Tenant.id == current_user.tenant_id)
        )
        resultado = await import_price_table(
            session,
            tenant_slug=tenant_slug,
            source_path=Path(caminho),
            name=nome.strip(),
            reference_month=competencia,
            valid_from=datetime(competencia.year, competencia.month, 1, tzinfo=UTC),
            valid_until=None,
        )
        resultado.price_list.created_by = current_user.user_id
        resultado.price_list.source_wamid = f"portal:{uuid.uuid4()}"
        resultado.price_list.source_kind = "PORTAL_CSV"
        session.add(
            PriceListSourceFile(
                id=uuid.uuid4(),
                tenant_id=current_user.tenant_id,
                price_list_id=resultado.price_list.id,
                filename=Path(arquivo.filename or "tabela.csv").name[:255],
                mime_type="text/csv",
                byte_size=len(conteudo),
                sha256=hashlib.sha256(conteudo).hexdigest(),
                content=conteudo,
            )
        )
        await session.commit()
    except (UnicodeDecodeError, ValueError, csv.Error):
        await session.rollback()
        return _redirect(destino, "tabela-invalida")
    finally:
        if caminho:
            Path(caminho).unlink(missing_ok=True)
    return _redirect(destino, "tabela-importada")


@router.post("/prices/publish", include_in_schema=False)
async def publicar_lote(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    batch_id: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/products?aba=tabelas", "csrf")
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    try:
        resultado = await _publication_service(session).publish_batch(
            tenant_id=current_user.tenant_id,
            batch_id=uuid.UUID(batch_id),
            actor_user_id=current_user.user_id,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception as error:  # noqa: BLE001
        await session.rollback()
        return _redirect("/portal/products?aba=tabelas", _codigo_do_erro(error))

    await session.commit()
    return _redirect(
        f"/portal/products?aba=tabelas&mes={resultado.reference_month:%Y-%m}",
        "lote-publicado",
    )


__all__ = ["router", "PortalRedirect"]
