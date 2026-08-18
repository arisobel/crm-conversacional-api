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

from crm_api.models.customer import Customer, CustomerLocation
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import User

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _browser(world):
    """Cliente que segue redirecionamentos, como um navegador."""
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


async def _entrar(client, email: str, senha: str = PASSWORD):
    pagina = await client.get("/portal/login")
    return await client.post(
        "/portal/login",
        data={"email": email, "password": senha, "csrf_token": _token(pagina.text)},
    )


@pytest_asyncio.fixture
async def admin(world):
    async with _browser(world) as client:
        resposta = await _entrar(client, ADMIN_EMAIL)
        assert resposta.status_code == 200
        yield client


# ---------------------------------------------------------------- sessão


@pytest.mark.asyncio
async def test_pagina_protegida_redireciona_para_o_login(world):
    async with _browser(world) as client:
        resposta = await client.get("/portal/customers")

    assert resposta.status_code == 200
    assert str(resposta.url).endswith("/portal/login")
    assert "Portal do representante" in resposta.text


@pytest.mark.asyncio
async def test_login_leva_para_a_carteira(world):
    async with _browser(world) as client:
        resposta = await _entrar(client, ADMIN_EMAIL)

    assert resposta.status_code == 200
    assert "/portal/customers" in str(resposta.url)
    assert "Gestora Exemplo" in resposta.text


@pytest.mark.asyncio
async def test_login_errado_nao_vaza_qual_campo_falhou(world):
    async with _browser(world) as client:
        errada = await _entrar(client, ADMIN_EMAIL, "SenhaErrada12345")
        inexistente = await _entrar(client, "ninguem@teste.com.br", PASSWORD)

    assert errada.status_code == inexistente.status_code == 401
    assert "E-mail ou senha inválidos." in errada.text
    assert "E-mail ou senha inválidos." in inexistente.text


@pytest.mark.asyncio
async def test_formulario_sem_csrf_e_recusado(world):
    """Sem o token, o POST é rejeitado antes de tocar o banco."""
    async with _browser(world) as client:
        await client.get("/portal/login")
        resposta = await client.post(
            "/portal/login", data={"email": ADMIN_EMAIL, "password": PASSWORD}
        )

    assert resposta.status_code == 400
    assert "formulário expirou" in resposta.text


@pytest.mark.asyncio
async def test_csrf_de_outra_origem_nao_serve(world):
    async with _browser(world) as client:
        await client.get("/portal/login")
        resposta = await client.post(
            "/portal/login",
            data={
                "email": ADMIN_EMAIL,
                "password": PASSWORD,
                "csrf_token": "token-forjado-por-outro-site",
            },
        )

    assert resposta.status_code == 400


@pytest.mark.asyncio
async def test_logout_encerra_a_sessao(world, admin):
    pagina = await admin.get("/portal/customers")
    resposta = await admin.post("/portal/logout", data={"csrf_token": _token(pagina.text)})

    assert str(resposta.url).endswith("/portal/login")

    seguinte = await admin.get("/portal/customers")
    assert str(seguinte.url).endswith("/portal/login")


# -------------------------------------------------------------- carteira


