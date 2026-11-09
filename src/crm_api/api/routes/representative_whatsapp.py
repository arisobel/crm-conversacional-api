"""As três leituras do representante, chamadas pelos executores do Gateway (W6).

O telefone vem no caminho, como em `/customers/by-whatsapp/{phone}`: é a única
identidade que o Gateway tem para oferecer, e é ela que decide de quem é a
carteira. Nenhuma destas rotas aceita um `user_id` — aceitar um permitiria ao
Gateway escolher a carteira que quisesse, e a autorização deixaria de ser
decidida aqui.
"""

import base64
import binascii
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.core.states import InvalidStateCode
from crm_api.models.pricing import PriceListStatus
from crm_api.models.reminder import ReminderOrigin, ReminderStatus, RepresentativeReminder
from crm_api.repositories.assistant_settings import get_assistant_policy
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.campaign_audience import AudienceRepository
from crm_api.repositories.catalog import CatalogRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customer_intakes import CustomerIntakeRepository
from crm_api.repositories.customers import CustomerRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.repositories.reminders import ReminderRepository
from crm_api.repositories.users import UserRepository
from crm_api.repositories.whatsapp_connections import WhatsappConnectionRepository
from crm_api.schemas.customer_intake import (
    CustomerIntakeResponse,
    OpenCustomerIntakeRequest,
)
from crm_api.schemas.price_lists import CurrentPriceListItemResponse
from crm_api.schemas.representative_whatsapp import (
    AssistantConfirmPriceUpdateRequest,
    AssistantCreateReminderRequest,
    AssistantCustomerConversationSummaryRequest,
    AssistantCustomerIntakeRequest,
    AssistantCustomerPriceListRequest,
    AssistantExecutionContext,
    AssistantListPortfolioCustomersRequest,
    AssistantLookupCustomersRequest,
    AssistantPriceUpdateConfirmationResponse,
    AssistantPriceUpdateProposalResponse,
    AssistantProposePriceUpdateRequest,
    AssistantReminderResponse,
    AssistantSearchPriceItemsRequest,
    CustomerConversationEntryResponse,
    CustomerConversationSummaryResponse,
    CustomerMatchesResponse,
    CustomerMatchResponse,
    PortfolioCustomersResponse,
    PriceItemsResponse,
    PriceUpdateChangeResponse,
    ResolvedCustomerPriceListResponse,
)
from crm_api.services.customer_admin import CustomerAdminService
from crm_api.services.customer_intake import (
    BlankField,
    CustomerIntakeService,
    WhatsappAlreadyUsed,
)
from crm_api.services.customer_intake import (
    NotARepresentative as IntakeNotARepresentative,
)
from crm_api.services.customer_price_list import (
    CustomerPriceListService,
    LocationUnavailable,
    PricesUnavailable,
)
from crm_api.services.icms import (
    AmbiguousIcmsRule,
    IcmsResolver,
    IcmsRuleNotFound,
    InvalidTaxRate,
    OriginNotConfigured,
)
from crm_api.services.portfolio import CustomerNotInScope
from crm_api.services.price_publication import PricePublicationService
from crm_api.services.price_update import (
    PriceUpdateProposalForbidden,
    PriceUpdateProposalNotFound,
    ProposedPriceRow,
    ProposedPriceSourceFile,
    RepresentativePriceUpdateService,
)
from crm_api.services.representative_whatsapp import (
    MAX_CANDIDATOS,
    NoPublishedCompetence,
    NotARepresentative,
    RepresentativeWhatsappService,
)
from crm_api.services.whatsapp_actor import (
    ActorNotFound,
    ActorRole,
    AmbiguousActor,
    WhatsappActorResolver,
)

router = APIRouter(prefix="/internal/representative/by-whatsapp", tags=["Representative WhatsApp"])

_RESPONSES = {
    401: {"description": "Unauthorized"},
    403: {"description": "Phone does not belong to a portal user"},
    404: {"description": "Tenant, actor or customer not found"},
    409: {"description": "Colliding actor, or missing/ambiguous ICMS rule"},
    422: {"description": "Invalid phone, or missing location, origin or competence"},
}


