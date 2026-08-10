"""Cadastro de artigo pela ficha do cliente.

O que estas provas guardam é a fronteira: o artigo entra no catálogo na hora, o
preço entra como rascunho, e nada chega ao cliente antes de o lote ser
publicado.
"""

import re
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    PASSWORD,
    REPRESENTATIVE_A_EMAIL,
    build_portal_world,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.core.passwords import hash_password
from crm_api.models.catalog import CustomerPreferredProduct, Product, ProductFamily
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.models.user import User, UserRole
from crm_api.services.catalog import BATCH_NAME

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
COMPETENCIA = date.today().replace(day=1)
GERENTE_EMAIL = "gerente@teste.com.br"


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
async def gerente(world):
    """MANAGER não existe no cenário compartilhado; criado só aqui."""
    async with world.app.state.session_factory() as session:
        session.add(
            User(
                id=uuid4(),
                tenant_id=world.tenant_id,
                full_name="Gerente Exemplo",
                email=GERENTE_EMAIL,
                password_hash=hash_password(PASSWORD),
                role=UserRole.MANAGER,
            )
        )
        await session.commit()

    async with _browser(world) as client:
        assert (await _entrar(client, GERENTE_EMAIL)).status_code == 200
        yield client


async def _cadastrar(client, customer_id, **campos):
    pagina = await client.get(f"/portal/customers/{customer_id}")
    dados = {
        "sku": "RBF-200",
        "commercial_name": "Rubberflex 200",
        "family_name": "Elásticos",
        "availability": "AVAILABLE",
        "base_price": "18,50",
        "csrf_token": _token(pagina.text),
    }
    dados.update(campos)
    return await client.post(f"/portal/customers/{customer_id}/articles", data=dados)


async def _tudo(world, modelo):
    async with world.app.state.session_factory() as session:
        return list(await session.scalars(select(modelo)))


# ------------------------------------------------------------ caminho feliz


@pytest.mark.asyncio
async def test_artigo_novo_entra_no_catalogo_e_vira_preferido(world, admin):
    resposta = await _cadastrar(admin, world.customer_b_id, customer_alias="o elástico")

    assert resposta.status_code == 200
    assert "Artigo cadastrado e incluído entre os preferidos." in resposta.text

    produtos = {produto.sku: produto for produto in await _tudo(world, Product)}
    assert "RBF-200" in produtos
    novo = produtos["RBF-200"]
    assert novo.commercial_name == "Rubberflex 200"
    assert novo.unit == "KG"

    preferencias = [
        preferencia
        for preferencia in await _tudo(world, CustomerPreferredProduct)
        if preferencia.customer_id == world.customer_b_id
    ]
    assert len(preferencias) == 1
    assert preferencias[0].product_id == novo.id
    assert preferencias[0].customer_alias == "o elástico"


@pytest.mark.asyncio
async def test_o_preco_entra_como_rascunho_na_competencia_corrente(world, admin):
    await _cadastrar(admin, world.customer_b_id)

    lotes = await _tudo(world, PriceList)
    assert len(lotes) == 1
    assert lotes[0].name == BATCH_NAME
    assert lotes[0].reference_month == COMPETENCIA
    assert lotes[0].status is PriceListStatus.DRAFT

    itens = await _tudo(world, PriceListItem)
    assert len(itens) == 1
    assert itens[0].price_list_id == lotes[0].id
    assert itens[0].base_price == Decimal("18.50")
    assert itens[0].availability is AvailabilityStatus.AVAILABLE

    # O que o preço ainda não é: vigente. Nada em `price_entries` significa
    # nada servido ao Gateway nem à lista do representante.
    assert await _tudo(world, PriceEntry) == []


@pytest.mark.asyncio
async def test_publicar_o_lote_faz_o_preco_valer(world, admin):
    await _cadastrar(admin, world.customer_b_id)
    lote = (await _tudo(world, PriceList))[0]

    pagina = await admin.get("/portal/prices")
    resposta = await admin.post(
        "/portal/prices/publish",
        data={"batch_id": str(lote.id), "csrf_token": _token(pagina.text)},
    )
    assert resposta.status_code == 200

    entradas = await _tudo(world, PriceEntry)
    assert len(entradas) == 1
    assert entradas[0].reference_month == COMPETENCIA
    assert entradas[0].base_price == Decimal("18.50")
    assert entradas[0].source_batch_id == lote.id


