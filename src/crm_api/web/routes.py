"""Páginas do portal do representante.

Camada fina: cada rota valida o CSRF, chama os mesmos serviços que a API usa e
traduz o resultado em redirecionamento. Nenhuma regra de negócio vive aqui.
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, build_auth_service
from crm_api.api.scoping import scope_for
from crm_api.core.config import Settings
from crm_api.core.database import get_session
from crm_api.core.numbers import InvalidDecimal, parse_decimal
from crm_api.core.passwords import WeakPassword
from crm_api.core.states import InvalidStateCode, normalize_state_code
from crm_api.models.interaction import NOTE_CHANNELS, InteractionDirection
from crm_api.models.pricing import AvailabilityStatus
from crm_api.models.tax import IcmsRule
from crm_api.models.user import User, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.catalog import CatalogRepository, ProductFilters
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customer_intakes import CustomerIntakeRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
)
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.repositories.price_lists import PriceListRepository
from crm_api.repositories.users import SessionRepository, UserRepository
from crm_api.services.auth import AuthenticationFailed, normalize_email
from crm_api.services.catalog import (
    ArticleNotFound,
    BasePriceRequired,
    CatalogService,
    DuplicateFamily,
    DuplicateSku,
    FamilyNotFound,
    FamilyRequired,
    IncompleteArticle,
    InvalidBasePrice,
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
from crm_api.services.icms import (
    AmbiguousIcmsRule,
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
from crm_api.web import messages
from crm_api.web.csrf import (
    CSRF_FIELD_NAME,
    attach_csrf_cookie,
    csrf_is_valid,
    current_or_new_token,
)
from crm_api.web.dependencies import LOGIN_PATH, PortalRedirect, portal_user, templates

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


def _redirect(destino: str, codigo: str | None = None) -> RedirectResponse:
    # 303 força o navegador a trocar o POST por um GET, encerrando o ciclo de
    # reenvio ao atualizar a página.
    if not codigo:
        return RedirectResponse(destino, status_code=303)
    # O destino pode já levar query string própria — a publicação volta para a
    # competência que acabou de publicar.
    separador = "&" if "?" in destino else "?"
    return RedirectResponse(f"{destino}{separador}m={codigo}", status_code=303)


def _render(
    request: Request,
    template: str,
    contexto: dict,
    *,
    current_user: CurrentUser | None = None,
    mensagem: str | None = None,
    erro_direto: str | None = None,
    status_code: int = 200,
) -> Response:
    settings: Settings = request.app.state.settings
    token = current_or_new_token(request)
    aviso, erro = messages.resolve(mensagem)
    resposta = templates.TemplateResponse(
        request,
        template,
        {
            **contexto,
            "current_user": current_user,
            "csrf_token": token,
            "aviso": aviso,
            "erro": erro_direto or erro,
        },
        status_code=status_code,
    )
    attach_csrf_cookie(resposta, token, secure=settings.session_cookie_secure)
    return resposta


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


async def _designaveis(session: AsyncSession, tenant_id: uuid.UUID) -> list[User]:
    return await UserRepository(session).list_users(
        tenant_id, active=True, limit=200, offset=0
    )


# ------------------------------------------------------------------ sessão


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def raiz() -> RedirectResponse:
    return RedirectResponse("/portal/customers", status_code=303)


@router.get("/login", include_in_schema=False)
async def pagina_login(
    request: Request,
    m: Annotated[str | None, Query()] = None,
    expirada: Annotated[str | None, Query()] = None,
) -> Response:
    return _render(request, "login.html", {"email": None}, mensagem=m or (
        "expirada" if expirada else None
    ))


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
    resposta = _redirect("/portal/customers")
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
            "filtros": {
                "busca": busca,
                "uf": uf,
                "situacao": situacao,
                "titular": titular,
                "contato": contato,
            },
            "pode_gerir": pode_gerir,
            "somente_minha": not pode_gerir,
        },
        current_user=current_user,
        mensagem=m,
    )


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


@router.get("/intakes", include_in_schema=False)
async def pagina_pre_cadastros(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    """Fila pendente que cada papel pode de fato resolver.

    O recorte de representante acontece no serviço, não no template: ele vê
    somente o que abriu; `ADMIN` e `MANAGER` veem a fila do tenant inteiro.
    """
    intakes, total = await _intake_service(request, session).queue(
        scope_for(current_user), actor_role=current_user.role
    )
    return _render(
        request,
        "intakes.html",
        {"intakes": intakes, "total": total},
        current_user=current_user,
        mensagem=m,
    )


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
    contact_name: _CustomerForm = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/intakes", "csrf")

    try:
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
        return _redirect("/portal/intakes", _codigo_do_erro(error))

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
        return _redirect("/portal/intakes", "csrf")

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
        return _redirect("/portal/intakes", _codigo_do_erro(error))

    await session.commit()
    return _redirect("/portal/intakes", "intake-rejeitado")


@router.get("/customers/{customer_id}", include_in_schema=False)
async def pagina_cliente(
    request: Request,
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    escopo = scope_for(current_user)
    servico = _admin_service(request, session)
    portfolio = CustomerPortfolioRepository(session)

    encontrado = await portfolio.get_customer(escopo, customer_id)
    if encontrado is None:
        return _redirect("/portal/customers", "nao-encontrado")
    cliente, dono = encontrado

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
    competencia = await entradas.latest_month(
        current_user.tenant_id, at=datetime.now(UTC).date()
    )
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

    return _render(
        request,
        "customer_detail.html",
        {
            "cliente": cliente,
            "titular": dono,
            "contatos": await servico.list_contacts(escopo, customer_id),
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
    destino = f"/portal/customers/{customer_id}"
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
    destino = f"/portal/customers/{customer_id}"
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
    return _redirect(
        destino, "titular-alterado" if resultado.changed else "titular-sem-mudanca"
    )


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


# ----------------------------------------------------------- representantes


@router.get("/users", include_in_schema=False)
async def pagina_usuarios(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    if current_user.role is not UserRole.ADMIN:
        return _redirect("/portal/customers", "sem-permissao")

    usuarios, _ = await _user_service(request, session).list_users(
        tenant_id=current_user.tenant_id, limit=200, offset=0
    )
    return _render(
        request,
        "users.html",
        {
            "usuarios": usuarios,
            "tamanho_minimo_senha": request.app.state.settings.password_min_length,
        },
        current_user=current_user,
        mensagem=m,
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
    destino = f"/portal/customers/{customer_id}"
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
    destino = f"/portal/customers/{customer_id}"
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
    destino = f"/portal/customers/{customer_id}"
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

    nome = (
        f"lista-{resolvida.customer.id}-{resolvida.reference_month:%Y%m}"
        f"-{resolvida.location.state_code}.csv"
    )
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
        "competencias": await PriceEntryRepository(session).list_months(
            current_user.tenant_id
        ),
        "origem": tenant.origin_state_code if tenant else None,
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
    editar: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    if current_user.role not in _MANAGEMENT_ROLES:
        return _redirect("/portal/customers", "sem-permissao")

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

    return _render(
        request,
        "products.html",
        {
            "linhas": await catalogo.list_products(
                current_user.tenant_id, filtros, month=competencia
            ),
            "familias": await catalogo.list_families(current_user.tenant_id, active=None),
            "contagem_por_familia": await catalogo.count_products_by_family(
                current_user.tenant_id
            ),
            "competencia": competencia,
            "busca": busca or "",
            "familia_escolhida": familia or "",
            "situacao": situacao,
            "sem_preco": bool(sem_preco),
            # Qual linha abre já em modo de edição, depois do redirecionamento.
            "editando": editar or "",
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

    entradas = PriceEntryRepository(session)
    competencias = await entradas.list_months(current_user.tenant_id)
    selecionada = _competencia(mes) or (competencias[0] if competencias else None)

    return _render(
        request,
        "prices.html",
        {
            "lotes": await PriceListRepository(session).list_batches(current_user.tenant_id),
            "competencias": competencias,
            "selecionada": selecionada,
            "itens": await entradas.list_items(current_user.tenant_id, selecionada)
            if selecionada
            else [],
            "revisoes": await entradas.list_revisions_with_product(
                current_user.tenant_id, selecionada
            )
            if selecionada
            else [],
        },
        current_user=current_user,
        mensagem=m,
    )


@router.post("/prices/publish", include_in_schema=False)
async def publicar_lote(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    batch_id: Annotated[str, Form()],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    if not csrf_is_valid(request, csrf_token):
        return _redirect("/portal/prices", "csrf")
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
        return _redirect("/portal/prices", _codigo_do_erro(error))

    await session.commit()
    return _redirect(
        f"/portal/prices?mes={resultado.reference_month:%Y-%m}", "lote-publicado"
    )


__all__ = ["router", "PortalRedirect"]