def _service(request: Request, session: AsyncSession) -> RepresentativeWhatsappService:
    settings = request.app.state.settings
    entries = PriceEntryRepository(session)
    portfolio = CustomerPortfolioRepository(session)
    admin = CustomerAdminRepository(session)
    return RepresentativeWhatsappService(
        portfolio=portfolio,
        admin=admin,
        entries=entries,
        interactions=InteractionRepository(session),
        resolved=CustomerPriceListService(
            portfolio=portfolio,
            admin=admin,
            entries=entries,
            resolver=IcmsResolver(IcmsRuleRepository(session)),
            settings=settings,
        ),
        audience=AudienceRepository(session),
        catalog=CatalogRepository(session),
        settings=settings,
    )


async def _resolve(session: AsyncSession, tenant_slug: str, phone: str):
    """Tenant, ator e telefone canônico — as três coisas que toda rota precisa."""
    tenant = await CustomerRepository(session).get_tenant(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    try:
        canonico = normalize_whatsapp_e164(phone)
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    try:
        actor = await WhatsappActorResolver(session).resolve(tenant.id, canonico)
    except AmbiguousActor as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ActorNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return tenant, actor


async def _resolve_assistant_execution(
    request: Request,
    session: AsyncSession,
    tenant_slug: str,
    phone: str,
    context: AssistantExecutionContext,
    capability: str,
):
    """Revalida a autorização da Linha Assistente em toda chamada v2."""
    assistant_line = request.app.state.settings.assistant_line_phone_number_id
    if assistant_line is None or context.assistant_line_phone_number_id != assistant_line:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="assistant line is not authorized"
        )

    try:
        if normalize_whatsapp_e164(phone) != normalize_whatsapp_e164(
            context.representative_phone_e164
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="representative phone does not match execution context",
            )
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    tenant, actor = await _resolve(session, tenant_slug, phone)
    if actor.role is not ActorRole.REPRESENTATIVE or actor.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="assistant requires representative"
        )

    connections = await WhatsappConnectionRepository(session).list_connected_for_representative(
        tenant.id, actor.user_id
    )
    if len(connections) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="representative line is not connected"
        )
    if (
        context.representative_line_reference is not None
        and context.representative_line_reference != connections[0].gateway_line_reference
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="representative line does not match"
        )

    policy = await get_assistant_policy(session, tenant.id, actor.user_id)
    if not policy.allows(capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="assistant capability is not enabled"
        )
    return tenant, actor


def _forbidden(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))


def _intake_service(session: AsyncSession) -> CustomerIntakeService:
    admin = CustomerAdminRepository(session)
    audit = AuditRepository(session)
    return CustomerIntakeService(
        intakes=CustomerIntakeRepository(session),
        admin=admin,
        users=UserRepository(session),
        # A criação do cliente na aceitação é delegada ao serviço do portal, para
        # que localidade padrão, titularidade e auditoria não ganhem uma segunda
        # implementação capaz de divergir.
        customers=CustomerAdminService(
            portfolio=CustomerPortfolioRepository(session), admin=admin, audit=audit
        ),
        audit=audit,
    )


@router.get("/{phone}/price-items", response_model=PriceItemsResponse, responses=_RESPONSES)
async def search_price_items(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
    query: Annotated[str, Query(min_length=2, max_length=120)],
) -> PriceItemsResponse:
    """Artigo na competência vigente, em preço-base e sem conversão de ICMS.

    Não há cliente na pergunta, logo não há UF de destino — inventar uma seria
    escolher a praça de alguém por conta própria.
    """
    tenant, actor = await _resolve(session, tenant_slug, phone)
    try:
        encontrados = await _service(request, session).search_price_items(actor, tenant.id, query)
    except NotARepresentative as error:
        raise _forbidden(error) from error
    except NoPublishedCompetence as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return PriceItemsResponse(
        reference_month=encontrados.reference_month,
        items=encontrados.items,
        suggestions=encontrados.suggestions,
    )


@router.get("/{phone}/customers", response_model=CustomerMatchesResponse, responses=_RESPONSES)
async def lookup_customers(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
    query: Annotated[str, Query(min_length=2, max_length=120)],
) -> CustomerMatchesResponse:
    """Clientes **da carteira de quem escreveu** que casam com o termo."""
    tenant, actor = await _resolve(session, tenant_slug, phone)
    try:
        encontrados = await _service(request, session).lookup_customers(actor, tenant.id, query)
    except NotARepresentative as error:
        raise _forbidden(error) from error

    return CustomerMatchesResponse(
        matches=[
            CustomerMatchResponse(
                customer_id=match.customer_id,
                legal_name=match.legal_name,
                trade_name=match.trade_name,
                document_number=match.document_number,
                state_code=match.state_code,
            )
            for match in encontrados[:MAX_CANDIDATOS]
        ],
        truncated=len(encontrados) > MAX_CANDIDATOS,
    )


