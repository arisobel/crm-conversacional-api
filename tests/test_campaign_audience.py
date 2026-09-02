"""Resolvedor determinístico de audiência (F6.2, ADR-028).

O cenário é montado para que cada balde da prévia tenha um habitante, porque a
afirmação que interessa não é "o filtro funciona" — é **o que acontece com
quem não entra**:

- `cliente_a` casa e recebe: elegível.
- `cliente_sem_contato` casa e não pode receber: excluído, com motivo, e
  continua visível na prévia.
- `cliente_ambiguo` casa e tem dois contatos sem principal: excluído, porque
  eleger um por ordem de cadastro mandaria a mensagem por acaso.
- `cliente_indeterminado` prefere artigo sem composição cadastrada: **não
  classificado**, que não é o mesmo que "não tem poliéster" (ADR-027).
- `customer_b`, da carteira do representante B, não aparece em nenhum deles.
"""

import uuid
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world, persist

from crm_api.models.catalog import (
    CustomerPreferredProduct,
    Product,
    ProductGroup,
    ProductGroupMember,
)
from crm_api.models.customer import Customer, CustomerLocation
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.textile import Fiber, ProductComposition
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.campaign_audience import AudienceRepository
from crm_api.repositories.whatsapp_campaigns import WhatsappCampaignRepository
from crm_api.services.whatsapp_campaign import WhatsappCampaignService
from crm_api.services.whatsapp_campaign_audience import (
    CONTATO_AMBIGUO,
    SEM_CONTATO_ATIVO,
    AudienceCriteria,
    AudienceResolver,
    EmptyCriteria,
    UnknownCriterion,
    UnknownFiber,
    UnknownProduct,
    UnknownProductGroup,
)


class Cenario:
    """Ids do mundo montado pela fixture, para o teste não caçar por nome."""

    def __init__(self, mundo, **ids):
        self.mundo = mundo
        self.__dict__.update(ids)

    @property
    def app(self):
        return self.mundo.app

    @property
    def tenant_id(self):
        return self.mundo.tenant_id