@pytest.mark.asyncio
async def test_representante_ve_apenas_a_propria_carteira(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await client.get("/portal/customers")

    assert "Alfa Tecelagem Ltda." in resposta.text
    assert "Beta Malharia Ltda." not in resposta.text
    assert "Gama Confecções Ltda." not in resposta.text
    # Sem papel de gestão, não aparece o menu de representantes.
    assert "/portal/users" not in resposta.text


@pytest.mark.asyncio
async def test_admin_ve_todo_o_tenant(admin):
    resposta = await admin.get("/portal/customers")

    for nome in ("Alfa Tecelagem", "Beta Malharia", "Gama Confecções"):
        assert nome in resposta.text


@pytest.mark.asyncio
async def test_filtro_por_uf_reduz_a_lista(admin):
    resposta = await admin.get("/portal/customers?uf=rs")

    assert "Beta Malharia" in resposta.text
    assert "Alfa Tecelagem" not in resposta.text


@pytest.mark.asyncio
async def test_cliente_de_outra_carteira_volta_para_a_lista(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await client.get(f"/portal/customers/{world.customer_b_id}")

    assert str(resposta.url).endswith("/portal/customers?m=nao-encontrado")
    assert "Registro não encontrado." in resposta.text


# --------------------------------------------------------------- cadastro


@pytest.mark.asyncio
async def test_cadastro_de_cliente_cria_a_localidade_padrao(world, admin):
    pagina = await admin.get("/portal/customers/novo")
    resposta = await admin.post(
        "/portal/customers/novo",
        data={
            "csrf_token": _token(pagina.text),
            "legal_name": "Delta Fiação Ltda.",
            "trade_name": "Delta",
            "state_code": "mg",
            "document_number": "44444444000144",
            "owner_user_id": str(world.representative_b_id),
        },
    )

    assert resposta.status_code == 200
    assert "Cliente cadastrado." in resposta.text
    assert "Principal" in resposta.text

    async with world.app.state.session_factory() as session:
        cliente = await session.scalar(
            select(Customer).where(Customer.legal_name == "Delta Fiação Ltda.")
        )
        local = await session.scalar(
            select(CustomerLocation).where(CustomerLocation.customer_id == cliente.id)
        )

    assert cliente.state_code == "MG"
    assert cliente.owner_user_id == world.representative_b_id
    assert (local.label, local.state_code, local.is_default) == ("Principal", "MG", True)


@pytest.mark.asyncio
async def test_uf_invalida_mostra_mensagem_em_portugues(admin):
    pagina = await admin.get("/portal/customers/novo")
    resposta = await admin.post(
        "/portal/customers/novo",
        data={"csrf_token": _token(pagina.text), "legal_name": "Zeta", "state_code": "XX"},
    )

    assert "UF inválida" in resposta.text
    assert "is not a Brazilian state code" not in resposta.text


@pytest.mark.asyncio
async def test_acentuacao_sobrevive_ao_formulario(world, admin):
    pagina = await admin.get("/portal/customers/novo")
    await admin.post(
        "/portal/customers/novo",
        data={
            "csrf_token": _token(pagina.text),
            "legal_name": "Tecelagem Conceição & Assunção Ltda.",
            "state_code": "SP",
        },
    )

    async with world.app.state.session_factory() as session:
        cliente = await session.scalar(
            select(Customer).where(Customer.trade_name.is_(None), Customer.state_code == "SP")
        )
        nomes = list(await session.scalars(select(Customer.legal_name)))

    assert "Tecelagem Conceição & Assunção Ltda." in nomes
    assert cliente is not None


@pytest.mark.asyncio
async def test_contato_e_criado_com_telefone_normalizado(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/contacts",
        data={
            "csrf_token": _token(pagina.text),
            "name": "Vitória Exemplo",
            "whatsapp_e164": "+55 (11) 99999-9999",
            "is_primary": "1",
        },
    )

    assert "Contato adicionado." in resposta.text
    assert "+5511999999999" in resposta.text

    async with world.app.state.session_factory() as session:
        contato = await session.scalar(select(CustomerContact))
    assert contato.is_primary is True


@pytest.mark.asyncio
async def test_telefone_invalido_mostra_mensagem_amigavel(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/contacts",
        data={"csrf_token": _token(pagina.text), "name": "Sem DDI", "whatsapp_e164": "11999"},
    )

    assert "Telefone inválido" in resposta.text


@pytest.mark.asyncio
async def test_localidade_padrao_nao_pode_ser_desativada(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    criada = await admin.post(
        f"/portal/customers/{world.customer_a_id}/locations",
        data={"csrf_token": _token(pagina.text), "label": "Matriz", "state_code": "SP"},
    )
    assert "Localidade adicionada." in criada.text

    async with world.app.state.session_factory() as session:
        local = await session.scalar(select(CustomerLocation))

    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/locations/{local.id}",
        data={"csrf_token": _token(criada.text), "acao": "desativar"},
    )

    assert "Promova outra localidade a padrão" in resposta.text


@pytest.mark.asyncio
async def test_transferencia_de_titular_pelo_portal(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/owner",
        data={
            "csrf_token": _token(pagina.text),
            "owner_user_id": str(world.representative_b_id),
            "reason": "férias",
        },
    )

    assert "Titular atualizado." in resposta.text
    assert "Vendedor B" in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_transfere_titular(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get(f"/portal/customers/{world.customer_a_id}")
        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/owner",
            data={
                "csrf_token": _token(pagina.text),
                "owner_user_id": str(world.representative_b_id),
            },
        )

    assert "Seu papel não permite" in resposta.text

    async with world.app.state.session_factory() as session:
        cliente = await session.scalar(
            select(Customer).where(Customer.id == world.customer_a_id)
        )
    assert cliente.owner_user_id == world.representative_a_id


# --------------------------------------------------------- representantes


@pytest.mark.asyncio
async def test_admin_cria_representante_pelo_portal(world, admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Nova Vendedora",
            "email": "nova@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
        },
    )

    assert "Usuário criado." in resposta.text
    assert "nova@teste.com.br" in resposta.text

    async with world.app.state.session_factory() as session:
        criada = await session.scalar(select(User).where(User.email == "nova@teste.com.br"))
    assert criada.role.value == "REPRESENTATIVE"


@pytest.mark.asyncio
async def test_admin_cria_representante_com_whatsapp_livre(world, admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Vendedora Com Zap",
            "email": "comzap@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+551188887777",
        },
    )

    assert resposta.status_code == 200
    assert "Usuário criado." in resposta.text

    async with world.app.state.session_factory() as session:
        criada = await session.scalar(select(User).where(User.email == "comzap@teste.com.br"))
    # Canonizado na borda: o nono dígito entra no cadastro, não na consulta.
    assert criada.whatsapp_e164 == "+5511988887777"


