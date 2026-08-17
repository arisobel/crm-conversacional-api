"""As três leituras do representante, chamadas pelos executores do Gateway (W6).

O telefone vem no caminho, como em `/customers/by-whatsapp/{phone}`: é a única
identidade que o Gateway tem para oferecer, e é ela que decide de quem é a
carteira. Nenhuma destas rotas aceita um `user_id` — aceitar um permitiria ao
Gateway escolher a carteira que quisesse, e a autorização deixaria de ser
decidida aqui.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.core.states import InvalidStateCode
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customer_intakes import CustomerIntakeRepository
from crm_api.repositories.customers import CustomerRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.repositories.users import UserRepository
from crm_api.schemas.customer_intake import (
    CustomerIntakeResponse,
    OpenCustomerIntakeRequest,
)
from crm_api.schemas.price_lists import CurrentPriceListItemResponse
from crm_api.schemas.representative_whatsapp import (
    CustomerMatchesResponse,
    CustomerMatchResponse,
    PriceItemsResponse,
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
from crm_api.services.representative_whatsapp import (
    MAX_CANDIDATOS,
    NoPublishedCompetence,
    NotARepresentative,
    RepresentativeWhatsappService,
)
from crm_api.services.whatsapp_actor import (
    ActorNotFound,
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
        resolved=CustomerPriceListService(
            portfolio=portfolio,
            admin=admin,
            entries=entries,
            resolver=IcmsResolver(IcmsRuleRepository(session)),
            settings=settings,
        ),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
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
        encontrados = await _service(request, session).search_price_items(
            actor, tenant.id, query
        )
    except NotARepresentative as error:
        raise _forbidden(error) from error
    except NoPublishedCompetence as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return PriceItemsResponse(
        reference_month=encontrados.reference_month, items=encontrados.items
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
        encontrados = await _service(request, session).lookup_customers(
            actor, tenant.id, query
        )
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
    """Tabela de um cliente da carteira, convertida para a UF de entrega dele.

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


def _price_list_response(resolvida) -> ResolvedCustomerPriceListResponse:
    return ResolvedCustomerPriceListResponse(
        customer_id=resolvida.customer.id,
        customer_name=resolvida.customer.legal_name,
        reference_month=resolvida.reference_month,
        origin_state=resolvida.origin_state,
        destination_state=resolvida.location.state_code,
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