@pytest_asyncio.fixture
async def cenario():
    mundo = await build_portal_world()
    tenant = mundo.tenant_id
    objetos: list = []

    def cliente(nome: str, uf: str, dono) -> Customer:
        registro = Customer(
            id=uuid4(),
            tenant_id=tenant,
            legal_name=nome,
            state_code=uf,
            owner_user_id=dono,
            active=True,
        )
        objetos.append(registro)
        objetos.append(
            CustomerLocation(
                id=uuid4(),
                tenant_id=tenant,
                customer_id=registro.id,
                label="Principal",
                state_code=uf,
                is_default=True,
            )
        )
        return registro

    def contato(dono: Customer, telefone: str, *, principal: bool) -> CustomerContact:
        registro = CustomerContact(
            id=uuid4(),
            tenant_id=tenant,
            customer_id=dono.id,
            name=f"Compras {dono.legal_name}",
            whatsapp_e164=telefone,
            is_primary=principal,
        )
        objetos.append(registro)
        return registro

    def prefere(dono: Customer, produto_id: uuid.UUID) -> None:
        objetos.append(
            CustomerPreferredProduct(
                id=uuid4(),
                tenant_id=tenant,
                customer_id=dono.id,
                product_id=produto_id,
                active=True,
            )
        )

    # --- catálogo: um artigo de poliéster, um de algodão, um sem composição ---
    familia_id = None
    async with mundo.app.state.session_factory() as session:
        from sqlalchemy import select

        familia_id = await session.scalar(select(Product.family_id))

    produto_algodao = Product(
        id=uuid4(),
        tenant_id=tenant,
        family_id=familia_id,
        sku="ALG-30-1",
        commercial_name="30/1 penteado",
    )
    produto_sem_composicao = Product(
        id=uuid4(),
        tenant_id=tenant,
        family_id=familia_id,
        sku="MIX-40",
        commercial_name="40 mescla",
    )
    objetos += [produto_algodao, produto_sem_composicao]

    pes = Fiber(id=uuid4(), tenant_id=tenant, code="PES", name="Poliéster")
    algodao = Fiber(id=uuid4(), tenant_id=tenant, code="CO", name="Algodão")
    objetos += [pes, algodao]
    objetos += [
        # O artigo do mundo base é 92% poliéster — o bastante para casar com um
        # piso de 60% e não casar com um de 95%.
        ProductComposition(
            id=uuid4(),
            tenant_id=tenant,
            product_id=mundo.product_id,
            fiber_id=pes.id,
            percent=Decimal("92.00"),
        ),
        ProductComposition(
            id=uuid4(),
            tenant_id=tenant,
            product_id=produto_algodao.id,
            fiber_id=algodao.id,
            percent=Decimal("100.00"),
        ),
    ]

    grupo_poliester = ProductGroup(
        id=uuid4(),
        tenant_id=tenant,
        name="Poliéster",
        normalized_name="poliester",
    )
    grupo_vazio = ProductGroup(
        id=uuid4(),
        tenant_id=tenant,
        name="Alta tenacidade",
        normalized_name="alta tenacidade",
    )
    objetos += [grupo_poliester, grupo_vazio]
    objetos.append(
        ProductGroupMember(
            id=uuid4(),
            tenant_id=tenant,
            group_id=grupo_poliester.id,
            product_id=mundo.product_id,
        )
    )

    # --- clientes da carteira do representante A ---
    rep_a = mundo.representative_a_id
    sem_contato = cliente("Delta Sem Contato Ltda.", "SP", rep_a)
    prefere(sem_contato, mundo.product_id)

    ambiguo = cliente("Epsilon Ambigua Ltda.", "SP", rep_a)
    prefere(ambiguo, mundo.product_id)
    contato(ambiguo, "+5511900010001", principal=False)
    contato(ambiguo, "+5511900010002", principal=False)

    indeterminado = cliente("Zeta Indeterminada Ltda.", "SP", rep_a)
    prefere(indeterminado, produto_sem_composicao.id)
    contato(indeterminado, "+5511900010003", principal=True)

    de_algodao = cliente("Eta Algodao Ltda.", "RS", rep_a)
    prefere(de_algodao, produto_algodao.id)
    contato(de_algodao, "+5511900010004", principal=True)

    async with mundo.app.state.session_factory() as session:
        # O cliente A do mundo base já prefere o artigo de poliéster; falta o
        # contato dele e o do cliente da carteira B, que nunca deve aparecer.
        objetos.append(
            CustomerContact(
                id=uuid4(),
                tenant_id=tenant,
                customer_id=mundo.customer_a_id,
                name="Compras Alfa",
                whatsapp_e164="+5511900020001",
                is_primary=True,
            )
        )
        objetos.append(
            CustomerContact(
                id=uuid4(),
                tenant_id=tenant,
                customer_id=mundo.customer_b_id,
                name="Compras Beta",
                whatsapp_e164="+5511900020002",
                is_primary=True,
            )
        )
        objetos.append(
            CustomerPreferredProduct(
                id=uuid4(),
                tenant_id=tenant,
                customer_id=mundo.customer_b_id,
                product_id=mundo.product_id,
                active=True,
            )
        )
        await persist(session, objetos)
        await session.commit()

    yield Cenario(
        mundo,
        grupo_poliester_id=grupo_poliester.id,
        grupo_vazio_id=grupo_vazio.id,
        produto_algodao_id=produto_algodao.id,
        produto_sem_composicao_id=produto_sem_composicao.id,
        sem_contato_id=sem_contato.id,
        ambiguo_id=ambiguo.id,
        indeterminado_id=indeterminado.id,
        de_algodao_id=de_algodao.id,
    )
    await mundo.app.state.engine.dispose()


def _resolver(session) -> AudienceResolver:
    return AudienceResolver(audience=AudienceRepository(session))


