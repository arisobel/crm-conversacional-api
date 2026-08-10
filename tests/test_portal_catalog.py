"""Tela de produtos: CRUD do catálogo, separado da atribuição de preço.

A fronteira que estas provas guardam é a mesma do ADR-020, vista do outro lado:
o catálogo diz o que o artigo **é**; a competência diz quanto ele **custa**.
Editar um não pode mexer no outro.
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

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
    PriceListStatus,
)

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


async def _familia_id(world) -> str:
    async with world.app.state.session_factory() as session:
        familia = await session.scalar(select(ProductFamily))
        return str(familia.id)


async def _tudo(world, modelo):
    async with world.app.state.session_factory() as session:
        return list(await session.scalars(select(modelo)))


async def _publicar_preco(world, product_id, *, preco="10.00"):
    async with world.app.state.session_factory() as session:
        session.add(
            PriceEntry(
                id=uuid4(),
                tenant_id=world.tenant_id,
                reference_month=COMPETENCIA,
                product_id=product_id,
                base_price=Decimal(preco),
                availability=AvailabilityStatus.AVAILABLE,
            )
        )
        await session.commit()


async def _criar(client, world, **campos):
    pagina = await client.get("/portal/products")
    dados = {
        "sku": "RBF-200",
        "commercial_name": "Rubberflex 200",
        "family_id": await _familia_id(world),
        "csrf_token": _token(pagina.text),
    }
    dados.update(campos)
    return await client.post("/portal/products", data=dados)


# --------------------------------------------------------------- a listagem


@pytest.mark.asyncio
async def test_lista_mostra_o_artigo_com_familia_e_preco_do_mes(world, admin):
    await _publicar_preco(world, world.product_id, preco="12.34")

    pagina = await admin.get("/portal/products")

    assert pagina.status_code == 200
    assert "TEX-75-36-CRU" in pagina.text
    assert "Texturizado" in pagina.text
    assert "12.34" in pagina.text


@pytest.mark.asyncio
async def test_artigo_sem_preco_na_competencia_aparece_marcado(world, admin):
    await _publicar_preco(world, world.product_id)
    await _criar(admin, world)

    pagina = await admin.get("/portal/products")

    assert "RBF-200" in pagina.text
    assert pagina.text.count("sem preço") >= 1


@pytest.mark.asyncio
async def test_filtro_de_busca_recorta_por_sku_nome_e_especificacao(world, admin):
    await _criar(admin, world, specification="fio 200 den")

    achou = await admin.get("/portal/products?busca=rubber")
    por_espec = await admin.get("/portal/products?busca=200 den")
    nao_achou = await admin.get("/portal/products?busca=inexistente")

    assert "RBF-200" in achou.text and "TEX-75-36-CRU" not in achou.text
    assert "RBF-200" in por_espec.text
    assert "Nenhum artigo com esses filtros." in nao_achou.text


@pytest.mark.asyncio
async def test_filtro_so_sem_preco_encontra_o_que_ficou_de_fora_do_mes(world, admin):
    await _publicar_preco(world, world.product_id)
    await _criar(admin, world)

    pagina = await admin.get("/portal/products?sem_preco=1")

    assert "RBF-200" in pagina.text
    assert "TEX-75-36-CRU" not in pagina.text


@pytest.mark.asyncio
async def test_lista_conta_quantos_clientes_preferem_o_artigo(world, admin):
    # O cenário já tem uma preferência ativa para o produto do tenant.
    pagina = await admin.get("/portal/products")

    linha = pagina.text.split("TEX-75-36-CRU")[1][:600]
    assert ">1<" in linha.replace(" ", "").replace("\n", "")


# ------------------------------------------------------------------ cadastro


@pytest.mark.asyncio
async def test_cadastrar_artigo_sem_disponibilidade_nao_cria_lote(world, admin):
    resposta = await _criar(admin, world)

    assert "Artigo cadastrado no catálogo." in resposta.text
    assert [p.sku for p in await _tudo(world, Product) if p.sku == "RBF-200"]
    # Catálogo é catálogo: sem disponibilidade escolhida, nenhum preço nasce.
    assert await _tudo(world, PriceList) == []
    assert await _tudo(world, PriceListItem) == []


@pytest.mark.asyncio
async def test_cadastrar_com_disponibilidade_abre_o_rascunho(world, admin):
    resposta = await _criar(admin, world, availability="AVAILABLE", base_price="18,50")

    assert "O preço entrou como rascunho" in resposta.text
    lotes = await _tudo(world, PriceList)
    assert len(lotes) == 1
    assert lotes[0].status is PriceListStatus.DRAFT
    assert (await _tudo(world, PriceListItem))[0].base_price == Decimal("18.50")


@pytest.mark.asyncio
async def test_disponibilidade_sem_preco_recusa_e_nao_deixa_artigo_orfao(world, admin):
    resposta = await _criar(admin, world, availability="AVAILABLE", base_price="")

    assert "Informe o preço-base" in resposta.text
    # A validação acontece antes de o produto existir; sem isso o artigo
    # sobraria no catálogo com o erro na tela.
    assert not [p for p in await _tudo(world, Product) if p.sku == "RBF-200"]


@pytest.mark.asyncio
async def test_sku_duplicado_e_recusado(world, admin):
    resposta = await _criar(admin, world, sku="TEX-75-36-CRU")

    assert "Já existe um artigo com esse SKU" in resposta.text
    assert len(await _tudo(world, Product)) == 1


# ------------------------------------------------------------------- edição


@pytest.mark.asyncio
async def test_editar_nome_especificacao_e_unidade(world, admin):
    pagina = await admin.get("/portal/products")
    resposta = await admin.post(
        f"/portal/products/{world.product_id}",
        data={
            "acao": "salvar",
            "commercial_name": "75/36 trama cru premium",
            "specification": "fio 75 den, 36 filamentos",
            "unit": "mt",
            "family_id": await _familia_id(world),
            "csrf_token": _token(pagina.text),
        },
    )

    assert "Artigo atualizado." in resposta.text
    async with world.app.state.session_factory() as session:
        produto = await session.get(Product, world.product_id)
    assert produto.commercial_name == "75/36 trama cru premium"
    assert produto.specification == "fio 75 den, 36 filamentos"
    assert produto.unit == "MT"


@pytest.mark.asyncio
async def test_sku_e_editavel_enquanto_nao_ha_preco_publicado(world, admin):
    pagina = await admin.get("/portal/products")
    resposta = await admin.post(
        f"/portal/products/{world.product_id}",
        data={
            "acao": "salvar",
            "commercial_name": "75/36 trama cru",
            "sku": "TEX-75-36-CRU-V2",
            "family_id": await _familia_id(world),
            "csrf_token": _token(pagina.text),
        },
    )

    assert "Artigo atualizado." in resposta.text
    async with world.app.state.session_factory() as session:
        produto = await session.get(Product, world.product_id)
    assert produto.sku == "TEX-75-36-CRU-V2"


@pytest.mark.asyncio
async def test_sku_trava_depois_do_primeiro_preco_publicado(world, admin):
    await _publicar_preco(world, world.product_id)

    pagina = await admin.get("/portal/products")
    resposta = await admin.post(
        f"/portal/products/{world.product_id}",
        data={
            "acao": "salvar",
            "commercial_name": "75/36 trama cru",
            "sku": "OUTRO-SKU",
            "family_id": await _familia_id(world),
            "csrf_token": _token(pagina.text),
        },
    )

    assert "já tem preço publicado" in resposta.text
    async with world.app.state.session_factory() as session:
        produto = await session.get(Product, world.product_id)
    assert produto.sku == "TEX-75-36-CRU"
    # E a tela nem oferece o campo.
    assert "Travado: este artigo já tem preço publicado" in pagina.text


@pytest.mark.asyncio
async def test_desativar_artigo_preserva_a_preferencia_do_cliente(world, admin):
    pagina = await admin.get("/portal/products")
    resposta = await admin.post(
        f"/portal/products/{world.product_id}",
        data={"acao": "desativar", "csrf_token": _token(pagina.text)},
    )

    assert "Artigo desativado." in resposta.text
    async with world.app.state.session_factory() as session:
        produto = await session.get(Product, world.product_id)
    assert produto.active is False

    # A preferência continua de pé: desativar é sobre a tabela, não sobre o que
    # o cliente escolheu.
    from crm_api.models.catalog import CustomerPreferredProduct

    preferencias = await _tudo(world, CustomerPreferredProduct)
    assert len(preferencias) == 1
    assert preferencias[0].active is True

    # E ele sai da tabela do mês, que é o que `Product.active` filtra.
    await _publicar_preco(world, world.product_id)
    tabela = await admin.get("/portal/prices")
    assert "TEX-75-36-CRU" not in tabela.text


@pytest.mark.asyncio
async def test_ficha_do_cliente_avisa_que_o_preferido_foi_desativado(world, admin):
    """Sem o aviso, o preferido some da lista e a ficha não explica por quê."""
    pagina = await admin.get("/portal/products")
    await admin.post(
        f"/portal/products/{world.product_id}",
        data={"acao": "desativar", "csrf_token": _token(pagina.text)},
    )

    ficha = await admin.get(f"/portal/customers/{world.customer_a_id}")

    assert "artigo desativado" in ficha.text


@pytest.mark.asyncio
async def test_reativar_traz_o_artigo_de_volta(world, admin):
    pagina = await admin.get("/portal/products")
    await admin.post(
        f"/portal/products/{world.product_id}",
        data={"acao": "desativar", "csrf_token": _token(pagina.text)},
    )
    resposta = await admin.post(
        f"/portal/products/{world.product_id}",
        data={"acao": "ativar", "csrf_token": _token(pagina.text)},
    )

    assert "Artigo reativado" in resposta.text
    async with world.app.state.session_factory() as session:
        assert (await session.get(Product, world.product_id)).active is True


@pytest.mark.asyncio
async def test_editar_nao_toca_no_preco_publicado(world, admin):
    await _publicar_preco(world, world.product_id, preco="12.34")

    pagina = await admin.get("/portal/products")
    await admin.post(
        f"/portal/products/{world.product_id}",
        data={
            "acao": "salvar",
            "commercial_name": "outro nome",
            "family_id": await _familia_id(world),
            "csrf_token": _token(pagina.text),
        },
    )

    entradas = await _tudo(world, PriceEntry)
    assert len(entradas) == 1
    assert entradas[0].base_price == Decimal("12.34")


# ----------------------------------------------------------------- famílias


@pytest.mark.asyncio
async def test_criar_familia_e_renomear(world, admin):
    pagina = await admin.get("/portal/products")
    criada = await admin.post(
        "/portal/families",
        data={"name": "Elásticos", "display_order": "5", "csrf_token": _token(pagina.text)},
    )
    assert "Família cadastrada." in criada.text

    async with world.app.state.session_factory() as session:
        familia = await session.scalar(
            select(ProductFamily).where(ProductFamily.name == "Elásticos")
        )
        familia_id = familia.id
    assert familia.display_order == 5

    renomeada = await admin.post(
        f"/portal/families/{familia_id}",
        data={
            "acao": "salvar",
            "name": "Elásticos e cadarços",
            "display_order": "2",
            "csrf_token": _token(pagina.text),
        },
    )
    assert "Família atualizada." in renomeada.text
    async with world.app.state.session_factory() as session:
        familia = await session.get(ProductFamily, familia_id)
    assert familia.name == "Elásticos e cadarços"
    assert familia.display_order == 2


@pytest.mark.asyncio
async def test_nome_de_familia_duplicado_e_recusado(world, admin):
    pagina = await admin.get("/portal/products")
    resposta = await admin.post(
        "/portal/families",
        data={"name": "Texturizado", "csrf_token": _token(pagina.text)},
    )

    assert "Já existe uma família com esse nome." in resposta.text
    assert len(await _tudo(world, ProductFamily)) == 1


@pytest.mark.asyncio
async def test_ordem_de_familia_precisa_ser_inteira(world, admin):
    pagina = await admin.get("/portal/products")
    resposta = await admin.post(
        "/portal/families",
        data={"name": "Elásticos", "display_order": "primeiro", "csrf_token": _token(pagina.text)},
    )

    assert "precisa ser um número inteiro" in resposta.text
    assert len(await _tudo(world, ProductFamily)) == 1


@pytest.mark.asyncio
async def test_desativar_familia_tira_os_artigos_dela_da_tabela(world, admin):
    await _publicar_preco(world, world.product_id)
    familia_id = await _familia_id(world)

    pagina = await admin.get("/portal/products")
    await admin.post(
        f"/portal/families/{familia_id}",
        data={"acao": "desativar", "csrf_token": _token(pagina.text)},
    )

    tabela = await admin.get("/portal/prices")
    assert "TEX-75-36-CRU" not in tabela.text


# ------------------------------------------------------------------- papéis


@pytest.mark.asyncio
async def test_representante_nao_alcanca_a_tela_de_produtos(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/products")
        ficha = await client.get(f"/portal/customers/{world.customer_a_id}")

    assert "Seu papel não permite essa operação." in pagina.text
    assert 'href="/portal/products"' not in ficha.text


@pytest.mark.asyncio
async def test_representante_nao_cadastra_nem_edita_pelo_post(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        ficha = await client.get(f"/portal/customers/{world.customer_a_id}")
        token = _token(ficha.text)
        await client.post(
            "/portal/products",
            data={"sku": "X-1", "commercial_name": "Forjado", "csrf_token": token},
        )
        await client.post(
            f"/portal/products/{world.product_id}",
            data={"acao": "desativar", "csrf_token": token},
        )

    assert len(await _tudo(world, Product)) == 1
    async with world.app.state.session_factory() as session:
        assert (await session.get(Product, world.product_id)).active is True


@pytest.mark.asyncio
async def test_sem_csrf_nada_e_gravado(world, admin):
    await admin.post(
        "/portal/products",
        data={"sku": "X-1", "commercial_name": "Forjado", "csrf_token": "invalido"},
    )
    await admin.post(
        "/portal/families", data={"name": "Forjada", "csrf_token": "invalido"}
    )

    assert len(await _tudo(world, Product)) == 1
    assert len(await _tudo(world, ProductFamily)) == 1