@pytest.mark.asyncio
async def test_segundo_artigo_do_mes_reaproveita_o_mesmo_lote(world, admin):
    await _cadastrar(admin, world.customer_b_id)
    await _cadastrar(
        admin,
        world.customer_b_id,
        sku="RBF-400",
        commercial_name="Rubberflex 400",
        base_price="21,90",
    )

    lotes = await _tudo(world, PriceList)
    assert len(lotes) == 1, "cada artigo virou um lote; publicar viraria ruído"
    itens = await _tudo(world, PriceListItem)
    assert len(itens) == 2
    assert {item.display_order for item in itens} == {0, 1}


@pytest.mark.asyncio
async def test_artigo_depois_da_publicacao_abre_lote_seguinte(world, admin):
    """Lote publicado não recebe item novo: ele passaria a mentir sobre si."""
    await _cadastrar(admin, world.customer_b_id)
    primeiro = (await _tudo(world, PriceList))[0]

    pagina = await admin.get("/portal/prices")
    await admin.post(
        "/portal/prices/publish",
        data={"batch_id": str(primeiro.id), "csrf_token": _token(pagina.text)},
    )

    await _cadastrar(
        admin,
        world.customer_b_id,
        sku="RBF-400",
        commercial_name="Rubberflex 400",
        base_price="21,90",
    )

    lotes = {lote.name: lote for lote in await _tudo(world, PriceList)}
    assert set(lotes) == {BATCH_NAME, f"{BATCH_NAME} (2)"}
    assert lotes[BATCH_NAME].status is PriceListStatus.PUBLISHED
    assert lotes[f"{BATCH_NAME} (2)"].status is PriceListStatus.DRAFT


# ------------------------------------------------------------------ família


@pytest.mark.asyncio
async def test_familia_nova_e_criada_uma_vez_so(world, admin):
    await _cadastrar(admin, world.customer_b_id)
    await _cadastrar(
        admin,
        world.customer_b_id,
        sku="RBF-400",
        commercial_name="Rubberflex 400",
        family_name="Elásticos",
    )

    elasticos = [f for f in await _tudo(world, ProductFamily) if f.name == "Elásticos"]
    assert len(elasticos) == 1, "o mesmo nome criou duas famílias"


@pytest.mark.asyncio
async def test_familia_existente_e_escolhida_pelo_id(world, admin):
    async with world.app.state.session_factory() as session:
        familia = await session.scalar(select(ProductFamily))
        familia_id, nome = familia.id, familia.name

    await _cadastrar(admin, world.customer_b_id, family_id=str(familia_id), family_name="")

    produto = next(p for p in await _tudo(world, Product) if p.sku == "RBF-200")
    assert produto.family_id == familia_id
    assert len([f for f in await _tudo(world, ProductFamily) if f.name == nome]) == 1


@pytest.mark.asyncio
async def test_sem_familia_nenhuma_o_cadastro_e_recusado(world, admin):
    resposta = await _cadastrar(admin, world.customer_b_id, family_name="", family_id="")

    assert "Escolha uma família existente ou informe o nome de uma nova." in resposta.text
    assert not [p for p in await _tudo(world, Product) if p.sku == "RBF-200"]


# ------------------------------------------------------------------ recusas


@pytest.mark.asyncio
async def test_sku_duplicado_nao_grava_nada(world, admin):
    async with world.app.state.session_factory() as session:
        produto = await session.scalar(select(Product))
        sku_existente = produto.sku

    resposta = await _cadastrar(admin, world.customer_b_id, sku=sku_existente)

    assert "Já existe um artigo com esse SKU" in resposta.text
    assert len(await _tudo(world, Product)) == 1
    assert await _tudo(world, PriceList) == []
    assert not [
        p for p in await _tudo(world, CustomerPreferredProduct)
        if p.customer_id == world.customer_b_id
    ]


@pytest.mark.asyncio
async def test_disponivel_sem_preco_e_recusado(world, admin):
    resposta = await _cadastrar(admin, world.customer_b_id, base_price="")

    assert "Informe o preço-base" in resposta.text
    assert not [p for p in await _tudo(world, Product) if p.sku == "RBF-200"]