async def _resolve(cenario, criterios: dict, *, ator=None, papel=UserRole.REPRESENTATIVE):
    async with cenario.app.state.session_factory() as session:
        return await _resolver(session).resolve(
            cenario.tenant_id,
            criterios,
            actor_user_id=ator or cenario.mundo.representative_a_id,
            actor_role=papel,
        )


def _ids(membros) -> set:
    return {m.customer.id for m in membros}


# ------------------------------------------------------- validação de critério


def test_chave_desconhecida_e_recusada():
    with pytest.raises(UnknownCriterion, match="desconhecido"):
        AudienceCriteria.from_mapping({"cor_favorita": ["azul"]})


def test_porte_tem_mensagem_propria():
    """O eixo foi pedido pelo negócio e ainda não existe. Dizer 'não modelado'
    é acionável; dizer 'desconhecido' faz parecer erro de digitação."""
    with pytest.raises(UnknownCriterion, match="declarado"):
        AudienceCriteria.from_mapping({"porte": "grande"})


def test_curva_abc_nao_pode_ser_inferida():
    with pytest.raises(UnknownCriterion, match="inferida"):
        AudienceCriteria.from_mapping({"curva_abc": "A"})


def test_criterio_vazio_nao_significa_carteira_inteira():
    with pytest.raises(EmptyCriteria, match="include_entire_portfolio"):
        AudienceCriteria.from_mapping({})


def test_percentual_sem_fibra_e_recusado():
    with pytest.raises(UnknownCriterion, match="fiber_codes"):
        AudienceCriteria.from_mapping({"min_fiber_percent": 60})


def test_percentual_fora_da_faixa_e_recusado():
    with pytest.raises(UnknownCriterion, match="entre 0 e 100"):
        AudienceCriteria.from_mapping({"fiber_codes": ["PES"], "min_fiber_percent": 140})


def test_forma_canonica_e_estavel():
    """Dois pedidos equivalentes produzem o mesmo snapshot."""
    um = AudienceCriteria.from_mapping({"fiber_codes": ["pes", "CO"], "state_codes": ["sp"]})
    outro = AudienceCriteria.from_mapping({"state_codes": ["SP"], "fiber_codes": ["CO", "pes"]})
    assert um.normalized() == outro.normalized()
    assert um.normalized() == {"fiber_codes": ["CO", "PES"], "state_codes": ["SP"]}


# --------------------------------------------------------------- eixo e escopo


@pytest.mark.asyncio
async def test_grupo_seleciona_quem_prefere_artigo_do_grupo(cenario):
    previa = await _resolve(cenario, {"product_group_ids": [cenario.grupo_poliester_id]})

    assert _ids(previa.eligible) == {cenario.mundo.customer_a_id}
    assert _ids(previa.excluded) == {cenario.sem_contato_id, cenario.ambiguo_id}
    # O cliente da carteira do representante B não aparece em balde nenhum.
    assert cenario.mundo.customer_b_id not in _ids(previa.eligible) | _ids(previa.excluded)


@pytest.mark.asyncio
async def test_carteira_alheia_nunca_entra_nem_para_admin(cenario):
    """A carteira é a do ator, qualquer que seja o papel — a alçada de `ADMIN`
    sobre outra carteira é pendência da F6.0."""
    previa = await _resolve(
        cenario,
        {"product_group_ids": [cenario.grupo_poliester_id]},
        ator=cenario.mundo.admin_id,
        papel=UserRole.ADMIN,
    )
    assert previa.counts["total"] == 0


@pytest.mark.asyncio
async def test_fibra_com_piso_de_percentual(cenario):
    """O artigo é 92% poliéster: entra com piso de 60, sai com piso de 95."""
    com_60 = await _resolve(
        cenario, {"fiber_codes": ["PES"], "min_fiber_percent": 60}
    )
    assert cenario.mundo.customer_a_id in _ids(com_60.eligible)

    com_95 = await _resolve(
        cenario, {"fiber_codes": ["PES"], "min_fiber_percent": 95}
    )
    assert com_95.counts["eligible"] == 0