@router.get(
    "/{phone}/portfolio-customers",
    response_model=PortfolioCustomersResponse,
    responses=_RESPONSES,
)
async def list_portfolio_customers(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
    query: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
) -> PortfolioCustomersResponse:
    tenant, actor = await _resolve(session, tenant_slug, phone)
    try:
        result = await _service(request, session).list_portfolio_customers(
            actor, tenant.id, query
        )
    except NotARepresentative as error:
        raise _forbidden(error) from error
    return PortfolioCustomersResponse(
        matches=[CustomerMatchResponse(**match.__dict__) for match in result.matches],
        truncated=result.truncated,
        filter_label=result.filter_label,
        filter_suggestions=list(result.filter_suggestions),
    )


@router.get(
    "/{phone}/customers/{customer_id}/price-list",
    response_model=ResolvedCustomerPriceListResponse,
    responses=_RESPONSES,
)
async def customer_price_list(
    phone: str,
    customer_id: uuid.UUID,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResolvedCustomerPriceListResponse:
    """Tabela de um cliente da carteira, ao preço publicado (ADR-032).

    Só com a conversão de ICMS ligada o preço vai para a UF de entrega dele, e
    só então `409`/`422` fiscais podem ocorrer.

    Cliente fora da carteira responde `404` de cliente — o mesmo corpo de um
    `customer_id` inexistente, como no portal: distinguir os dois confirmaria a
    existência de uma conta de outra carteira.
    """
    tenant, actor = await _resolve(session, tenant_slug, phone)
    try:
        resolvida = await _service(request, session).customer_price_list(
            actor, tenant.id, customer_id, origin_state=tenant.origin_state_code
        )
    except NotARepresentative as error:
        raise _forbidden(error) from error
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="customer not found"
        ) from error
    except (IcmsRuleNotFound, AmbiguousIcmsRule) as error:
        # Conflito, não ausência: a tabela existe; falta a regra fiscal que
        # permite exibi-la para esta praça.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (LocationUnavailable, PricesUnavailable, OriginNotConfigured, InvalidTaxRate) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    return _price_list_response(resolvida)


@router.post(
    "/{phone}/customer-intakes",
    response_model=CustomerIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_RESPONSES | {409: {"description": "Phone already in use, or colliding actor"}},
)
async def open_customer_intake(
    phone: str,
    payload: OpenCustomerIntakeRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerIntakeResponse:
    """Abre pré-cadastro de cliente. **Não cria cliente e não autoriza telefone.**

    A única escrita que o representante alcança pelo WhatsApp, e ela deliberadamente
    não produz nada que o canal passe a atender: o cliente só existe, e o telefone
    dele só entra no roster, quando alguém aceita no portal. Se a mensagem gravasse
    o contato direto, uma frase no WhatsApp autorizaria um telefone qualquer a
    conversar com o CRM.

    A resposta é `201` também na reentrega, com `created: false` — a chave de
    idempotência é o `wamid`, e o mesmo `wamid` devolve o mesmo pré-cadastro em
    vez de abrir um segundo.
    """
    tenant, actor = await _resolve(session, tenant_slug, phone)
    servico = _intake_service(session)
    try:
        aberto = await servico.open(
            actor,
            tenant.id,
            idempotency_key=payload.idempotency_key,
            legal_name=payload.legal_name,
            state_code=payload.state_code,
            whatsapp_e164=payload.whatsapp_e164,
            preferred_products_text=payload.preferred_products_text,
            request_id=request.headers.get("x-request-id"),
        )
    except IntakeNotARepresentative as error:
        raise _forbidden(error) from error
    except WhatsappAlreadyUsed as error:
        # Conflito, não dado inválido: o telefone é válido e já pertence a
        # alguém neste tenant. Quem redige a resposta pode pedir outro número.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"telefone já cadastrado neste tenant: {error}",
        ) from error
    except (InvalidStateCode, BlankField) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    await session.commit()
    intake = aberto.intake
    return CustomerIntakeResponse(
        intake_id=intake.id,
        status=intake.status,
        legal_name=intake.legal_name,
        state_code=intake.state_code,
        has_whatsapp=intake.whatsapp_e164 is not None,
        preferred_products_text=intake.preferred_products_text,
        created_at=intake.created_at,
        created=aberto.created,
    )


