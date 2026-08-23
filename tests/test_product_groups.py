"""Grupo de artigo: agrupamento livre e multivalorado, ao lado da família.

A razão de existir está na diferença entre os dois. **Família é layout**: uma
por artigo, porque é ela que agrupa a tabela impressa para o cliente. **Grupo é
consulta**: quantos couberem, porque um fio de alta tenacidade é poliéster *e*
é alta-tenacidade.

O que estes testes prendem:

- a família não mudou — continua uma só, e etiquetar não a toca;
- nomes equivalentes não viram grupos irmãos, o que dividiria o público de um
  disparo em silêncio;
- representante cria grupo e etiqueta, mas não renomeia, não desativa e não
  mexe em família nem em artigo.
"""

import re
from contextlib import asynccontextmanager

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

from crm_api.core.text import normalize_group_name
from crm_api.models.catalog import Product, ProductGroup, ProductGroupMember
from crm_api.models.user import AuditLog

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


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


async def _criar_grupo(client, nome: str):
    pagina = await client.get("/portal/products")
    return await client.post(
        "/portal/product-groups",
        data={"name": nome, "csrf_token": _token(pagina.text)},
    )


async def _grupos(world) -> list[ProductGroup]:
    async with world.app.state.session_factory() as session:
        return list(await session.scalars(select(ProductGroup)))


async def _vinculos(world) -> list[ProductGroupMember]:
    async with world.app.state.session_factory() as session:
        return list(await session.scalars(select(ProductGroupMember)))


async def _id_do_grupo(world, nome: str) -> str:
    canonico = normalize_group_name(nome)
    return str(next(g.id for g in await _grupos(world) if g.normalized_name == canonico))


async def _etiquetar(client, world, produto_id, grupo_nome, acao="incluir"):
    pagina = await client.get("/portal/products")
    return await client.post(
        f"/portal/products/{produto_id}/groups",
        data={
            "acao": acao,
            "group_id": await _id_do_grupo(world, grupo_nome),
            "csrf_token": _token(pagina.text),
        },
    )


# --------------------------------------------------------- criar e canonizar


