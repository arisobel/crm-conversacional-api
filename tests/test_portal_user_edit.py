"""Edição de usuário do portal pela tela.

`update` já existia no serviço e na API; faltava o botão. O portal também faz
uma coisa que a API não consegue: **limpar** o WhatsApp. Lá o schema valida o
campo contra E.164 e `None` significa "não mexa", então não há como expressar
"apague este número".

As guardas que importam, todas com teste:

- o último `ADMIN` ativo não pode ser rebaixado;
- ninguém fica sem nome;
- telefone que já é de outro usuário, ou de um contato de cliente, é recusado —
  a colisão é a rota de escalação mais barata do desenho;
- representante não edita ninguém.
"""

import re
from contextlib import asynccontextmanager
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

from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import AuditLog, User

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
    found = _CSRF.search(html)
    assert found, "página não trouxe campo csrf_token"
    return found.group(1)


async def _entrar(client, email: str, password: str = PASSWORD):
    page = await client.get("/portal/login")
    return await client.post(
        "/portal/login",
        data={"email": email, "password": password, "csrf_token": _token(page.text)},
    )


async def _editar(client, user_id, **campos):
    pagina = await client.get("/portal/users")
    dados = {"csrf_token": _token(pagina.text), **campos}
    return await client.post(f"/portal/users/{user_id}/editar", data=dados)


async def _recarregar(world, user_id) -> User:
    async with world.app.state.session_factory() as session:
        return await session.get(User, user_id)


@pytest.mark.asyncio
async def test_admin_edita_nome_papel_e_whatsapp(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A. Silva",
            role="MANAGER",
            whatsapp_e164="+5511988887777",
        )
        assert "Usuário atualizado." in resposta.text

    usuario = await _recarregar(world, world.representative_a_id)
    assert usuario.full_name == "Vendedora A. Silva"
    assert usuario.role.value == "MANAGER"
    assert usuario.whatsapp_e164 == "+5511988887777"


@pytest.mark.asyncio
async def test_whatsapp_aparece_na_lista(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="REPRESENTATIVE",
            whatsapp_e164="+5511988887777",
        )
        pagina = await admin.get("/portal/users")
        assert "+5511988887777" in pagina.text


@pytest.mark.asyncio
async def test_campo_vazio_remove_o_whatsapp(world):
    """O que a API não consegue expressar: apagar o número."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="REPRESENTATIVE",
            whatsapp_e164="+5511988887777",
        )
        assert (await _recarregar(world, world.representative_a_id)).whatsapp_e164

        await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="REPRESENTATIVE",
            whatsapp_e164="",
        )

    assert (await _recarregar(world, world.representative_a_id)).whatsapp_e164 is None


@pytest.mark.asyncio
async def test_nome_em_branco_e_recusado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.representative_a_id,
            full_name="   ",
            role="REPRESENTATIVE",
            whatsapp_e164="",
        )
        assert "Alteração recusada" in resposta.text

    assert (await _recarregar(world, world.representative_a_id)).full_name == "Vendedora A"


@pytest.mark.asyncio
async def test_ultimo_admin_nao_pode_ser_rebaixado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.admin_id,
            full_name="Gestora Exemplo",
            role="REPRESENTATIVE",
            whatsapp_e164="",
        )
        assert "Alteração recusada" in resposta.text

    assert (await _recarregar(world, world.admin_id)).role.value == "ADMIN"


@pytest.mark.asyncio
async def test_telefone_de_outro_usuario_e_recusado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="REPRESENTATIVE",
            whatsapp_e164="+5511988887777",
        )
        resposta = await _editar(
            admin,
            world.representative_b_id,
            full_name="Vendedor B",
            role="REPRESENTATIVE",
            whatsapp_e164="+5511988887777",
        )
        assert "Usuário atualizado." not in resposta.text

    assert (await _recarregar(world, world.representative_b_id)).whatsapp_e164 is None


@pytest.mark.asyncio
async def test_telefone_de_contato_de_cliente_e_recusado(world):
    """A colisão que daria capacidades de representante a um contato."""
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_a_id,
                name="Compras Alfa",
                whatsapp_e164="+5511977776666",
                is_primary=True,
            )
        )
        await session.commit()

    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="REPRESENTATIVE",
            whatsapp_e164="+5511977776666",
        )
        assert "Usuário atualizado." not in resposta.text

    assert (await _recarregar(world, world.representative_a_id)).whatsapp_e164 is None


@pytest.mark.asyncio
async def test_telefone_malformado_e_recusado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="REPRESENTATIVE",
            whatsapp_e164="11 99999-8888 sem país",
        )
        assert "Usuário atualizado." not in resposta.text


@pytest.mark.asyncio
async def test_papel_fora_da_lista_e_recusado(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A",
            role="SUPERUSER",
            whatsapp_e164="",
        )
        assert "Papel inválido." in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_edita_ninguem(world):
    async with _browser(world) as representante:
        await _entrar(representante, REPRESENTATIVE_A_EMAIL)
        token = _token((await representante.get("/portal/customers")).text)

        resposta = await representante.post(
            f"/portal/users/{world.representative_b_id}/editar",
            data={
                "full_name": "Renomeado sem alçada",
                "role": "ADMIN",
                "whatsapp_e164": "",
                "csrf_token": token,
            },
        )
        assert "Seu papel não permite essa operação." in resposta.text

    beta = await _recarregar(world, world.representative_b_id)
    assert beta.full_name == "Vendedor B"
    assert beta.role.value == "REPRESENTATIVE"


@pytest.mark.asyncio
async def test_edicao_sem_csrf_nao_passa(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await admin.post(
            f"/portal/users/{world.representative_a_id}/editar",
            data={
                "full_name": "Sem token",
                "role": "ADMIN",
                "whatsapp_e164": "",
                "csrf_token": "token-de-outro-lugar",
            },
        )
        assert "O formulário expirou." in resposta.text

    assert (await _recarregar(world, world.representative_a_id)).full_name == "Vendedora A"


@pytest.mark.asyncio
async def test_edicao_fica_auditada_com_antes_e_depois(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        await _editar(
            admin,
            world.representative_a_id,
            full_name="Vendedora A. Silva",
            role="REPRESENTATIVE",
            whatsapp_e164="+5511988887777",
        )

    async with world.app.state.session_factory() as session:
        registros = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "USER_UPDATED"))
        ).all()
        assert len(registros) == 1
        assert registros[0].before["full_name"] == "Vendedora A"
        assert registros[0].after["full_name"] == "Vendedora A. Silva"
        assert registros[0].after["whatsapp_e164"] == "+5511988887777"
        assert registros[0].actor_user_id == world.admin_id


@pytest.mark.asyncio
async def test_admin_edita_o_proprio_cadastro(world):
    """Editar a própria linha é útil — é como o ADMIN cadastra o WhatsApp dele."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        resposta = await _editar(
            admin,
            world.admin_id,
            full_name="Gestora Exemplo",
            role="ADMIN",
            whatsapp_e164="+5511966665555",
        )
        assert "Usuário atualizado." in resposta.text

    assert (await _recarregar(world, world.admin_id)).whatsapp_e164 == "+5511966665555"