# As rotas v2 recebem contexto no corpo HMAC. As rotas GET/POST anteriores
# continuam durante a migração do Gateway, mas não servem à Linha Assistente.
@router.post(
    "/{phone}/assistant-v2/price-items",
    response_model=PriceItemsResponse,
    responses=_RESPONSES,
)
async def assistant_search_price_items(
    phone: str,
    payload: AssistantSearchPriceItemsRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PriceItemsResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_SEARCH_PRICE_ITEMS"
    )
    try:
        result = await _service(request, session).search_price_items(
            actor, tenant.id, payload.query
        )
    except NoPublishedCompetence as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return PriceItemsResponse(
        reference_month=result.reference_month,
        items=result.items,
        suggestions=result.suggestions,
    )


@router.post(
    "/{phone}/assistant-v2/customers",
    response_model=CustomerMatchesResponse,
    responses=_RESPONSES,
)
async def assistant_lookup_customers(
    phone: str,
    payload: AssistantLookupCustomersRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerMatchesResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_LOOKUP_CUSTOMER"
    )
    matches = await _service(request, session).lookup_customers(
        actor, tenant.id, payload.query
    )
    if not matches:
        # Diagnóstico temporário, sem registrar o termo, telefone ou nome de
        # cliente: permite diferenciar falha de filtro da carteira de ausência
        # real de correspondência no tenant de produção.
        candidates = await CustomerPortfolioRepository(session).list_customers(
            PortfolioScope(tenant_id=tenant.id, owner_user_id=None),
            CustomerFilters(search=payload.query, active=True),
            limit=MAX_CANDIDATOS + 1,
            offset=0,
        )
        request.app.logger.info(
            "assistant_customer_lookup_miss tenant_matches=%d owner_matches=%s",
            len(candidates),
            any(customer.owner_user_id == actor.user_id for customer, _ in candidates),
        )
    return CustomerMatchesResponse(
        matches=[
            CustomerMatchResponse(
                customer_id=match.customer_id,
                legal_name=match.legal_name,
                trade_name=match.trade_name,
                document_number=match.document_number,
                state_code=match.state_code,
            )
            for match in matches[:MAX_CANDIDATOS]
        ],
        truncated=len(matches) > MAX_CANDIDATOS,
    )


@router.post(
    "/{phone}/assistant-v2/portfolio-customers",
    response_model=PortfolioCustomersResponse,
    responses=_RESPONSES,
)
async def assistant_list_portfolio_customers(
    phone: str,
    payload: AssistantListPortfolioCustomersRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortfolioCustomersResponse:
    tenant, actor = await _resolve_assistant_execution(
        request,
        session,
        tenant_slug,
        phone,
        payload.context,
        "CRM_REP_LIST_PORTFOLIO_CUSTOMERS",
    )
    result = await _service(request, session).list_portfolio_customers(
        actor, tenant.id, payload.query
    )
    return PortfolioCustomersResponse(
        matches=[CustomerMatchResponse(**match.__dict__) for match in result.matches],
        truncated=result.truncated,
        filter_label=result.filter_label,
        filter_suggestions=list(result.filter_suggestions),
    )


@router.post(
    "/{phone}/assistant-v2/customers/{customer_id}/price-list",
    response_model=ResolvedCustomerPriceListResponse,
    responses=_RESPONSES,
)
async def assistant_customer_price_list(
    phone: str,
    customer_id: uuid.UUID,
    payload: AssistantCustomerPriceListRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResolvedCustomerPriceListResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_GET_CUSTOMER_PRICE_LIST"
    )
    try:
        result = await _service(request, session).customer_price_list(
            actor, tenant.id, customer_id, origin_state=tenant.origin_state_code
        )
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="customer not found"
        ) from error
    except (IcmsRuleNotFound, AmbiguousIcmsRule) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (LocationUnavailable, PricesUnavailable, OriginNotConfigured, InvalidTaxRate) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return _price_list_response(result)


