"""Telas de R6b: preferidos, lista resolvida, matriz de ICMS e tabela do mês."""

import re
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    PASSWORD,
    REPRESENTATIVE_A_EMAIL,
    REPRESENTATIVE_B_EMAIL,
    build_portal_world,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.catalog import CustomerPreferredProduct, Product, ProductFamily
from crm_api.models.customer import Tenant
from crm_api.models.interaction import CustomerInteraction, InteractionDirection
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.models.tax import IcmsRule

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
COMPETENCIA = date.today().replace(day=1)


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _browser(world):
    async with AsyncClient(
        transport=ASGITransport(app=world.app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client


def _token(html: str) -> str:
    achado = _CSRF.search(html)
    assert achado, "página não trouxe campo csrf_token"
    return achado.group(1)


async def _entrar(client, email: str):
    pagina = await client.get("/portal/login")
    return await client.post(
        "/portal/login",
        data={"email": email, "password": PASSWORD, "csrf_token": _token(pagina.text)},
    )


@pytest_asyncio.fixture
async def admin(world):
    async with _browser(world) as client:
        assert (await _entrar(client, ADMIN_EMAIL)).status_code == 200
        yield client


@pytest_asyncio.fixture
async def representante(world):
    async with _browser(world) as client:
        assert (await _entrar(client, REPRESENTATIVE_A_EMAIL)).status_code == 200
        yield client


async def _preparar_precificacao(world, *, com_regra: bool = True, origem: str = "SP"):
    """Origem no tenant, preço publicado na competência e regra SP→SP."""
    async with world.app.state.session_factory() as session:
        tenant = await session.get(Tenant, world.tenant_id)
        tenant.origin_state_code = origem
        session.add(
            PriceEntry(
                id=uuid4(),
                tenant_id=world.tenant_id,
                reference_month=COMPETENCIA,
                product_id=world.product_id,
                base_price=Decimal("12.0500"),
                base_tax_rate=Decimal("18.000"),
                availability=AvailabilityStatus.AVAILABLE,
                published_at=datetime.now(UTC),
            )
        )
        if com_regra:
            session.add(
                IcmsRule(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    origin_state=origem,
                    destination_state="SP",
                    tax_rate=Decimal("12.000"),
                    valid_from=date.today() - timedelta(days=1),
                )
            )
        await session.commit()


# ------------------------------------------------------ produtos preferidos


@pytest.mark.asyncio
async def test_incluir_produto_preferido_pela_ficha(world, admin):
    async with world.app.state.session_factory() as session:
        familia = ProductFamily(id=uuid4(), tenant_id=world.tenant_id, name="Liso")
        produto = Product(
            id=uuid4(),
            tenant_id=world.tenant_id,
            family_id=familia.id,
            sku="LIS-50-24",
            commercial_name="50/24 liso",
        )
        session.add_all([familia, produto])
        await session.commit()
        novo_id = produto.id

    pagina = await admin.get(f"/portal/customers/{world.customer_b_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_b_id}/preferred",
        data={
            "product_id": str(novo_id),
            "customer_alias": "o liso de sempre",
            "csrf_token": _token(pagina.text),
        },
    )

    assert resposta.status_code == 200
    assert "Produto incluído entre os preferidos." in resposta.text
    assert "o liso de sempre" in resposta.text


@pytest.mark.asyncio
async def test_incluir_duas_vezes_o_mesmo_produto_e_recusado(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/preferred",
        data={"product_id": str(world.product_id), "csrf_token": _token(pagina.text)},
    )

    assert "já está entre os preferidos" in resposta.text


@pytest.mark.asyncio
async def test_retirar_e_reincluir_preserva_o_apelido(world, admin):
    async with world.app.state.session_factory() as session:
        preferencia = await session.scalar(select(CustomerPreferredProduct))
        preferencia.customer_alias = "trama fina"
        await session.commit()
        preferencia_id = preferencia.id

    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    await admin.post(
        f"/portal/customers/{world.customer_a_id}/preferred/{preferencia_id}",
        data={"acao": "remover", "csrf_token": _token(pagina.text)},
    )
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/preferred",
        data={"product_id": str(world.product_id), "csrf_token": _token(pagina.text)},
    )

    assert resposta.status_code == 200
    async with world.app.state.session_factory() as session:
        quantas = list(await session.scalars(select(CustomerPreferredProduct)))
    # Reincluir reativa a linha existente; a chave (cliente, produto) é única.
    assert len(quantas) == 1
    assert quantas[0].active is True
    assert quantas[0].customer_alias == "trama fina"


@pytest.mark.asyncio
async def test_representante_nao_altera_preferidos_de_carteira_alheia(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_B_EMAIL)
        pagina = await client.get(f"/portal/customers/{world.customer_b_id}")
        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/preferred",
            data={"product_id": str(world.product_id), "csrf_token": _token(pagina.text)},
        )

    assert "Registro não encontrado." in resposta.text
    async with world.app.state.session_factory() as session:
        preferencias = list(await session.scalars(select(CustomerPreferredProduct)))
    assert len(preferencias) == 1
    assert preferencias[0].customer_id == world.customer_a_id


