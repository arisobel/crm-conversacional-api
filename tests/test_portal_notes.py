"""Registro de conversa pela ficha do cliente, pelo navegador.

`test_representative_notes.py` cobre as regras no serviço. Aqui a pergunta é
outra: o formulário chega, o CSRF vale, a nota aparece na página e a recusa
volta como mensagem legível em vez de erro cru.
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


async def _entrar(client, email: str):
    page = await client.get("/portal/login")
    return await client.post(
        "/portal/login",
        data={"email": email, "password": PASSWORD, "csrf_token": _token(page.text)},
    )


async def _ficha(client, customer_id):
    return await client.get(f"/portal/customers/{customer_id}")


@pytest.mark.asyncio
async def test_representante_registra_conversa_e_ela_aparece_na_ficha(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await _ficha(client, world.customer_a_id)

        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/notas",
            data={
                "summary": "Liguei; pediu cotação de 75/36 cru.",
                "channel": "PHONE",
                "direction": "OUTBOUND",
                "csrf_token": _token(pagina.text),
            },
        )

        assert resposta.status_code == 200
        assert "Conversa registrada no histórico." in resposta.text
        assert "Liguei; pediu cotação de 75/36 cru." in resposta.text
        assert "registro manual" in resposta.text


@pytest.mark.asyncio
async def test_visita_sem_sentido_e_aceita_pelo_formulario(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await _ficha(client, world.customer_a_id)

        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/notas",
            data={
                "summary": "Visita na fábrica.",
                "channel": "VISIT",
                # O `<select>` manda string vazia quando "não se aplica".
                "direction": "",
                "csrf_token": _token(pagina.text),
            },
        )
        assert "Conversa registrada no histórico." in resposta.text
        assert "Visita na fábrica." in resposta.text


@pytest.mark.asyncio
async def test_nota_vazia_volta_como_mensagem_e_nao_como_erro(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await _ficha(client, world.customer_a_id)

        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/notas",
            data={
                "summary": "   ",
                "channel": "PHONE",
                "direction": "",
                "csrf_token": _token(pagina.text),
            },
        )
        assert resposta.status_code == 200
        assert "Escreva o que aconteceu antes de registrar." in resposta.text


@pytest.mark.asyncio
async def test_sem_csrf_a_nota_nao_entra(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)

        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/notas",
            data={
                "summary": "Deveria ser barrada.",
                "channel": "PHONE",
                "direction": "",
                "csrf_token": "token-de-outro-lugar",
            },
        )
        assert "O formulário expirou." in resposta.text
        assert "Deveria ser barrada." not in resposta.text


@pytest.mark.asyncio
async def test_representante_corrige_a_propria_nota_pela_ficha(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await _ficha(client, world.customer_a_id)
        token = _token(pagina.text)

        await client.post(
            f"/portal/customers/{world.customer_a_id}/notas",
            data={
                "summary": "Texto com erro de digitaçãoo.",
                "channel": "PHONE",
                "direction": "OUTBOUND",
                "csrf_token": token,
            },
        )

        ficha = await _ficha(client, world.customer_a_id)
        # A ficha oferece a correção porque o autor é quem está logado.
        assert "Corrigir" in ficha.text
        nota_id = re.search(
            rf'/portal/customers/{world.customer_a_id}/notas/([0-9a-f-]{{36}})', ficha.text
        )
        assert nota_id, "a ficha não ofereceu o formulário de correção"

        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/notas/{nota_id.group(1)}",
            data={"summary": "Texto corrigido.", "csrf_token": _token(ficha.text)},
        )
        assert "Nota corrigida." in resposta.text
        assert "Texto corrigido." in resposta.text
        assert "editada" in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_alcanca_ficha_de_carteira_alheia(world):
    """A rota de nota não pode ser um atalho para fora da carteira."""
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        # Pega um token válido na própria ficha e tenta usá-lo na alheia.
        pagina = await _ficha(client, world.customer_a_id)

        resposta = await client.post(
            f"/portal/customers/{world.customer_b_id}/notas",
            data={
                "summary": "Cliente de outro representante.",
                "channel": "PHONE",
                "direction": "",
                "csrf_token": _token(pagina.text),
            },
        )
        assert "Cliente de outro representante." not in resposta.text


@pytest.mark.asyncio
async def test_gestao_ve_e_corrige_nota_de_representante(world):
    async with _browser(world) as representante:
        await _entrar(representante, REPRESENTATIVE_A_EMAIL)
        pagina = await _ficha(representante, world.customer_a_id)
        await representante.post(
            f"/portal/customers/{world.customer_a_id}/notas",
            data={
                "summary": "Relato do representante.",
                "channel": "PHONE",
                "direction": "INBOUND",
                "csrf_token": _token(pagina.text),
            },
        )

    async with _browser(world) as gestao:
        await _entrar(gestao, ADMIN_EMAIL)
        ficha = await _ficha(gestao, world.customer_a_id)
        assert "Relato do representante." in ficha.text
        assert "Corrigir" in ficha.text
