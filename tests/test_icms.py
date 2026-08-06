from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    REPRESENTATIVE_A_EMAIL,
    build_portal_world,
    login,
    portal_settings,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.catalog import CustomerPreferredProduct
from crm_api.models.customer import Customer, CustomerLocation, Tenant
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.models.tax import IcmsRule
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.icms import (
    AmbiguousIcmsRule,
    ConversionMode,
    IcmsResolution,
    IcmsResolver,
    IcmsRuleNotFound,
    OriginNotConfigured,
    convert_price,
)
from crm_api.services.price_publication import PricePublicationService

COMPETENCIA = date.today().replace(day=1)
ONTEM = date.today() - timedelta(days=1)


# ------------------------------------------------------------- conversão


def _resolucao(taxa: str) -> IcmsResolution:
    return IcmsResolution(
        rule_id=uuid4(),
        tax_rate=Decimal(taxa),
        origin_state="SP",
        destination_state="RS",
        specificity=1,
    )


def test_conversao_por_dentro_remove_a_aliquota_de_origem():
    """12,05 com 18% embutido, vendido para UF de 12%."""
    convertido = convert_price(
        base_price=Decimal("12.0500"),
        base_tax_rate=Decimal("18.000"),
        resolution=_resolucao("12.000"),
        mode=ConversionMode.INSIDE,
    )

    # 12,05 x 0,82 = 9,881 ; 9,881 / 0,88 = 11,2284
    assert convertido.final_price == Decimal("11.2284")
    assert convertido.trace["net_price"] == "9.8810"
    assert convertido.trace["mode"] == "INSIDE"


def test_mesma_aliquota_de_origem_e_destino_nao_muda_o_preco():
    convertido = convert_price(
        base_price=Decimal("12.0500"),
        base_tax_rate=Decimal("18.000"),
        resolution=_resolucao("18.000"),
        mode=ConversionMode.INSIDE,
    )

    assert convertido.final_price == Decimal("12.0500")


def test_preco_base_sem_imposto_embutido_apenas_recebe_o_destino():
    convertido = convert_price(
        base_price=Decimal("10.0000"),
        base_tax_rate=None,
        resolution=_resolucao("12.000"),
        mode=ConversionMode.INSIDE,
    )

    # 10 / 0,88 = 11,363636...
    assert convertido.final_price == Decimal("11.3636")


def test_modo_por_fora_produz_resultado_diferente():
    """Q2 em aberto: os dois modos existem e não são equivalentes."""
    dentro = convert_price(
        base_price=Decimal("12.0500"),
        base_tax_rate=Decimal("18.000"),
        resolution=_resolucao("12.000"),
        mode=ConversionMode.INSIDE,
    )
    fora = convert_price(
        base_price=Decimal("12.0500"),
        base_tax_rate=Decimal("18.000"),
        resolution=_resolucao("12.000"),
        mode=ConversionMode.OUTSIDE,
    )

    # 12,05 / 1,18 = 10,2118644 ; x 1,12 = 11,4372881
    assert fora.final_price == Decimal("11.4373")
    assert dentro.final_price != fora.final_price


def test_valores_monetarios_nunca_usam_ponto_flutuante():
    convertido = convert_price(
        base_price=Decimal("12.0500"),
        base_tax_rate=Decimal("18.000"),
        resolution=_resolucao("12.000"),
        mode=ConversionMode.INSIDE,
    )

    assert isinstance(convertido.final_price, Decimal)


# -------------------------------------------------------------- resolução


class _RepositorioFalso:
    def __init__(self, regras):
        self._regras = regras

    async def candidates(self, **_):
        return self._regras


def _regra(**kwargs) -> IcmsRule:
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "origin_state": "SP",
        "destination_state": "RS",
        "tax_rate": Decimal("12.000"),
        "valid_from": ONTEM,
        "priority": 100,
        "active": True,
    }
    base.update(kwargs)
    return IcmsRule(**base)


@pytest.mark.asyncio
async def test_regra_de_cliente_prevalece_sobre_a_de_produto():
    cliente, produto = uuid4(), uuid4()
    generica = _regra(tax_rate=Decimal("12.000"))
    por_produto = _regra(product_id=produto, tax_rate=Decimal("7.000"))
    por_cliente = _regra(customer_id=cliente, tax_rate=Decimal("4.000"))

    resolvida = await IcmsResolver(
        _RepositorioFalso([generica, por_produto, por_cliente])
    ).resolve(
        tenant_id=uuid4(),
        origin_state="SP",
        destination_state="RS",
        product_id=produto,
        customer_id=cliente,
        at=date.today(),
    )

    assert resolvida.tax_rate == Decimal("4.000")
    assert resolvida.specificity == 4