# ---------------------------------------------------------- lista de preço


@pytest.mark.asyncio
async def test_lista_de_preco_mostra_conversao_e_trilha(world, representante):
    await _preparar_precificacao(world)

    resposta = await representante.get(
        f"/portal/customers/{world.customer_a_id}/price-list"
    )

    assert resposta.status_code == 200
    # 12,05 x 0,82 / 0,88
    assert "11.2284" in resposta.text
    assert "como este preço foi calculado" in resposta.text


@pytest.mark.asyncio
async def test_lista_sem_regra_de_icms_explica_o_que_falta(world, representante):
    await _preparar_precificacao(world, com_regra=False)

    resposta = await representante.get(
        f"/portal/customers/{world.customer_a_id}/price-list"
    )

    # A tela continua de pé e diz o que cadastrar, em vez de estimar.
    assert resposta.status_code == 200
    assert "Não há regra de ICMS" in resposta.text
    assert "11.2284" not in resposta.text


@pytest.mark.asyncio
async def test_lista_sem_uf_de_origem_configurada(world, representante):
    await _preparar_precificacao(world, origem="SP")
    async with world.app.state.session_factory() as session:
        tenant = await session.get(Tenant, world.tenant_id)
        tenant.origin_state_code = None
        await session.commit()

    resposta = await representante.get(
        f"/portal/customers/{world.customer_a_id}/price-list"
    )

    assert "UF de origem" in resposta.text


@pytest.mark.asyncio
async def test_exportacao_csv_sai_com_bom_e_ponto_e_virgula(world, representante):
    await _preparar_precificacao(world)

    resposta = await representante.get(
        f"/portal/customers/{world.customer_a_id}/price-list?formato=csv"
    )

    assert resposta.status_code == 200
    assert "text/csv" in resposta.headers["content-type"]
    assert "attachment" in resposta.headers["content-disposition"]
    texto = resposta.text
    assert texto.startswith("﻿")
    assert "sku;familia;produto" in texto
    # Decimal com vírgula: é o que a planilha em pt-BR lê como número.
    assert "11,2284" in texto


@pytest.mark.asyncio
async def test_lista_de_cliente_fora_da_carteira_volta_para_a_lista(world):
    await _preparar_precificacao(world)
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_B_EMAIL)
        resposta = await client.get(
            f"/portal/customers/{world.customer_a_id}/price-list"
        )

    assert "Registro não encontrado." in resposta.text
    assert "11.2284" not in resposta.text


# ---------------------------------------------------------- matriz de ICMS


@pytest.mark.asyncio
async def test_admin_cadastra_regra_pela_tela(world, admin):
    pagina = await admin.get("/portal/icms-rules")
    resposta = await admin.post(
        "/portal/icms-rules",
        data={
            "origin_state": "sp",
            "destination_state": "rs",
            "tax_rate": "12,000",
            "valid_from": date.today().isoformat(),
            "priority": "100",
            "csrf_token": _token(pagina.text),
        },
    )

    assert "Regra de ICMS cadastrada." in resposta.text
    async with world.app.state.session_factory() as session:
        regra = await session.scalar(select(IcmsRule))
    assert (regra.origin_state, regra.destination_state) == ("SP", "RS")
    assert regra.tax_rate == Decimal("12.000")


@pytest.mark.asyncio
async def test_uf_invalida_na_matriz_e_recusada(world, admin):
    pagina = await admin.get("/portal/icms-rules")
    resposta = await admin.post(
        "/portal/icms-rules",
        data={
            "origin_state": "XX",
            "destination_state": "RS",
            "tax_rate": "12",
            "valid_from": date.today().isoformat(),
            "csrf_token": _token(pagina.text),
        },
    )

    assert "UF inválida" in resposta.text
    async with world.app.state.session_factory() as session:
        assert await session.scalar(select(IcmsRule)) is None


@pytest.mark.asyncio
async def test_representante_nao_alcanca_a_matriz(world, representante):
    resposta = await representante.get("/portal/icms-rules")

    assert "Seu papel não permite essa operação." in resposta.text
    assert str(resposta.url).endswith("/portal/customers?m=sem-permissao")


# --------------------------------------------------------- tabela do mês