@pytest.mark.asyncio
async def test_eixos_de_produto_se_cruzam(cenario):
    """Grupo E fibra: o artigo precisa ser as duas coisas.

    O grupo vazio não tem artigo nenhum, então a interseção com poliéster é
    vazia — e o resultado é público zero, não a soma dos dois eixos.
    """
    previa = await _resolve(
        cenario,
        {"product_group_ids": [cenario.grupo_vazio_id], "fiber_codes": ["PES"]},
    )
    assert previa.counts["total"] == 0


@pytest.mark.asyncio
async def test_uf_recorta_o_publico(cenario):
    previa = await _resolve(cenario, {"include_entire_portfolio": True, "state_codes": ["RS"]})
    assert _ids(previa.eligible) == {cenario.de_algodao_id}


@pytest.mark.asyncio
async def test_carteira_inteira_e_escolha_explicita(cenario):
    previa = await _resolve(cenario, {"include_entire_portfolio": True})
    todos = _ids(previa.eligible) | _ids(previa.excluded)
    assert cenario.mundo.customer_b_id not in todos
    assert cenario.mundo.customer_a_id in todos
    assert cenario.de_algodao_id in todos


# ------------------------------------------------------ critério inexistente


@pytest.mark.asyncio
async def test_grupo_inexistente_falha_em_vez_de_encolher(cenario):
    with pytest.raises(UnknownProductGroup):
        await _resolve(cenario, {"product_group_ids": [uuid4()]})


@pytest.mark.asyncio
async def test_fibra_desconhecida_falha(cenario):
    with pytest.raises(UnknownFiber, match="XX"):
        await _resolve(cenario, {"fiber_codes": ["XX"]})


@pytest.mark.asyncio
async def test_artigo_inexistente_falha(cenario):
    with pytest.raises(UnknownProduct):
        await _resolve(cenario, {"product_ids": [uuid4()]})


# -------------------------------------------------------------- os três baldes


@pytest.mark.asyncio
async def test_sem_contato_ativo_e_excluido_com_motivo(cenario):
    previa = await _resolve(cenario, {"product_group_ids": [cenario.grupo_poliester_id]})
    excluido = next(m for m in previa.excluded if m.customer.id == cenario.sem_contato_id)
    assert excluido.excluded_reason == SEM_CONTATO_ATIVO
    assert excluido.contact is None


@pytest.mark.asyncio
async def test_contatos_ambiguos_nao_elegem_um_por_acaso(cenario):
    previa = await _resolve(cenario, {"product_group_ids": [cenario.grupo_poliester_id]})
    excluido = next(m for m in previa.excluded if m.customer.id == cenario.ambiguo_id)
    assert excluido.excluded_reason == CONTATO_AMBIGUO
    assert excluido.contact is None


@pytest.mark.asyncio
async def test_artigo_sem_composicao_nao_vira_negativa(cenario):
    """O cliente sai no terceiro balde: não é elegível e não é exclusão
    comercial — é lacuna de cadastro, que some quando alguém a preencher."""
    previa = await _resolve(cenario, {"fiber_codes": ["PES"]})

    indeterminados = {c.id for c in previa.unclassified}
    assert cenario.indeterminado_id in indeterminados
    assert cenario.indeterminado_id not in _ids(previa.eligible)
    assert cenario.indeterminado_id not in _ids(previa.excluded)


@pytest.mark.asyncio
async def test_grupo_nao_produz_indeterminado(cenario):
    """Não estar num grupo é um fato — alguém curou a lista. Só a composição
    ausente é lacuna."""
    previa = await _resolve(cenario, {"product_group_ids": [cenario.grupo_poliester_id]})
    assert previa.unclassified == []


