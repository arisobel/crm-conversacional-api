"""Telas de campanha de WhatsApp (F6.3).

Roteador próprio, e não mais um bloco em `routes.py`: aquele módulo já passa de
1800 linhas e trata de cadastro comercial, que não é isto.

**A confirmação não existe nesta fase, e a tela diz isso.** Enquanto o contrato
com o Gateway não estiver fechado (F6.4), uma campanha só chega a rascunho. Não
há botão de confirmar, nenhum estado é apresentado como "enviado" e o template
Meta não é escolhido aqui — o catálogo de templates é do Gateway, e inventar um
identificador que a Meta não aprovou seria fabricar o dado que falta.

O rascunho é criado **re-resolvendo os critérios**, nunca a partir da lista de
destinatários que veio do formulário. Um POST forjado com clientes de outra
carteira não teria efeito de qualquer forma — o serviço da F6.1 recusa —, mas
re-resolver é o que garante que o congelado é o que o resolvedor produziu.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser
from crm_api.core.database import get_session
from crm_api.core.states import InvalidStateCode, normalize_state_code
from crm_api.models.user import UserRole
from crm_api.models.whatsapp_campaign import CampaignStatus
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.campaign_audience import AudienceRepository
from crm_api.repositories.catalog import CatalogRepository
from crm_api.repositories.textile import TextileRepository
from crm_api.repositories.whatsapp_campaigns import WhatsappCampaignRepository
from crm_api.services.whatsapp_campaign import (
    BlankField,
    CampaignNotCancellable,
    CampaignNotFound,
    EmptyAudience,
    WhatsappCampaignService,
)
from crm_api.services.whatsapp_campaign_audience import (
    AudienceResolver,
    EmptyCriteria,
    UnknownCriterion,
    UnknownFiber,
    UnknownProduct,
    UnknownProductGroup,
)
from crm_api.web.csrf import CSRF_FIELD_NAME, csrf_is_valid
from crm_api.web.dependencies import portal_user
from crm_api.web.rendering import redirect, render

router = APIRouter(prefix="/portal/campaigns", tags=["Portal"])

LISTA = "/portal/campaigns"

# Enquanto o catálogo do Gateway não existe, o template fica declaradamente
# pendente. É o valor que vai para o `template_snapshot` e o que a tela explica.
TEMPLATE_PENDENTE = {"status": "PENDENTE_CATALOGO_GATEWAY"}

# Erros de critério cuja **mensagem** é a informação útil: elas nascem escritas
# para quem lê a tela ("porte ainda não é atributo do cliente"). Voltam pela
# própria resposta do POST, sem passar pela query string — ver `render`.
_ERROS_DE_CRITERIO = (
    UnknownCriterion,
    EmptyCriteria,
    UnknownProductGroup,
    UnknownFiber,
    UnknownProduct,
    InvalidStateCode,
)


def _recusa_de_criterio(error: Exception) -> tuple[str | None, str | None]:
    """Traduz o erro em `(código, texto)` para a página de recusa.

    `InvalidStateCode` é a exceção à regra: a mensagem dela é interna e em
    inglês, e o aceite do portal exige erro em português. Ela usa o código já
    existente; as demais já vêm escritas para o usuário.
    """
    if isinstance(error, InvalidStateCode):
        return "uf-invalida", None
    return None, str(error)

_Multi = Annotated[list[str], Form()]
_Opcional = Annotated[str | None, Form()]


def _service(session: AsyncSession) -> WhatsappCampaignService:
    return WhatsappCampaignService(
        campaigns=WhatsappCampaignRepository(session),
        audit=AuditRepository(session),
    )


def _resolver(session: AsyncSession) -> AudienceResolver:
    return AudienceResolver(audience=AudienceRepository(session))


def _escopo(current_user: CurrentUser) -> uuid.UUID | None:
    """`None` é "todo o tenant", e só sai para `ADMIN` e `MANAGER`."""
    return (
        current_user.user_id if current_user.role is UserRole.REPRESENTATIVE else None
    )


def _criterios(
    grupos: list[str],
    fibras: list[str],
    percentual: str | None,
    ufs: str | None,
    carteira_inteira: str | None,
) -> dict:
    """Traduz o formulário no mapa que `AudienceCriteria` sabe validar.

    Campos em branco são **omitidos**, não enviados vazios: o validador
    distingue "não pedi este eixo" de "pedi e não casou nada", e um `[]` no
    lugar de ausência apagaria a diferença.
    """
    bruto: dict = {}
    if grupos:
        bruto["product_group_ids"] = [uuid.UUID(g) for g in grupos if g]
    if fibras:
        bruto["fiber_codes"] = [f for f in fibras if f]
    if percentual and percentual.strip():
        bruto["min_fiber_percent"] = percentual.strip().replace(",", ".")
    if ufs and ufs.strip():
        bruto["state_codes"] = [
            normalize_state_code(uf) for uf in ufs.replace(";", ",").split(",") if uf.strip()
        ]
    if carteira_inteira:
        bruto["include_entire_portfolio"] = True
    return bruto


async def _nomes_de_grupo(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, str]:
    """Id → nome atual, para a tela não exibir UUID cru como critério.

    Inclui os inativos: uma campanha antiga pode ter usado um grupo que depois
    saiu de circulação, e mostrar o id dele seria pior do que mostrar o nome.
    """
    grupos = await CatalogRepository(session).list_groups(tenant_id, active=None)
    return {str(grupo.id): grupo.name for grupo in grupos}


async def _contexto_do_formulario(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Os eixos disponíveis para montar o critério, vindos do cadastro.

    A tela oferece apenas o que existe: grupos e fibras cadastrados. É a forma
    de não permitir que alguém digite um eixo que o domínio não modela.
    """
    return {
        "grupos": await CatalogRepository(session).list_groups(tenant_id),
        "fibras": await TextileRepository(session).list_fibers(tenant_id),
        "nomes_de_grupo": await _nomes_de_grupo(session, tenant_id),
        "template_pendente": True,
    }