@pytest.mark.asyncio
async def test_ausencia_de_regra_e_erro_nao_aliquota_zero():
    with pytest.raises(IcmsRuleNotFound):
        await IcmsResolver(_RepositorioFalso([])).resolve(
            tenant_id=uuid4(),
            origin_state="SP",
            destination_state="RS",
            at=date.today(),
        )


@pytest.mark.asyncio
async def test_empate_no_mesmo_nivel_falha_em_vez_de_escolher():
    empatadas = [
        _regra(tax_rate=Decimal("12.000")),
        _regra(tax_rate=Decimal("7.000")),
    ]

    with pytest.raises(AmbiguousIcmsRule):
        await IcmsResolver(_RepositorioFalso(empatadas)).resolve(
            tenant_id=uuid4(),
            origin_state="SP",
            destination_state="RS",
            at=date.today(),
        )


@pytest.mark.asyncio
async def test_prioridade_e_depois_vigencia_desempatam():
    antiga = _regra(tax_rate=Decimal("12.000"), priority=200, valid_from=ONTEM - timedelta(days=30))
    recente = _regra(tax_rate=Decimal("7.000"), priority=200, valid_from=ONTEM)
    fraca = _regra(tax_rate=Decimal("25.000"), priority=10)

    resolvida = await IcmsResolver(_RepositorioFalso([antiga, recente, fraca])).resolve(
        tenant_id=uuid4(),
        origin_state="SP",
        destination_state="RS",
        at=date.today(),
    )

    assert resolvida.tax_rate == Decimal("7.000")


@pytest.mark.asyncio
async def test_tenant_sem_uf_de_origem_falha_com_mensagem_clara():
    with pytest.raises(OriginNotConfigured):
        await IcmsResolver(_RepositorioFalso([_regra()])).resolve(
            tenant_id=uuid4(),
            origin_state=None,
            destination_state="RS",
            at=date.today(),
        )


# ------------------------------------------------------- lista resolvida


@pytest_asyncio.fixture
async def mundo():
    construido = await build_portal_world()
    app = construido.app

    async with app.state.session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == construido.tenant_id))
        tenant.origin_state_code = "SP"

        lote = PriceList(
            id=uuid4(),
            tenant_id=construido.tenant_id,
            name="Tabela do mês",
            reference_month=COMPETENCIA,
            valid_from=datetime.now(UTC) - timedelta(days=1),
            base_tax_rate=Decimal("18.000"),
            status=PriceListStatus.DRAFT,
        )
        session.add(lote)
        session.add(
            PriceListItem(
                id=uuid4(),
                tenant_id=construido.tenant_id,
                price_list_id=lote.id,
                product_id=construido.product_id,
                base_price=Decimal("12.0500"),
                availability=AvailabilityStatus.AVAILABLE,
            )
        )
        await session.commit()

        await PricePublicationService(
            session=session,
            entries=PriceEntryRepository(session),
            audit=AuditRepository(session),
        ).publish_batch(tenant_id=construido.tenant_id, batch_id=lote.id)

        session.add(
            CustomerPreferredProduct(
                id=uuid4(),
                tenant_id=construido.tenant_id,
                customer_id=construido.customer_b_id,
                product_id=construido.product_id,
                customer_alias="Fio cru especial",
            )
        )
        await session.commit()

    yield construido
    await app.state.engine.dispose()


@asynccontextmanager
async def _autenticado(mundo, email: str = ADMIN_EMAIL):
    async with AsyncClient(
        transport=ASGITransport(app=mundo.app), base_url="http://test"
    ) as client:
        await login(client, email=email)
        yield client