async def _lote(world, *, nome: str = "Tabela do mês") -> object:
    async with world.app.state.session_factory() as session:
        lote = PriceList(
            id=uuid4(),
            tenant_id=world.tenant_id,
            name=nome,
            reference_month=COMPETENCIA,
            valid_from=datetime.now(UTC),
            status=PriceListStatus.DRAFT,
        )
        session.add(lote)
        session.add(
            PriceListItem(
                id=uuid4(),
                tenant_id=world.tenant_id,
                price_list_id=lote.id,
                product_id=world.product_id,
                base_price=Decimal("12.0500"),
                availability=AvailabilityStatus.AVAILABLE,
            )
        )
        await session.commit()
        return lote.id


@pytest.mark.asyncio
async def test_publicar_lote_pela_tela_cria_a_competencia(world, admin):
    lote_id = await _lote(world)

    pagina = await admin.get("/portal/prices")
    resposta = await admin.post(
        "/portal/prices/publish",
        data={"batch_id": str(lote_id), "csrf_token": _token(pagina.text)},
    )

    assert "Tabela publicada na competência." in resposta.text
    async with world.app.state.session_factory() as session:
        entrada = await session.scalar(select(PriceEntry))
    assert entrada.base_price == Decimal("12.0500")
    assert entrada.source_batch_id == lote_id


@pytest.mark.asyncio
async def test_republicar_o_mesmo_lote_nao_gera_revisao_vazia(world, admin):
    lote_id = await _lote(world)
    pagina = await admin.get("/portal/prices")
    dados = {"batch_id": str(lote_id), "csrf_token": _token(pagina.text)}

    await admin.post("/portal/prices/publish", data=dados)
    resposta = await admin.post("/portal/prices/publish", data=dados)

    # A primeira publicação aparece nas revisões; a segunda não acrescenta nada.
    assert resposta.text.count("primeira publicação") == 1


@pytest.mark.asyncio
async def test_lote_cancelado_nao_e_publicavel(world, admin):
    lote_id = await _lote(world)
    async with world.app.state.session_factory() as session:
        lote = await session.get(PriceList, lote_id)
        lote.status = PriceListStatus.CANCELLED
        await session.commit()

    pagina = await admin.get("/portal/prices")
    resposta = await admin.post(
        "/portal/prices/publish",
        data={"batch_id": str(lote_id), "csrf_token": _token(pagina.text)},
    )

    assert "cancelado ou expirado" in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_alcanca_a_tela_de_tabelas(world, representante):
    resposta = await representante.get("/portal/prices")

    assert str(resposta.url).endswith("/portal/customers?m=sem-permissao")


@pytest.mark.asyncio
async def test_publicacao_sem_csrf_nao_toca_o_banco(world, admin):
    lote_id = await _lote(world)

    resposta = await admin.post(
        "/portal/prices/publish",
        data={"batch_id": str(lote_id), "csrf_token": "forjado"},
    )

    assert "O formulário expirou." in resposta.text
    async with world.app.state.session_factory() as session:
        assert await session.scalar(select(PriceEntry)) is None


# ---------------------------------------------------------------- timeline


@pytest.mark.asyncio
async def test_ficha_mostra_o_historico_de_interacoes(world, representante):
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerInteraction(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_a_id,
                channel="WHATSAPP",
                direction=InteractionDirection.INBOUND,
                source="whatsapp-gateway",
                external_ref="wamid.1",
                occurred_at=datetime.now(UTC),
                summary="Preciso de 200kg do cru",
            )
        )
        await session.commit()

    resposta = await representante.get(f"/portal/customers/{world.customer_a_id}")

    assert "Preciso de 200kg do cru" in resposta.text
    assert "recebida" in resposta.text


@pytest.mark.asyncio
async def test_carteira_marca_quem_nunca_falou(world, representante):
    resposta = await representante.get("/portal/customers")

    assert "Última interação" in resposta.text
    assert "nunca" in resposta.text


# --------------------------------------------------------------- segurança


@pytest.mark.asyncio
async def test_toda_resposta_traz_cabecalhos_contra_clickjacking(world):
    async with _browser(world) as client:
        resposta = await client.get("/portal/login")

    assert resposta.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in resposta.headers["content-security-policy"]
    assert resposta.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_documentacao_interativa_fica_fora_por_padrao(world):
    async with _browser(world) as client:
        docs = await client.get("/docs")
        esquema = await client.get("/openapi.json")

    assert docs.status_code == 404
    assert esquema.status_code == 404


@pytest.mark.asyncio
async def test_documentacao_pode_ser_ligada_explicitamente():
    mundo = await build_portal_world(expose_api_docs=True)
    try:
        async with _browser(mundo) as client:
            assert (await client.get("/openapi.json")).status_code == 200
    finally:
        await mundo.app.state.engine.dispose()
