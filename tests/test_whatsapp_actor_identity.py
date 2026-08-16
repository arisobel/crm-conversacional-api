"""Identidade do ator no WhatsApp: telefone canônico e apelido público.

Primeira etapa do manifesto por ator. O que está sob teste aqui é o que hoje
falha em silêncio: um representante cadastrado sem o nono dígito nunca seria
reconhecido, e a tela mostraria o cadastro correto.
"""

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from conftest import ADMIN_EMAIL, PASSWORD, build_portal_world, login
from httpx import ASGITransport, AsyncClient

from crm_api.core.identifiers import is_public_ref, new_public_ref
from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.models.user import UserRole


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _client(world, email: str | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        if email is not None:
            await login(client, email=email)
        yield client


@pytest_asyncio.fixture
async def admin(world):
    async with _client(world, ADMIN_EMAIL) as client:
        yield client


def _new_user(**overrides) -> dict:
    payload = {
        "full_name": "Representante Novo",
        "email": "novo@teste.com.br",
        "password": PASSWORD,
        "role": UserRole.REPRESENTATIVE.value,
    }
    payload.update(overrides)
    return payload


def test_apelido_publico_tem_o_formato_que_o_gateway_exige():
    """`^[a-f0-9]{24}$` não é preferência de estilo: é o validador do Gateway."""
    assert all(is_public_ref(new_public_ref()) for _ in range(50))


def test_apelidos_nao_se_repetem():
    assert len({new_public_ref() for _ in range(1_000)}) == 1_000


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("+551188887777", "+5511988887777"),  # celular antigo ganha o nono dígito
        ("+5511988887777", "+5511988887777"),  # já canônico, não muda
        ("+551133334444", "+551133334444"),  # fixo começa em 3: fica intacto
        ("+55 (11) 98888-7777", "+5511988887777"),  # apresentação é limpa
        ("+12125551234", "+12125551234"),  # fora do +55 nada é inferido
    ],
)
def test_canonizacao_de_telefone(entrada: str, esperado: str):
    assert normalize_whatsapp_e164(entrada) == esperado


def test_numero_fora_do_e164_nao_passa_pela_canonizacao():
    with pytest.raises(InvalidWhatsappNumber):
        normalize_whatsapp_e164("11988887777")


@pytest.mark.asyncio
async def test_usuario_criado_sem_nono_digito_e_gravado_canonico(admin):
    """O defeito que motivou esta etapa.

    Antes, `+551188887777` era aceito como está e jamais casaria com o
    `+5511988887777` que a Meta entrega.
    """
    response = await admin.post(
        "/admin/users", json=_new_user(whatsapp_e164="+551188887777")
    )
    assert response.status_code == 201
    assert response.json()["whatsapp_e164"] == "+5511988887777"


@pytest.mark.asyncio
async def test_dois_usuarios_nao_dividem_o_mesmo_telefone(admin):
    primeiro = await admin.post(
        "/admin/users",
        json=_new_user(email="primeira@teste.com.br", whatsapp_e164="+5511988887777"),
    )
    # A segunda tentativa usa a grafia antiga do mesmo assinante: só é recusada
    # porque a canonização acontece antes da checagem.
    segundo = await admin.post(
        "/admin/users",
        json=_new_user(email="segundo@teste.com.br", whatsapp_e164="+551188887777"),
    )
    assert primeiro.status_code == 201
    assert segundo.status_code == 409


@pytest.mark.asyncio
async def test_telefone_de_contato_de_cliente_nao_vira_usuario(world, admin):
    """A colisão é a rota de escalação mais barata do desenho.

    Um telefone que fosse contato de cliente e usuário do portal receberia
    capacidades de representante por um cadastro descuidado.
    """
    contato = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Compradora", "whatsapp_e164": "+5511977776666"},
    )
    assert contato.status_code == 201

    conflito = await admin.post(
        "/admin/users",
        json=_new_user(email="conflito@teste.com.br", whatsapp_e164="+5511977776666"),
    )
    assert conflito.status_code == 409
    assert "customer contact" in conflito.json()["detail"]


@pytest.mark.asyncio
async def test_telefone_invalido_e_recusado_com_422(admin):
    response = await admin.post("/admin/users", json=_new_user(whatsapp_e164="+5511"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_atualizar_mantendo_o_proprio_telefone_nao_colide_consigo(admin):
    criado = await admin.post(
        "/admin/users", json=_new_user(whatsapp_e164="+5511966665555")
    )
    user_id = criado.json()["user_id"]

    response = await admin.patch(f"/admin/users/{user_id}", json={"whatsapp_e164": "+551166665555"})
    assert response.status_code == 200
    assert response.json()["whatsapp_e164"] == "+5511966665555"