@pytest.mark.asyncio
async def test_whatsapp_de_contato_de_cliente_nao_vira_500(world, admin):
    """A recusa é correta; o 500 era só a ausência de tradução.

    `_codigo_do_erro` relança o que não conhece, e `WhatsappAlreadyUsed` não
    estava na tabela — uma regra de negócio funcionando virava erro de servidor.
    """
    ocupado = "+5511975714368"
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_a_id,
                name="Compras Alfa",
                whatsapp_e164=ocupado,
                is_primary=True,
            )
        )
        await session.commit()

    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Colide Com Contato",
            "email": "colide@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": ocupado,
        },
    )

    assert resposta.status_code == 200
    assert "já está em uso" in resposta.text
    # Nada de tripa interna na tela.
    assert "Traceback" not in resposta.text
    assert "WhatsappAlreadyUsed" not in resposta.text

    async with world.app.state.session_factory() as session:
        # Nenhum registro parcial: o usuário não existe, e o contato segue dono
        # do número.
        assert await session.scalar(select(User).where(User.email == "colide@teste.com.br")) is None
        contato = await session.scalar(
            select(CustomerContact).where(CustomerContact.whatsapp_e164 == ocupado)
        )
        assert contato is not None


@pytest.mark.asyncio
async def test_whatsapp_de_outro_usuario_do_portal_tambem_e_recusado(world, admin):
    """Mesma exceção, outra origem — a colisão entre dois usuários do portal."""
    pagina = await admin.get("/portal/users")
    await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Primeiro Dono",
            "email": "primeiro@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+5511966665555",
        },
    )

    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Segundo Dono",
            "email": "segundo@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+5511966665555",
        },
    )

    assert resposta.status_code == 200
    assert "já está em uso" in resposta.text

    async with world.app.state.session_factory() as session:
        assert (
            await session.scalar(select(User).where(User.email == "segundo@teste.com.br"))
        ) is None


@pytest.mark.asyncio
async def test_email_duplicado_continua_com_a_mensagem_de_sempre(world, admin):
    """Regressão da tabela: acrescentar um código não pode mover os outros."""
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Repetido",
            "email": ADMIN_EMAIL,
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
        },
    )

    assert resposta.status_code == 200
    assert "Já existe um usuário com esse e-mail." in resposta.text


@pytest.mark.asyncio
async def test_telefone_invalido_continua_distinto_de_telefone_em_uso(admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Telefone Torto",
            "email": "torto@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "1199",
        },
    )

    assert resposta.status_code == 200
    assert "Telefone inválido" in resposta.text
    assert "já está em uso" not in resposta.text


@pytest.mark.asyncio
async def test_senha_fraca_explica_a_politica(admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Fraca",
            "email": "fraca@teste.com.br",
            "password": "curta1",
            "role": "REPRESENTATIVE",
        },
    )

    assert "Senha recusada" in resposta.text


@pytest.mark.asyncio
async def test_admin_nao_desativa_a_propria_conta(world, admin):
    pagina = await admin.get("/portal/users")

    # A tela não oferece o botão para a própria conta.
    assert f'action="/portal/users/{world.admin_id}"' not in pagina.text

    # E a rota recusa mesmo se o POST for forjado à mão.
    resposta = await admin.post(
        f"/portal/users/{world.admin_id}",
        data={"csrf_token": _token(pagina.text), "acao": "desativar"},
    )
    assert "não pode desativar a própria conta" in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_alcanca_a_tela_de_usuarios(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await client.get("/portal/users")

    assert str(resposta.url).endswith("/portal/customers?m=sem-permissao")
    assert "Seu papel não permite" in resposta.text


@pytest.mark.asyncio
async def test_folha_de_estilo_e_servida(world):
    async with _browser(world) as client:
        resposta = await client.get("/portal/static/portal.css")

    assert resposta.status_code == 200
    assert "text/css" in resposta.headers["content-type"]