@pytest.mark.asyncio
async def test_sob_consulta_dispensa_o_preco(world, admin):
    resposta = await _cadastrar(
        admin, world.customer_b_id, base_price="", availability="CONSULT"
    )

    assert "Artigo cadastrado" in resposta.text
    item = (await _tudo(world, PriceListItem))[0]
    assert item.availability is AvailabilityStatus.CONSULT
    assert item.base_price == Decimal("0")


@pytest.mark.asyncio
async def test_preco_em_formato_brasileiro_com_milhar(world, admin):
    await _cadastrar(admin, world.customer_b_id, base_price="1.234,56")

    assert (await _tudo(world, PriceListItem))[0].base_price == Decimal("1234.56")


@pytest.mark.asyncio
async def test_preco_ilegivel_e_recusado(world, admin):
    resposta = await _cadastrar(admin, world.customer_b_id, base_price="doze reais")

    assert "Preço inválido" in resposta.text
    assert not [p for p in await _tudo(world, Product) if p.sku == "RBF-200"]


@pytest.mark.asyncio
async def test_cadastro_sem_csrf_nao_toca_o_banco(world, admin):
    resposta = await admin.post(
        f"/portal/customers/{world.customer_b_id}/articles",
        data={
            "sku": "RBF-200",
            "commercial_name": "Rubberflex 200",
            "family_name": "Elásticos",
            "availability": "AVAILABLE",
            "base_price": "18,50",
            "csrf_token": "forjado",
        },
    )

    assert "O formulário expirou" in resposta.text
    assert len(await _tudo(world, Product)) == 1


# ------------------------------------------------------------------- papéis


@pytest.mark.asyncio
async def test_gerente_cadastra_artigo(world, gerente):
    resposta = await _cadastrar(gerente, world.customer_b_id)

    assert "Artigo cadastrado" in resposta.text
    assert len(await _tudo(world, Product)) == 2


@pytest.mark.asyncio
async def test_representante_nao_cadastra_artigo(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await _cadastrar(client, world.customer_a_id)

    assert "Seu papel não permite essa operação." in resposta.text
    assert len(await _tudo(world, Product)) == 1
    assert await _tudo(world, PriceList) == []


@pytest.mark.asyncio
async def test_representante_nao_recebe_o_modal_na_ficha(world):
    # O único produto do cenário já é preferido do cliente A, e o formulário de
    # inclusão só aparece quando sobra algo no catálogo para incluir.
    async with world.app.state.session_factory() as session:
        familia = await session.scalar(select(ProductFamily))
        session.add(
            Product(
                id=uuid4(),
                tenant_id=world.tenant_id,
                family_id=familia.id,
                sku="LIS-50-24",
                commercial_name="50/24 liso",
            )
        )
        await session.commit()

    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get(f"/portal/customers/{world.customer_a_id}")

    assert 'id="modal-artigo"' not in pagina.text
    assert "Cadastrar artigo" not in pagina.text
    # O combobox continua: buscar no catálogo não é privilégio.
    assert "data-combobox" in pagina.text


# --------------------------------------------------------------------- tela


@pytest.mark.asyncio
async def test_ficha_avisa_que_o_preferido_esta_sem_preco_no_mes(world, admin):
    """Sem o aviso, o preferido some da lista e ninguém descobre por quê."""
    async with world.app.state.session_factory() as session:
        session.add(
            PriceEntry(
                id=uuid4(),
                tenant_id=world.tenant_id,
                reference_month=COMPETENCIA,
                product_id=world.product_id,
                base_price=Decimal("10.00"),
                availability=AvailabilityStatus.AVAILABLE,
            )
        )
        await session.commit()

    # O produto do cenário tem preço; o recém-cadastrado, não.
    await _cadastrar(admin, world.customer_a_id)
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")

    assert pagina.text.count("sem preço no mês") == 1
    linha_do_novo = pagina.text.split("RBF-200")[1][:400]
    assert "sem preço no mês" in linha_do_novo


@pytest.mark.asyncio
async def test_combobox_mantem_o_select_nativo_no_formulario(world, admin):
    """A busca é enfeite; o campo que o servidor lê continua sendo o select."""
    pagina = await admin.get(f"/portal/customers/{world.customer_b_id}")

    assert "data-combobox" in pagina.text
    assert 'name="product_id"' in pagina.text
    assert '<script src="/portal/static/portal.js" defer></script>' in pagina.text
    assert '/portal/static/portal-nojs.css' in pagina.text