@router.get("", include_in_schema=False)
async def pagina_campanhas(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    situacao: Annotated[str | None, Query()] = None,
    m: Annotated[str | None, Query()] = None,
) -> Response:
    """Lista recortada pelo papel: o representante vê as suas, a gestão vê o
    tenant."""
    estado = None
    if situacao:
        try:
            estado = CampaignStatus(situacao)
        except ValueError:
            estado = None

    campanhas, total = await _service(session).list_campaigns(
        current_user.tenant_id,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role,
        status=estado,
    )
    return render(
        request,
        "campaigns.html",
        {
            "campanhas": campanhas,
            "total": total,
            "situacao": situacao or "",
            "situacoes": [e.value for e in CampaignStatus],
            "nomes_de_grupo": await _nomes_de_grupo(session, current_user.tenant_id),
        },
        current_user=current_user,
        mensagem=m,
    )


@router.get("/nova", include_in_schema=False)
async def pagina_nova_campanha(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    contexto = await _contexto_do_formulario(session, current_user.tenant_id)
    return render(
        request,
        "campaign_new.html",
        {**contexto, "previa": None, "criterios_form": {}},
        current_user=current_user,
        mensagem=m,
    )


@router.post("/previa", include_in_schema=False)
async def gerar_previa(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    product_group_ids: _Multi = [],  # noqa: B006 -- FastAPI lê a anotação, não muta
    fiber_codes: _Multi = [],  # noqa: B006
    min_fiber_percent: _Opcional = None,
    state_codes: _Opcional = None,
    include_entire_portfolio: _Opcional = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Resolve o público e devolve a revisão. **Não grava nada.**"""
    if not csrf_is_valid(request, csrf_token):
        return redirect(f"{LISTA}/nova", "csrf")

    contexto = await _contexto_do_formulario(session, current_user.tenant_id)
    escolhido = {
        "product_group_ids": product_group_ids,
        "fiber_codes": fiber_codes,
        "min_fiber_percent": min_fiber_percent or "",
        "state_codes": state_codes or "",
        "include_entire_portfolio": bool(include_entire_portfolio),
    }

    try:
        bruto = _criterios(
            product_group_ids,
            fiber_codes,
            min_fiber_percent,
            state_codes,
            include_entire_portfolio,
        )
        previa = await _resolver(session).resolve(
            current_user.tenant_id,
            bruto,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
        )
    except _ERROS_DE_CRITERIO as error:
        codigo, texto = _recusa_de_criterio(error)
        return render(
            request,
            "campaign_new.html",
            {**contexto, "previa": None, "criterios_form": escolhido},
            current_user=current_user,
            mensagem=codigo,
            erro_direto=texto,
            status_code=422,
        )

    return render(
        request,
        "campaign_new.html",
        {**contexto, "previa": previa, "criterios_form": escolhido},
        current_user=current_user,
    )


@router.post("", include_in_schema=False)
async def criar_rascunho(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str, Form()],
    product_group_ids: _Multi = [],  # noqa: B006
    fiber_codes: _Multi = [],  # noqa: B006
    min_fiber_percent: _Opcional = None,
    state_codes: _Opcional = None,
    include_entire_portfolio: _Opcional = None,
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    """Congela o rascunho a partir dos critérios, re-resolvidos agora.

    A lista revisada na tela anterior não é transportada: ela seria uma segunda
    fonte de verdade, e uma divergência entre as duas passaria despercebida. O
    que a revisão garante é que a pessoa viu o resultado destes critérios; o que
    o rascunho congela é o resultado deles no instante da criação.
    """
    if not csrf_is_valid(request, csrf_token):
        return redirect(f"{LISTA}/nova", "csrf")

    contexto = await _contexto_do_formulario(session, current_user.tenant_id)
    escolhido = {
        "product_group_ids": product_group_ids,
        "fiber_codes": fiber_codes,
        "min_fiber_percent": min_fiber_percent or "",
        "state_codes": state_codes or "",
        "include_entire_portfolio": bool(include_entire_portfolio),
    }

    def _recusa(texto: str | None, codigo: str | None = None) -> Response:
        return render(
            request,
            "campaign_new.html",
            {**contexto, "previa": None, "criterios_form": escolhido},
            current_user=current_user,
            mensagem=codigo,
            erro_direto=texto,
            status_code=422,
        )

    try:
        bruto = _criterios(
            product_group_ids,
            fiber_codes,
            min_fiber_percent,
            state_codes,
            include_entire_portfolio,
        )
        previa = await _resolver(session).resolve(
            current_user.tenant_id,
            bruto,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
        )
    except _ERROS_DE_CRITERIO as error:
        codigo, texto = _recusa_de_criterio(error)
        return _recusa(texto, codigo)

    try:
        criada = await _service(session).create_draft(
            current_user.tenant_id,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
            idempotency_key=idempotency_key,
            criteria=previa.normalized_criteria,
            template=TEMPLATE_PENDENTE,
            audience_summary=previa.counts,
            recipients=previa.to_draft_recipients(),
        )
    except EmptyAudience:
        await session.rollback()
        return _recusa(
            "Nenhum destinatário elegível para estes critérios. Ajuste o"
            " critério ou complete o cadastro dos contatos."
        )
    except BlankField:
        await session.rollback()
        return _recusa("Informe a identificação do pedido.")
    except Exception:  # noqa: BLE001 -- recusa genérica; a mensagem interna não vai à tela
        # As demais exceções do serviço carregam identificadores internos na
        # mensagem — um `str(error)` aqui despejaria UUID na tela, contra o
        # aceite de R6a ("erros de domínio aparecem em português").
        await session.rollback()
        return _recusa("Não foi possível criar o rascunho com estes critérios.")

    await session.commit()
    return redirect(f"{LISTA}/{criada.campaign.id}", "campanha-criada")


@router.get("/{campaign_id}", include_in_schema=False)
async def pagina_campanha(
    request: Request,
    campaign_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    m: Annotated[str | None, Query()] = None,
) -> Response:
    try:
        campanha, destinatarios = await _service(session).get_campaign(
            current_user.tenant_id,
            campaign_id,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
        )
    except CampaignNotFound:
        return redirect(LISTA, "nao-encontrado")

    return render(
        request,
        "campaign_detail.html",
        {
            "campanha": campanha,
            "destinatarios": destinatarios,
            "nomes_de_grupo": await _nomes_de_grupo(session, current_user.tenant_id),
            # Só o dono do rascunho cancela; a gestão lê. A alçada acima da
            # própria carteira é pendência da F6.0.
            "pode_cancelar": (
                campanha.status is CampaignStatus.DRAFT
                and campanha.representative_user_id == current_user.user_id
            ),
        },
        current_user=current_user,
        mensagem=m,
    )


@router.post("/{campaign_id}/cancelar", include_in_schema=False)
async def cancelar_campanha(
    request: Request,
    campaign_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(portal_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    csrf_token: Annotated[str, Form(alias=CSRF_FIELD_NAME)] = "",
) -> Response:
    destino = f"{LISTA}/{campaign_id}"
    if not csrf_is_valid(request, csrf_token):
        return redirect(destino, "csrf")

    try:
        await _service(session).cancel_draft(
            current_user.tenant_id,
            campaign_id,
            actor_user_id=current_user.user_id,
            actor_role=current_user.role,
            request_id=request.headers.get("x-request-id"),
        )
    except CampaignNotFound:
        await session.rollback()
        return redirect(LISTA, "nao-encontrado")
    except CampaignNotCancellable:
        await session.rollback()
        return redirect(destino, "campanha-nao-cancelavel")

    await session.commit()
    return redirect(destino, "campanha-cancelada")