@router.post(
    "/{phone}/assistant-v2/customers/{customer_id}/conversation-summary",
    response_model=CustomerConversationSummaryResponse,
    responses=_RESPONSES,
)
async def assistant_customer_conversation_summary(
    phone: str,
    customer_id: uuid.UUID,
    payload: AssistantCustomerConversationSummaryRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerConversationSummaryResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context,
        "CRM_REP_GET_CUSTOMER_CONVERSATION_SUMMARY",
    )
    try:
        result = await _service(request, session).customer_conversation_summary(
            actor, tenant.id, customer_id
        )
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="customer not found"
        ) from error
    return CustomerConversationSummaryResponse(
        customer_id=result.customer.id,
        customer_name=result.customer.trade_name or result.customer.legal_name,
        interactions=[
            CustomerConversationEntryResponse(
                occurred_at=item.occurred_at,
                direction=item.direction.value if item.direction is not None else None,
                summary=item.summary,
            )
            for item in result.interactions
        ],
    )


@router.post(
    "/{phone}/assistant-v2/customer-intakes",
    response_model=CustomerIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_RESPONSES,
)
async def assistant_open_customer_intake(
    phone: str,
    payload: AssistantCustomerIntakeRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerIntakeResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_CREATE_CUSTOMER_INTAKE"
    )
    intake = payload.intake
    try:
        opened = await _intake_service(session).open(
            actor,
            tenant.id,
            idempotency_key=intake.idempotency_key,
            legal_name=intake.legal_name,
            state_code=intake.state_code,
            whatsapp_e164=intake.whatsapp_e164,
            preferred_products_text=intake.preferred_products_text,
            request_id=payload.context.request_id,
        )
    except WhatsappAlreadyUsed as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (InvalidStateCode, BlankField, InvalidWhatsappNumber) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    await session.commit()
    result = opened.intake
    return CustomerIntakeResponse(
        intake_id=result.id,
        status=result.status,
        legal_name=result.legal_name,
        state_code=result.state_code,
        has_whatsapp=result.whatsapp_e164 is not None,
        preferred_products_text=result.preferred_products_text,
        created_at=result.created_at,
        created=opened.created,
    )


@router.post(
    "/{phone}/assistant-v2/reminders",
    response_model=AssistantReminderResponse,
    responses=_RESPONSES,
)
async def assistant_create_reminder(
    phone: str,
    payload: AssistantCreateReminderRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssistantReminderResponse:
    """Cria compromisso pessoal do representante, idempotente pelo wamid."""
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_CREATE_REMINDER"
    )
    if payload.due_at.tzinfo is None or payload.due_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="due_at requires timezone")
    due_at = payload.due_at.astimezone(UTC)
    now = datetime.now(UTC)
    if due_at <= now or due_at > now + timedelta(days=366):
        raise HTTPException(status_code=422, detail="reminder due_at outside supported range")

    repository = ReminderRepository(session)
    reminder = await repository.get_by_source(tenant.id, payload.source_wamid)
    created = reminder is None
    if reminder is None:
        due_local = due_at.astimezone(ZoneInfo("America/Sao_Paulo"))
        slot_start = due_local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
        conflict = await repository.find_slot_conflict(
            tenant.id, actor.user_id, slot_start, slot_start + timedelta(hours=1)
        )
        if conflict is not None:
            raise HTTPException(status_code=409, detail="representative reminder slot conflict")
        reminder = RepresentativeReminder(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            representative_user_id=actor.user_id,
            customer_id=None,
            customer_contact_id=None,
            origin=ReminderOrigin.REPRESENTATIVE.value,
            kind=payload.kind,
            status=ReminderStatus.CONFIRMED.value,
            note=payload.note.strip(),
            due_at=due_at,
            timezone="America/Sao_Paulo",
            source_wamid=payload.source_wamid,
            source_line_reference=payload.context.assistant_line_phone_number_id,
        )
        repository.add(reminder)
        await session.commit()
    return AssistantReminderResponse(
        created=created,
        reminder_id=reminder.id,
        status=reminder.status,
        due_at=reminder.due_at,
        kind=reminder.kind,
    )