@pytest.mark.asyncio
async def test_admin_cria_grupo(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _criar_grupo(admin, "Poliéster")

    assert "Grupo de artigo criado." in resposta.text
    grupos = await _grupos(world)
    assert len(grupos) == 1
    # O digitado é preservado; o canônico é o que a unicidade compara.
    assert grupos[0].name == "Poliéster"
    assert grupos[0].normalized_name == "poliester"


@pytest.mark.asyncio
async def test_nome_equivalente_nao_cria_grupo_irmao(world):
    """Sem isto, o público de um disparo racha e ninguém percebe."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        resposta = await _criar_grupo(admin, "  POLIESTER ")

    assert "Já existe um grupo com esse nome" in resposta.text
    assert len(await _grupos(world)) == 1


@pytest.mark.asyncio
async def test_grupo_sem_nome_e_recusado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _criar_grupo(admin, "   ")

    assert "Dê um nome ao grupo." in resposta.text
    assert await _grupos(world) == []


@pytest.mark.asyncio
async def test_criacao_fica_auditada_com_o_autor(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Viscose")

    async with world.app.state.session_factory() as session:
        registros = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "PRODUCT_GROUP_CREATED")
            )
        ).all()
        assert len(registros) == 1
        assert registros[0].actor_user_id == world.admin_id
        assert registros[0].after["name"] == "Viscose"


# ------------------------------------------------------- o ponto do N↔N


@pytest.mark.asyncio
async def test_um_artigo_pode_estar_em_varios_grupos(world):
    """O caso que motivou a `0013`: poliéster **e** alta-tenacidade."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _criar_grupo(admin, "Alta-tenacidade")
        await _etiquetar(admin, world, world.product_id, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Alta-tenacidade")

    assert len(await _vinculos(world)) == 2


@pytest.mark.asyncio
async def test_etiquetar_nao_toca_na_familia_do_artigo(world):
    """Família é layout e continua uma só; grupo não a substitui."""
    async with world.app.state.session_factory() as session:
        antes = (await session.scalar(select(Product))).family_id

    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Poliéster")

    async with world.app.state.session_factory() as session:
        assert (await session.scalar(select(Product))).family_id == antes


@pytest.mark.asyncio
async def test_incluir_duas_vezes_nao_duplica_nem_falha(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Poliéster")
        resposta = await _etiquetar(admin, world, world.product_id, "Poliéster")

    assert "Grupos do artigo atualizados." in resposta.text
    assert len(await _vinculos(world)) == 1


@pytest.mark.asyncio
async def test_remover_etiqueta(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Poliéster", acao="remover")

    assert await _vinculos(world) == []


@pytest.mark.asyncio
async def test_remover_o_que_nao_esta_la_e_silencioso(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        resposta = await _etiquetar(
            admin, world, world.product_id, "Poliéster", acao="remover"
        )

    assert "Grupos do artigo atualizados." in resposta.text
    assert await _vinculos(world) == []


@pytest.mark.asyncio
async def test_grupos_aparecem_na_lista_de_produtos(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Poliéster")
        pagina = await admin.get("/portal/products")

    assert "Poliéster" in pagina.text
    assert "Grupos de artigo" in pagina.text


# ----------------------------------------------------------------- alçadas


@pytest.mark.asyncio
async def test_representante_cria_grupo_e_etiqueta(world):
    """O pedido do Charles: criar livremente, sem depender da gestão."""
    async with _browser(world) as rep:
        await _entrar(rep, REPRESENTATIVE_A_EMAIL)
        criou = await _criar_grupo(rep, "Alta-tenacidade")
        etiquetou = await _etiquetar(rep, world, world.product_id, "Alta-tenacidade")

    assert "Grupo de artigo criado." in criou.text
    assert "Grupos do artigo atualizados." in etiquetou.text
    assert len(await _vinculos(world)) == 1


@pytest.mark.asyncio
async def test_grupo_criado_por_representante_e_do_tenant(world):
    """A autoria é registrada, mas o grupo vale para todos.

    "Poliéster" que significasse coisas diferentes por representante tornaria o
    público de um disparo imprevisível.
    """
    async with _browser(world) as rep:
        await _entrar(rep, REPRESENTATIVE_A_EMAIL)
        await _criar_grupo(rep, "Poliéster")

    grupos = await _grupos(world)
    assert grupos[0].created_by == world.representative_a_id

    async with _browser(world) as outro:
        await _entrar(outro, ADMIN_EMAIL)
        pagina = await outro.get("/portal/products")
        assert "Poliéster" in pagina.text


@pytest.mark.asyncio
async def test_representante_nao_renomeia_nem_desativa_grupo(world):
    """Criar não desfaz o trabalho de ninguém; renomear e desativar, sim."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")

    grupo_id = await _id_do_grupo(world, "Poliéster")
    async with _browser(world) as rep:
        await _entrar(rep, REPRESENTATIVE_A_EMAIL)
        pagina = await rep.get("/portal/products")
        renomear = await rep.post(
            f"/portal/product-groups/{grupo_id}",
            data={
                "acao": "renomear",
                "name": "Outro nome",
                "csrf_token": _token(pagina.text),
            },
        )
        desativar = await rep.post(
            f"/portal/product-groups/{grupo_id}",
            data={"acao": "desativar", "csrf_token": _token(pagina.text)},
        )

    assert "Seu papel não permite essa operação." in renomear.text
    assert "Seu papel não permite essa operação." in desativar.text
    grupos = await _grupos(world)
    assert grupos[0].name == "Poliéster"
    assert grupos[0].active is True


@pytest.mark.asyncio
async def test_gestao_renomeia_e_desativa(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliester")
        grupo_id = await _id_do_grupo(world, "Poliester")
        pagina = await admin.get("/portal/products")

        renomeado = await admin.post(
            f"/portal/product-groups/{grupo_id}",
            data={
                "acao": "renomear",
                "name": "Poliéster",
                "csrf_token": _token(pagina.text),
            },
        )
        await admin.post(
            f"/portal/product-groups/{grupo_id}",
            data={"acao": "desativar", "csrf_token": _token(pagina.text)},
        )

    assert "Grupo atualizado." in renomeado.text
    grupos = await _grupos(world)
    assert grupos[0].name == "Poliéster"
    assert grupos[0].active is False


@pytest.mark.asyncio
async def test_desativar_preserva_as_etiquetas(world):
    """Desativar tira de circulação; apagar perderia trabalho manual."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _etiquetar(admin, world, world.product_id, "Poliéster")
        grupo_id = await _id_do_grupo(world, "Poliéster")
        pagina = await admin.get("/portal/products")
        await admin.post(
            f"/portal/product-groups/{grupo_id}",
            data={"acao": "desativar", "csrf_token": _token(pagina.text)},
        )

    assert len(await _vinculos(world)) == 1


@pytest.mark.asyncio
async def test_renomear_para_nome_equivalente_a_outro_e_recusado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        await _criar_grupo(admin, "Viscose")
        grupo_id = await _id_do_grupo(world, "Viscose")
        pagina = await admin.get("/portal/products")

        resposta = await admin.post(
            f"/portal/product-groups/{grupo_id}",
            data={
                "acao": "renomear",
                "name": "poliester",
                "csrf_token": _token(pagina.text),
            },
        )

    assert "Já existe um grupo com esse nome" in resposta.text
    assert {g.name for g in await _grupos(world)} == {"Poliéster", "Viscose"}


@pytest.mark.asyncio
async def test_etiquetar_sem_csrf_nao_passa(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _criar_grupo(admin, "Poliéster")
        resposta = await admin.post(
            f"/portal/products/{world.product_id}/groups",
            data={
                "acao": "incluir",
                "group_id": await _id_do_grupo(world, "Poliéster"),
                "csrf_token": "token-de-outro-lugar",
            },
        )

    assert "O formulário expirou." in resposta.text
    assert await _vinculos(world) == []