@pytest.mark.asyncio
async def test_contagens_batem_com_as_listas(cenario):
    previa = await _resolve(cenario, {"fiber_codes": ["PES"]})
    assert previa.counts["eligible"] == len(previa.eligible)
    assert previa.counts["excluded"] == len(previa.excluded)
    assert previa.counts["unclassified"] == len(previa.unclassified)
    assert previa.counts["total"] == len(previa.eligible) + len(previa.excluded)


@pytest.mark.asyncio
async def test_isolamento_no_repositorio_isolado(cenario):
    """Exercita o repositório sem passar por rota nem serviço — o mesmo desenho
    do teste de carteira de R1, porque é na consulta que a regra precisa valer.
    """
    async with cenario.app.state.session_factory() as session:
        repo = AudienceRepository(session)
        outro_tenant = uuid4()

        assert (
            await repo.customers_in_scope(
                outro_tenant, owner_user_id=cenario.mundo.representative_a_id
            )
            == []
        )
        assert await repo.products_in_groups(outro_tenant, [cenario.grupo_poliester_id]) == set()
        assert await repo.existing_group_ids(outro_tenant, [cenario.grupo_poliester_id]) == set()
        assert await repo.fibers_by_codes(outro_tenant, ["PES"]) == {}
        assert await repo.active_contacts(outro_tenant, [cenario.mundo.customer_a_id]) == {}

        # E, dentro do tenant certo, a carteira do representante B não vaza
        # para o A nem na consulta mais aberta que existe.
        da_carteira_a = await repo.customers_in_scope(
            cenario.tenant_id, owner_user_id=cenario.mundo.representative_a_id
        )
        assert cenario.mundo.customer_b_id not in {c.id for c in da_carteira_a}


# ----------------------------------------------------- determinismo e entrega


@pytest.mark.asyncio
async def test_a_mesma_previa_duas_vezes_e_identica(cenario):
    criterios = {"product_group_ids": [cenario.grupo_poliester_id]}
    uma = await _resolve(cenario, criterios)
    outra = await _resolve(cenario, criterios)

    assert [m.customer.id for m in uma.eligible] == [m.customer.id for m in outra.eligible]
    assert [m.customer.id for m in uma.excluded] == [m.customer.id for m in outra.excluded]
    assert uma.normalized_criteria == outra.normalized_criteria


@pytest.mark.asyncio
async def test_previa_alimenta_o_rascunho_da_f61(cenario):
    """O encaixe entre as duas fases: a prévia vira o público congelado.

    Os não classificados **não** entram — congelar um julgamento que ninguém
    fez seria inventar o dado que falta.
    """
    previa = await _resolve(cenario, {"fiber_codes": ["PES"]})
    destinatarios = previa.to_draft_recipients()

    async with cenario.app.state.session_factory() as session:
        service = WhatsappCampaignService(
            campaigns=WhatsappCampaignRepository(session),
            audit=AuditRepository(session),
        )
        criada = await service.create_draft(
            cenario.tenant_id,
            actor_user_id=cenario.mundo.representative_a_id,
            actor_role=UserRole.REPRESENTATIVE,
            idempotency_key="da-previa-0001",
            criteria=previa.normalized_criteria,
            template={"name": "oferta_mensal", "language": "pt_BR"},
            audience_summary=previa.counts,
            recipients=destinatarios,
        )
        await session.commit()

    assert criada.created is True
    assert criada.campaign.criteria_snapshot == {"fiber_codes": ["PES"]}
    assert criada.campaign.audience_summary_snapshot["eligible"] == previa.counts["eligible"]

    async with cenario.app.state.session_factory() as session:
        _, linhas = await WhatsappCampaignService(
            campaigns=WhatsappCampaignRepository(session),
            audit=AuditRepository(session),
        ).get_campaign(
            cenario.tenant_id,
            criada.campaign.id,
            actor_user_id=cenario.mundo.representative_a_id,
            actor_role=UserRole.REPRESENTATIVE,
        )
        assert len(linhas) == len(destinatarios)
        assert cenario.indeterminado_id not in {linha.customer_id for linha in linhas}