@router.post(
    "/{phone}/assistant-v2/price-updates/propose",
    response_model=AssistantPriceUpdateProposalResponse,
    responses=_RESPONSES,
)
async def assistant_propose_price_update(
    phone: str,
    payload: AssistantProposePriceUpdateRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssistantPriceUpdateProposalResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_UPDATE_PRICES"
    )
    try:
        source_file = None
        if payload.source_file is not None:
            try:
                content = base64.b64decode(payload.source_file.content_base64, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("invalid source file encoding") from error
            source_file = ProposedPriceSourceFile(
                filename=payload.source_file.filename,
                mime_type=payload.source_file.mime_type,
                content=content,
            )
        proposal = await RepresentativePriceUpdateService(session).propose(
            tenant_id=tenant.id,
            representative_user_id=actor.user_id,
            source_wamid=payload.source_wamid,
            reference_month=payload.reference_month,
            source_kind=payload.source_kind,
            source_file=source_file,
            rows=[
                ProposedPriceRow(row.sku, row.base_price, row.availability)
                for row in payload.rows
            ],
        )
    except PriceUpdateProposalForbidden as error:
        raise HTTPException(status_code=403, detail="price update proposal denied") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await session.commit()
    return AssistantPriceUpdateProposalResponse(
        proposal_id=proposal.proposal_id,
        reference_month=proposal.reference_month,
        ready_for_confirmation=proposal.ready_for_confirmation,
        duplicate_skus=proposal.duplicate_skus,
        unknown_skus=proposal.unknown_skus,
        changes=[PriceUpdateChangeResponse(**change.__dict__) for change in proposal.changes],
    )


@router.post(
    "/{phone}/assistant-v2/price-updates/{proposal_id}/confirm",
    response_model=AssistantPriceUpdateConfirmationResponse,
    responses=_RESPONSES,
)
async def assistant_confirm_price_update(
    phone: str,
    proposal_id: uuid.UUID,
    payload: AssistantConfirmPriceUpdateRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssistantPriceUpdateConfirmationResponse:
    tenant, actor = await _resolve_assistant_execution(
        request, session, tenant_slug, phone, payload.context, "CRM_REP_UPDATE_PRICES"
    )
    updates = RepresentativePriceUpdateService(session)
    try:
        batch = await updates.get_owned(tenant.id, actor.user_id, proposal_id)
    except PriceUpdateProposalNotFound as error:
        raise HTTPException(status_code=404, detail="price update proposal not found") from error
    except PriceUpdateProposalForbidden as error:
        raise HTTPException(status_code=403, detail="price update proposal denied") from error
    if batch.status == PriceListStatus.PUBLISHED:
        return AssistantPriceUpdateConfirmationResponse(
            proposal_id=batch.id, published=True, already_published=True
        )
    if batch.status != PriceListStatus.DRAFT:
        raise HTTPException(status_code=409, detail="price update proposal is not publishable")
    result = await PricePublicationService(
        session=session,
        entries=PriceEntryRepository(session),
        audit=AuditRepository(session),
    ).publish_batch(
        tenant_id=tenant.id,
        batch_id=batch.id,
        actor_user_id=actor.user_id,
        request_id=payload.context.request_id,
    )
    await session.commit()
    return AssistantPriceUpdateConfirmationResponse(
        proposal_id=batch.id,
        published=True,
        created=result.criados,
        updated=result.atualizados,
        unchanged=result.inalterados,
    )


def _price_list_response(resolvida) -> ResolvedCustomerPriceListResponse:
    return ResolvedCustomerPriceListResponse(
        customer_id=resolvida.customer.id,
        customer_name=resolvida.customer.legal_name,
        reference_month=resolvida.reference_month,
        origin_state=resolvida.origin_state,
        destination_state=resolvida.destination_state,
        currency=resolvida.currency,
        items=[
            CurrentPriceListItemResponse(
                product_id=item.product_id,
                family_name=item.family_name,
                sku=item.sku,
                display_name=item.display_name,
                specification=item.specification,
                unit=item.unit,
                availability=item.availability,
                base_price=item.base_price,
                final_price=item.final_price,
                tax_rate=item.tax_rate,
                expected_arrival_date=item.expected_arrival_date,
                arrival_note=item.arrival_note,
                notes=item.notes,
            )
            for item in resolvida.items
        ],
    )
