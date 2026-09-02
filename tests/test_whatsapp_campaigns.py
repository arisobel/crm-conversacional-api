"""Rascunho de campanha de WhatsApp (F6.1, ADR-028).

O que está sob teste são as invariantes que o resto do plano F6 vai assumir
como dadas, e cada uma tem um teste que falha se alguém a afrouxar:

1. **Nenhum destinatário fora da carteira do ator** — para qualquer papel,
   inclusive `ADMIN`, enquanto a alçada da F6.0 não for decidida.
2. **Reentrega do comando não duplica campanha.** A chave de idempotência é
   decidida pela unicidade do banco, não pela checagem do serviço.
3. **O rascunho é fotografia**: mudar o cadastro depois não reescreve o que
   foi revisado.
4. **Representante não enxerga campanha alheia**, nem por lista nem por id —
   e o erro é o mesmo de campanha inexistente.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from sqlalchemy import func, select

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import AuditLog, UserRole
from crm_api.models.whatsapp_campaign import (
    CampaignStatus,
    RecipientStatus,
    WhatsappCampaign,
    WhatsappCampaignRecipient,
)
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.whatsapp_campaigns import WhatsappCampaignRepository
from crm_api.services.whatsapp_campaign import (
    BlankField,
    CampaignNotCancellable,
    CampaignNotFound,
    ContactMismatch,
    CreatedDraft,
    CustomerOutsidePortfolio,
    DraftRecipient,
    DuplicateRecipient,
    EmptyAudience,
    MissingExclusionReason,
    WhatsappCampaignService,
)

CONTATO_A = "+5511900001111"
CONTATO_B = "+5511900002222"


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    contato_a = CustomerContact(
        id=uuid4(),
        tenant_id=mundo.tenant_id,
        customer_id=mundo.customer_a_id,
        name="Compras Alfa",
        whatsapp_e164=CONTATO_A,
        is_primary=True,
    )
    contato_b = CustomerContact(
        id=uuid4(),
        tenant_id=mundo.tenant_id,
        customer_id=mundo.customer_b_id,
        name="Compras Beta",
        whatsapp_e164=CONTATO_B,
        is_primary=True,
    )
    async with mundo.app.state.session_factory() as session:
        session.add_all([contato_a, contato_b])
        await session.commit()

    mundo.__dict__["contact_a_id"] = contato_a.id
    mundo.__dict__["contact_b_id"] = contato_b.id
    yield mundo
    await mundo.app.state.engine.dispose()


def _service(session) -> WhatsappCampaignService:
    return WhatsappCampaignService(
        campaigns=WhatsappCampaignRepository(session),
        audit=AuditRepository(session),
    )


def _draft_kwargs(world, **overrides) -> dict:
    base = dict(
        actor_user_id=world.representative_a_id,
        actor_role=UserRole.REPRESENTATIVE,
        idempotency_key="draft-0001",
        criteria={"product_group": "poliéster"},
        template={"name": "oferta_mensal", "language": "pt_BR"},
        audience_summary={"eligible": 1, "excluded": 0},
        recipients=[
            DraftRecipient(
                customer_id=world.customer_a_id, contact_id=world.contact_a_id
            )
        ],
    )
    base.update(overrides)
    return base


async def _criar(world, session, **overrides) -> CreatedDraft:
    resultado = await _service(session).create_draft(
        world.tenant_id, **_draft_kwargs(world, **overrides)
    )
    await session.commit()
    return resultado


async def _contagem(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


# ------------------------------------------------------------------- criação


@pytest.mark.asyncio
async def test_criar_rascunho_persiste_fotografia_e_auditoria(world):
    async with world.app.state.session_factory() as session:
        resultado = await _criar(world, session)

    assert resultado.created is True
    campanha = resultado.campaign
    assert campanha.status is CampaignStatus.DRAFT
    assert campanha.confirmation is None
    assert campanha.gateway_campaign_id is None
    assert campanha.representative_user_id == world.representative_a_id

    async with world.app.state.session_factory() as session:
        linhas = list(await session.scalars(select(WhatsappCampaignRecipient)))
        assert len(linhas) == 1
        assert linhas[0].status is RecipientStatus.PENDING
        assert linhas[0].recipient_snapshot["whatsapp_e164"] == CONTATO_A
        assert linhas[0].recipient_snapshot["legal_name"] == "Alfa Tecelagem Ltda."

        trilha = await session.scalar(
            select(AuditLog).where(AuditLog.action == "WHATSAPP_CAMPAIGN_DRAFT_CREATED")
        )
        assert trilha is not None
        assert trilha.entity_id == campanha.id
        assert trilha.after["recipients_eligible"] == 1


@pytest.mark.asyncio
async def test_reentrega_da_mesma_chave_nao_duplica(world):
    async with world.app.state.session_factory() as session:
        primeira = await _criar(world, session)
    async with world.app.state.session_factory() as session:
        segunda = await _criar(world, session)
        assert segunda.created is False
        assert segunda.campaign.id == primeira.campaign.id
        assert await _contagem(session, WhatsappCampaign) == 1


@pytest.mark.asyncio
async def test_destinatario_de_outra_carteira_e_recusado(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(CustomerOutsidePortfolio):
            await _criar(
                world,
                session,
                recipients=[
                    DraftRecipient(
                        customer_id=world.customer_a_id, contact_id=world.contact_a_id
                    ),
                    DraftRecipient(
                        customer_id=world.customer_b_id, contact_id=world.contact_b_id
                    ),
                ],
            )
    # Uma linha inválida derruba o rascunho inteiro: nada foi gravado.
    async with world.app.state.session_factory() as session:
        assert await _contagem(session, WhatsappCampaign) == 0
        assert await _contagem(session, WhatsappCampaignRecipient) == 0


@pytest.mark.asyncio
async def test_admin_sem_carteira_nao_cria_em_nome_de_terceiros(world):
    """A alçada de `ADMIN` acima da própria carteira é pendência da F6.0.

    Enquanto ela não for decidida, o `ADMIN` só monta rascunho sobre clientes
    de que é titular — e este cenário não tem nenhum.
    """
    async with world.app.state.session_factory() as session:
        with pytest.raises(CustomerOutsidePortfolio):
            await _criar(
                world,
                session,
                actor_user_id=world.admin_id,
                actor_role=UserRole.ADMIN,
            )


@pytest.mark.asyncio
async def test_contato_de_outro_cliente_e_recusado(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(ContactMismatch):
            await _criar(
                world,
                session,
                recipients=[
                    DraftRecipient(
                        customer_id=world.customer_a_id, contact_id=world.contact_b_id
                    )
                ],
            )


@pytest.mark.asyncio
async def test_linha_sem_contato_exige_motivo(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(MissingExclusionReason):
            await _criar(
                world,
                session,
                recipients=[
                    DraftRecipient(
                        customer_id=world.customer_a_id, contact_id=world.contact_a_id
                    ),
                    DraftRecipient(customer_id=world.customer_a_id, contact_id=None),
                ],
            )


@pytest.mark.asyncio
async def test_exclusao_com_motivo_vira_linha_excluida(world):
    async with world.app.state.session_factory() as session:
        await _criar(
            world,
            session,
            recipients=[
                DraftRecipient(
                    customer_id=world.customer_a_id, contact_id=world.contact_a_id
                ),
                DraftRecipient(
                    customer_id=world.customer_a_id,
                    contact_id=None,
                    excluded_reason="sem contato elegível",
                ),
            ],
        )
    async with world.app.state.session_factory() as session:
        excluida = await session.scalar(
            select(WhatsappCampaignRecipient).where(
                WhatsappCampaignRecipient.status == RecipientStatus.EXCLUDED
            )
        )
        assert excluida is not None
        assert excluida.contact_id is None
        assert excluida.excluded_reason == "sem contato elegível"


@pytest.mark.asyncio
async def test_rascunho_todo_excluido_e_recusado(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(EmptyAudience):
            await _criar(
                world,
                session,
                recipients=[
                    DraftRecipient(
                        customer_id=world.customer_a_id,
                        contact_id=None,
                        excluded_reason="sem consentimento",
                    )
                ],
            )


@pytest.mark.asyncio
async def test_destinatario_duplicado_e_recusado(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(DuplicateRecipient):
            await _criar(
                world,
                session,
                recipients=[
                    DraftRecipient(
                        customer_id=world.customer_a_id, contact_id=world.contact_a_id
                    ),
                    DraftRecipient(
                        customer_id=world.customer_a_id, contact_id=world.contact_a_id
                    ),
                ],
            )


@pytest.mark.asyncio
async def test_criterios_vazios_sao_recusados(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(BlankField):
            await _criar(world, session, criteria={})


@pytest.mark.asyncio
async def test_fotografia_sobrevive_a_mudanca_cadastral(world):
    async with world.app.state.session_factory() as session:
        await _criar(world, session)

    async with world.app.state.session_factory() as session:
        cliente = await session.get(Customer, world.customer_a_id)
        cliente.legal_name = "Alfa Tecelagem e Fiação S.A."
        await session.commit()

    async with world.app.state.session_factory() as session:
        linha = await session.scalar(select(WhatsappCampaignRecipient))
        assert linha.recipient_snapshot["legal_name"] == "Alfa Tecelagem Ltda."


# ------------------------------------------------------------------ consulta


@pytest.mark.asyncio
async def test_representante_nao_alcanca_campanha_alheia(world):
    async with world.app.state.session_factory() as session:
        criada = await _criar(world, session)

    async with world.app.state.session_factory() as session:
        service = _service(session)
        with pytest.raises(CampaignNotFound):
            await service.get_campaign(
                world.tenant_id,
                criada.campaign.id,
                actor_user_id=world.representative_b_id,
                actor_role=UserRole.REPRESENTATIVE,
            )
        linhas, total = await service.list_campaigns(
            world.tenant_id,
            actor_user_id=world.representative_b_id,
            actor_role=UserRole.REPRESENTATIVE,
        )
        assert linhas == [] and total == 0


@pytest.mark.asyncio
async def test_dona_consulta_com_destinatarios(world):
    async with world.app.state.session_factory() as session:
        criada = await _criar(world, session)

    async with world.app.state.session_factory() as session:
        campanha, destinatarios = await _service(session).get_campaign(
            world.tenant_id,
            criada.campaign.id,
            actor_user_id=world.representative_a_id,
            actor_role=UserRole.REPRESENTATIVE,
        )
        assert campanha.id == criada.campaign.id
        assert len(destinatarios) == 1


@pytest.mark.asyncio
async def test_admin_ve_o_tenant_e_filtra_por_representante(world):
    async with world.app.state.session_factory() as session:
        await _criar(world, session)

    async with world.app.state.session_factory() as session:
        service = _service(session)
        linhas, total = await service.list_campaigns(
            world.tenant_id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
        )
        assert total == 1 and len(linhas) == 1

        _, sem_resultado = await service.list_campaigns(
            world.tenant_id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
            representative_user_id=world.representative_b_id,
        )
        assert sem_resultado == 0


@pytest.mark.asyncio
async def test_filtro_por_representante_e_ignorado_para_representante(world):
    """Como o `owner_user_id` ignorado no cadastro (R2): o recorte do papel
    prevalece sobre o filtro pedido."""
    async with world.app.state.session_factory() as session:
        await _criar(world, session)

    async with world.app.state.session_factory() as session:
        linhas, total = await _service(session).list_campaigns(
            world.tenant_id,
            actor_user_id=world.representative_b_id,
            actor_role=UserRole.REPRESENTATIVE,
            representative_user_id=world.representative_a_id,
        )
        assert linhas == [] and total == 0


@pytest.mark.asyncio
async def test_isolamento_de_tenant_no_repositorio(world):
    """Exercita o repositório isolado, sem passar por serviço — o mesmo
    desenho do teste de carteira de R1."""
    async with world.app.state.session_factory() as session:
        criada = await _criar(world, session)

    async with world.app.state.session_factory() as session:
        repo = WhatsappCampaignRepository(session)
        outro_tenant = uuid4()
        assert await repo.get(outro_tenant, criada.campaign.id) is None
        assert await repo.list(outro_tenant) == []
        assert await repo.count(outro_tenant) == 0


# -------------------------------------------------------------- cancelamento


@pytest.mark.asyncio
async def test_cancelar_rascunho_e_idempotente_e_auditado(world):
    async with world.app.state.session_factory() as session:
        criada = await _criar(world, session)

    async with world.app.state.session_factory() as session:
        cancelada = await _service(session).cancel_draft(
            world.tenant_id,
            criada.campaign.id,
            actor_user_id=world.representative_a_id,
            actor_role=UserRole.REPRESENTATIVE,
        )
        await session.commit()
        assert cancelada.status is CampaignStatus.CANCELLED

    async with world.app.state.session_factory() as session:
        de_novo = await _service(session).cancel_draft(
            world.tenant_id,
            criada.campaign.id,
            actor_user_id=world.representative_a_id,
            actor_role=UserRole.REPRESENTATIVE,
        )
        assert de_novo.status is CampaignStatus.CANCELLED
        trilhas = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "WHATSAPP_CAMPAIGN_CANCELLED")
        )
        # Cancelar o já cancelado é no-op: uma única entrada na trilha.
        assert trilhas == 1


@pytest.mark.asyncio
async def test_cancelamento_fora_do_alcance_e_nao_encontrado(world):
    async with world.app.state.session_factory() as session:
        criada = await _criar(world, session)

    async with world.app.state.session_factory() as session:
        with pytest.raises(CampaignNotFound):
            await _service(session).cancel_draft(
                world.tenant_id,
                criada.campaign.id,
                actor_user_id=world.representative_b_id,
                actor_role=UserRole.REPRESENTATIVE,
            )
    async with world.app.state.session_factory() as session:
        intacta = await session.get(WhatsappCampaign, criada.campaign.id)
        assert intacta.status is CampaignStatus.DRAFT


@pytest.mark.asyncio
async def test_campanha_confirmada_nao_e_cancelavel_por_este_fluxo(world):
    """O cancelamento de pendências de campanha confirmada é fluxo da F6.4,
    com o Gateway; este serviço só desfaz o que ainda não foi aprovado."""
    async with world.app.state.session_factory() as session:
        criada = await _criar(world, session)

    async with world.app.state.session_factory() as session:
        campanha = await session.get(WhatsappCampaign, criada.campaign.id)
        campanha.confirmation = {"actor": str(world.representative_a_id)}
        campanha.status = CampaignStatus.CONFIRMED
        await session.commit()

    async with world.app.state.session_factory() as session:
        with pytest.raises(CampaignNotCancellable):
            await _service(session).cancel_draft(
                world.tenant_id,
                criada.campaign.id,
                actor_user_id=world.representative_a_id,
                actor_role=UserRole.REPRESENTATIVE,
            )
