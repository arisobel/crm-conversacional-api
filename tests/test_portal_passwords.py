"""Senha pelo portal: redefinição pelo ADMIN e troca pelo próprio usuário.

As duas operações existiam pela metade — `POST /admin/users/{id}/password` na
API, sem botão em tela, e nada de autoatendimento. Um representante que
esquecesse a senha dependia de alguém chamar a API na mão, e não tinha como
trocar a senha que recebeu.

O que estes testes prendem, além do caminho feliz:

- a troca própria **exige a senha atual** — sem isso, um cookie roubado tranca
  o dono para fora da própria conta;
- ela derruba as **outras** sessões e mantém a de quem trocou;
- a redefinição pelo ADMIN derruba **todas**, inclusive a que estava aberta;
- representante não redefine senha de ninguém.
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

from crm_api.models.user import AuditLog

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
NOVA = "TrocaSegura2026x"


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


# ------------------------------------------------- troca da própria senha


@pytest.mark.asyncio
async def test_representante_troca_a_propria_senha_e_entra_com_a_nova(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/minha-senha")
        assert pagina.status_code == 200

        resposta = await client.post(
            "/portal/minha-senha",
            data={
                "current_password": PASSWORD,
                "new_password": NOVA,
                "confirm_password": NOVA,
                "csrf_token": _token(pagina.text),
            },
        )
        assert "Senha trocada." in resposta.text

    # Sessão nova, senha nova.
    async with _browser(world) as outro:
        entrada = await _entrar(outro, REPRESENTATIVE_A_EMAIL, NOVA)
        assert entrada.status_code == 200
        assert "/portal/customers" in str(entrada.url)


@pytest.mark.asyncio
async def test_a_senha_antiga_para_de_valer(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/minha-senha")
        await client.post(
            "/portal/minha-senha",
            data={
                "current_password": PASSWORD,
                "new_password": NOVA,
                "confirm_password": NOVA,
                "csrf_token": _token(pagina.text),
            },
        )

    async with _browser(world) as outro:
        entrada = await _entrar(outro, REPRESENTATIVE_A_EMAIL, PASSWORD)
        assert "E-mail ou senha inválidos." in entrada.text


@pytest.mark.asyncio
async def test_troca_exige_a_senha_atual(world):
    """Sem isso, uma sessão sequestrada trancaria o dono para fora."""
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/minha-senha")

        resposta = await client.post(
            "/portal/minha-senha",
            data={
                "current_password": "nao-e-a-minha-senha",
                "new_password": NOVA,
                "confirm_password": NOVA,
                "csrf_token": _token(pagina.text),
            },
        )
        assert "A senha atual não confere." in resposta.text

    # E a senha original continua valendo.
    async with _browser(world) as outro:
        entrada = await _entrar(outro, REPRESENTATIVE_A_EMAIL, PASSWORD)
        assert "/portal/customers" in str(entrada.url)


@pytest.mark.asyncio
async def test_tentativa_com_senha_atual_errada_fica_auditada(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/minha-senha")
        await client.post(
            "/portal/minha-senha",
            data={
                "current_password": "errada",
                "new_password": NOVA,
                "confirm_password": NOVA,
                "csrf_token": _token(pagina.text),
            },
        )

    async with world.app.state.session_factory() as session:
        registros = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "USER_PASSWORD_CHANGE_REFUSED")
            )
        ).all()
        assert len(registros) == 1
        assert registros[0].actor_user_id == world.representative_a_id


@pytest.mark.asyncio
async def test_confirmacao_divergente_nao_troca_nada(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/minha-senha")

        resposta = await client.post(
            "/portal/minha-senha",
            data={
                "current_password": PASSWORD,
                "new_password": NOVA,
                "confirm_password": NOVA + "x",
                "csrf_token": _token(pagina.text),
            },
        )
        assert "A confirmação não bate com a nova senha." in resposta.text

    async with _browser(world) as outro:
        entrada = await _entrar(outro, REPRESENTATIVE_A_EMAIL, PASSWORD)
        assert "/portal/customers" in str(entrada.url)


@pytest.mark.asyncio
async def test_senha_fraca_e_recusada_na_troca_propria(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get("/portal/minha-senha")

        resposta = await client.post(
            "/portal/minha-senha",
            data={
                "current_password": PASSWORD,
                "new_password": "curta1",
                "confirm_password": "curta1",
                "csrf_token": _token(pagina.text),
            },
        )
        assert "Senha trocada." not in resposta.text


@pytest.mark.asyncio
async def test_troca_propria_derruba_as_outras_sessoes_e_mantem_a_atual(world):
    """A sessão de quem trocou sobrevive; a do outro navegador, não."""
    async with _browser(world) as primeiro, _browser(world) as segundo:
        await _entrar(primeiro, REPRESENTATIVE_A_EMAIL)
        await _entrar(segundo, REPRESENTATIVE_A_EMAIL)

        pagina = await primeiro.get("/portal/minha-senha")
        await primeiro.post(
            "/portal/minha-senha",
            data={
                "current_password": PASSWORD,
                "new_password": NOVA,
                "confirm_password": NOVA,
                "csrf_token": _token(pagina.text),
            },
        )

        # Quem trocou continua dentro.
        continua = await primeiro.get("/portal/customers")
        assert "/portal/login" not in str(continua.url)

        # A outra sessão foi revogada e cai no login.
        caiu = await segundo.get("/portal/customers")
        assert "/portal/login" in str(caiu.url)


# ----------------------------------------------- redefinição pelo ADMIN


@pytest.mark.asyncio
async def test_admin_redefine_senha_de_representante_pela_tela(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        pagina = await admin.get("/portal/users")
        assert "redefinir senha" in pagina.text

        resposta = await admin.post(
            f"/portal/users/{world.representative_a_id}/password",
            data={"password": NOVA, "csrf_token": _token(pagina.text)},
        )
        assert "Senha redefinida." in resposta.text

    async with _browser(world) as representante:
        entrada = await _entrar(representante, REPRESENTATIVE_A_EMAIL, NOVA)
        assert "/portal/customers" in str(entrada.url)


@pytest.mark.asyncio
async def test_redefinicao_derruba_a_sessao_aberta_do_usuario(world):
    async with _browser(world) as representante, _browser(world) as admin:
        await _entrar(representante, REPRESENTATIVE_A_EMAIL)
        await _entrar(admin, ADMIN_EMAIL)

        pagina = await admin.get("/portal/users")
        await admin.post(
            f"/portal/users/{world.representative_a_id}/password",
            data={"password": NOVA, "csrf_token": _token(pagina.text)},
        )

        caiu = await representante.get("/portal/customers")
        assert "/portal/login" in str(caiu.url)


@pytest.mark.asyncio
async def test_representante_nao_redefine_senha_de_ninguem(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        token = _token((await admin.get("/portal/users")).text)

    async with _browser(world) as representante:
        await _entrar(representante, REPRESENTATIVE_A_EMAIL)
        # Token do próprio navegador dele, para isolar a alçada do CSRF.
        proprio = _token((await representante.get("/portal/customers")).text)

        resposta = await representante.post(
            f"/portal/users/{world.representative_b_id}/password",
            data={"password": NOVA, "csrf_token": proprio},
        )
        assert "Seu papel não permite essa operação." in resposta.text
        assert token  # o token do admin nunca foi usado aqui

    # A senha do B continua a original.
    async with _browser(world) as beta:
        from conftest import REPRESENTATIVE_B_EMAIL

        entrada = await _entrar(beta, REPRESENTATIVE_B_EMAIL, PASSWORD)
        assert "/portal/customers" in str(entrada.url)


@pytest.mark.asyncio
async def test_redefinicao_fica_auditada_com_o_autor(world):
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        pagina = await admin.get("/portal/users")
        await admin.post(
            f"/portal/users/{world.representative_a_id}/password",
            data={"password": NOVA, "csrf_token": _token(pagina.text)},
        )

    async with world.app.state.session_factory() as session:
        registros = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "USER_PASSWORD_RESET")
            )
        ).all()
        assert len(registros) == 1
        assert registros[0].actor_user_id == world.admin_id
        assert registros[0].entity_id == world.representative_a_id


@pytest.mark.asyncio
async def test_troca_propria_alcanca_tambem_o_admin(world):
    """A tela não é só do representante; quem tem alçada também troca a sua."""
    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        pagina = await admin.get("/portal/minha-senha")
        resposta = await admin.post(
            "/portal/minha-senha",
            data={
                "current_password": PASSWORD,
                "new_password": NOVA,
                "confirm_password": NOVA,
                "csrf_token": _token(pagina.text),
            },
        )
        assert "Senha trocada." in resposta.text