async def _regra_geral(mundo, destino: str, taxa: str):
    async with mundo.app.state.session_factory() as session:
        IcmsRuleRepository(session).add(
            IcmsRule(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                origin_state="SP",
                destination_state=destino,
                tax_rate=Decimal(taxa),
                valid_from=ONTEM,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_dois_clientes_em_ufs_diferentes_recebem_precos_diferentes(mundo):
    await _regra_geral(mundo, "SP", "18.000")
    await _regra_geral(mundo, "RS", "12.000")

    async with _autenticado(mundo) as client:
        # Alfa recebe em SP; Beta recebe em RS.
        alfa = await client.get(f"/admin/customers/{mundo.customer_a_id}/price-list")
        beta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    assert alfa.status_code == beta.status_code == 200
    preco_sp = alfa.json()["items"][0]["final_price"]
    preco_rs = beta.json()["items"][0]["final_price"]

    assert preco_sp == "12.0500"
    assert preco_rs == "11.2284"
    assert alfa.json()["destination_state"] == "SP"
    assert beta.json()["destination_state"] == "RS"


@pytest.mark.asyncio
async def test_a_lista_usa_o_apelido_do_cliente(mundo):
    await _regra_geral(mundo, "RS", "12.000")

    async with _autenticado(mundo) as client:
        resposta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    assert resposta.json()["items"][0]["display_name"] == "Fio cru especial"


@pytest.mark.asyncio
async def test_cada_item_carrega_o_rastro_do_calculo(mundo):
    await _regra_geral(mundo, "RS", "12.000")

    async with _autenticado(mundo) as client:
        resposta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    trace = resposta.json()["items"][0]["trace"]
    assert trace["origin_state"] == "SP"
    assert trace["destination_state"] == "RS"
    assert trace["base_tax_rate"] == "18.000"
    assert trace["destination_tax_rate"] == "12.000"
    assert trace["final_price"] == "11.2284"
    assert trace["rule_id"]


@pytest.mark.asyncio
async def test_matriz_ausente_interrompe_a_lista_inteira(mundo):
    """Melhor nenhuma lista do que uma tabela silenciosamente incompleta."""
    async with _autenticado(mundo) as client:
        resposta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    assert resposta.status_code == 409
    assert "nenhuma regra de ICMS" in resposta.json()["detail"]


@pytest.mark.asyncio
async def test_tenant_sem_origem_nao_estima_um_preco(mundo):
    await _regra_geral(mundo, "RS", "12.000")
    async with mundo.app.state.session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == mundo.tenant_id))
        tenant.origin_state_code = None
        await session.commit()

    async with _autenticado(mundo) as client:
        resposta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    assert resposta.status_code == 422
    assert "UF de origem" in resposta.json()["detail"]


@pytest.mark.asyncio
async def test_cliente_fora_da_carteira_nao_tem_lista(mundo):
    await _regra_geral(mundo, "RS", "12.000")
    async with _autenticado(mundo, REPRESENTATIVE_A_EMAIL) as client:
        resposta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_localidade_define_a_uf_e_nao_o_cadastro_do_cliente(mundo):
    """Beta é cadastrado em RS mas recebe numa filial em SP."""
    await _regra_geral(mundo, "SP", "18.000")
    await _regra_geral(mundo, "RS", "12.000")

    async with mundo.app.state.session_factory() as session:
        atual = await session.scalar(
            select(CustomerLocation).where(
                CustomerLocation.customer_id == mundo.customer_b_id
            )
        )
        atual.is_default = False
        session.add(
            CustomerLocation(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                customer_id=mundo.customer_b_id,
                label="Filial Campinas",
                state_code="SP",
                is_default=True,
            )
        )
        await session.commit()

    async with _autenticado(mundo) as client:
        resposta = await client.get(f"/admin/customers/{mundo.customer_b_id}/price-list")

    corpo = resposta.json()
    assert corpo["destination_state"] == "SP"
    assert corpo["location_label"] == "Filial Campinas"
    assert corpo["items"][0]["final_price"] == "12.0500"

    async with mundo.app.state.session_factory() as session:
        cliente = await session.scalar(
            select(Customer).where(Customer.id == mundo.customer_b_id)
        )
    assert cliente.state_code == "RS"


@pytest.mark.asyncio
async def test_admin_cadastra_regra_pela_api(mundo):
    async with _autenticado(mundo) as client:
        criada = await client.post(
            "/admin/icms-rules",
            json={
                "origin_state": "sp",
                "destination_state": "mg",
                "tax_rate": "12.000",
                "valid_from": ONTEM.isoformat(),
            },
        )
        listadas = await client.get("/admin/icms-rules")

    assert criada.status_code == 201
    assert criada.json()["origin_state"] == "SP"
    assert criada.json()["destination_state"] == "MG"
    assert len(listadas.json()) == 1


@pytest.mark.asyncio
async def test_regra_com_produto_e_familia_juntos_e_recusada(mundo):
    async with _autenticado(mundo) as client:
        resposta = await client.post(
            "/admin/icms-rules",
            json={
                "origin_state": "SP",
                "destination_state": "MG",
                "tax_rate": "12.000",
                "valid_from": ONTEM.isoformat(),
                "product_id": str(uuid4()),
                "family_id": str(uuid4()),
            },
        )

    assert resposta.status_code == 422
    assert "mutually exclusive" in resposta.json()["detail"]


@pytest.mark.asyncio
async def test_representante_nao_administra_a_matriz(mundo):
    async with _autenticado(mundo, REPRESENTATIVE_A_EMAIL) as client:
        resposta = await client.get("/admin/icms-rules")

    assert resposta.status_code == 403


@pytest.mark.asyncio
async def test_modo_de_conversao_e_configuravel(mundo):
    """Q2 pendente: trocar a fórmula é configuração, não migração."""
    assert portal_settings().icms_conversion_mode == "INSIDE"
    assert portal_settings(icms_conversion_mode="OUTSIDE").icms_conversion_mode == "OUTSIDE"
