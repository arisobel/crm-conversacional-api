"""Telas de campanha no portal (F6.3).

O que estes testes protegem não é o HTML, é o que a tela **não** pode fazer:

1. Não existe caminho que envie mensagem. A campanha para no rascunho, e a
   palavra "enviado" não aparece para quem só tem rascunho.
2. O rascunho é montado re-resolvendo os critérios. Um POST forjado com
   destinatários de outra carteira não muda o público congelado.
3. O escopo de carteira vale nas três telas — lista, detalhe e ficha do
   cliente — e o erro de campanha alheia é o de campanha inexistente.
4. Formulário sem CSRF não cria nem cancela nada.
"""

import re
from contextlib import asynccontextmanager
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
    persist,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from crm_api.models.catalog import (
    CustomerPreferredProduct,
    ProductGroup,
    ProductGroupMember,
)
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.textile import Fiber, ProductComposition
from crm_api.models.whatsapp_campaign import (
    CampaignStatus,
    WhatsappCampaign,
    WhatsappCampaignRecipient,
)

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    tenant = mundo.tenant_id
    grupo = ProductGroup(
        id=uuid4(),
        tenant_id=tenant,
        name="Poliéster",
        normalized_name="poliester",
    )
    fibra = Fiber(id=uuid4(), tenant_id=tenant, code="PES", name="Poliéster")
    objetos = [
        grupo,
        fibra,
        ProductGroupMember(
            id=uuid4(),
            tenant_id=tenant,
            group_id=grupo.id,
            product_id=mundo.product_id,
        ),
        ProductComposition(
            id=uuid4(),
            tenant_id=tenant,
            product_id=mundo.product_id,
            fiber_id=fibra.id,
            percent=Decimal("92.00"),
        ),
        # O cliente A já prefere o artigo; falta o contato para ele ser elegível.
        CustomerContact(
            id=uuid4(),
            tenant_id=tenant,
            customer_id=mundo.customer_a_id,
            name="Compras Alfa",
            whatsapp_e164="+5511900030001",
            is_primary=True,
        ),
        # O cliente da carteira B, com tudo pronto — para provar que mesmo assim
        # ele não entra na prévia do representante A.
        CustomerContact(
            id=uuid4(),
            tenant_id=tenant,
            customer_id=mundo.customer_b_id,
            name="Compras Beta",
            whatsapp_e164="+5511900030002",
            is_primary=True,
        ),
        CustomerPreferredProduct(
            id=uuid4(),
            tenant_id=tenant,
            customer_id=mundo.customer_b_id,
            product_id=mundo.product_id,
            active=True,
        ),
    ]
    async with mundo.app.state.session_factory() as session:
        await persist(session, objetos)
        await session.commit()

    mundo.__dict__["grupo_id"] = grupo.id
    yield mundo
    await mundo.app.state.engine.dispose()


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


async def _previa(client, world, **campos):
    página = await client.get("/portal/campaigns/nova")
    dados = {
        "csrf_token": _token(página.text),
        "product_group_ids": str(world.grupo_id),
    }
    dados.update(campos)
    return await client.post("/portal/campaigns/previa", data=dados)


async def _criar_rascunho(client, world, *, chave="portal-teste-1", **campos):
    página = await client.get("/portal/campaigns/nova")
    dados = {
        "csrf_token": _token(página.text),
        "product_group_ids": str(world.grupo_id),
        "idempotency_key": chave,
    }
    dados.update(campos)
    return await client.post("/portal/campaigns", data=dados)


async def _contar(world, model) -> int:
    async with world.app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


# ------------------------------------------------------------------- prévia


@pytest.mark.asyncio
async def test_previa_mostra_elegivel_e_nao_grava_nada(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await _previa(client, world)

    assert resposta.status_code == 200
    assert "Alfa Tecelagem" in resposta.text
    # A prévia é leitura: nenhuma campanha nasce dela.
    assert await _contar(world, WhatsappCampaign) == 0


@pytest.mark.asyncio
async def test_previa_nao_mostra_cliente_de_outra_carteira(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await _previa(client, world)

    assert "Beta Malharia" not in resposta.text


@pytest.mark.asyncio
async def test_uf_invalida_aparece_em_portugues(world):
    """O aceite de R6a: erro de domínio na tela em português, nunca a mensagem
    interna. `InvalidStateCode` diz "is not a Brazilian state code" — isso não
    pode chegar ao usuário."""
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        página = await client.get("/portal/campaigns/nova")
        resposta = await client.post(
            "/portal/campaigns/previa",
            data={"csrf_token": _token(página.text), "state_codes": "ZZ"},
        )

    assert resposta.status_code == 422
    assert "UF inválida" in resposta.text
    assert "Brazilian" not in resposta.text


@pytest.mark.asyncio
async def test_eixo_nao_modelado_explica_o_motivo(world):
    """Um eixo que o domínio não modela só chega se alguém forjar o POST — e a
    resposta precisa dizer por quê, não estourar 500 nem devolver lista vazia."""
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        página = await client.get("/portal/campaigns/nova")
        resposta = await client.post(
            "/portal/campaigns/previa",
            data={
                "csrf_token": _token(página.text),
                "product_group_ids": str(uuid4()),
            },
        )

    assert resposta.status_code == 422
    assert "inexistente ou inativo" in resposta.text


@pytest.mark.asyncio
async def test_formulario_vazio_nao_vira_carteira_inteira(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        página = await client.get("/portal/campaigns/nova")
        resposta = await client.post(
            "/portal/campaigns/previa", data={"csrf_token": _token(página.text)}
        )

    assert resposta.status_code == 422
    assert "include_entire_portfolio" in resposta.text


# ----------------------------------------------------------------- rascunho


@pytest.mark.asyncio
async def test_criar_rascunho_congela_o_publico(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await _criar_rascunho(client, world)

    assert resposta.status_code == 200
    # A tela do rascunho não pode sugerir que algo saiu.
    assert "Nada foi enviado" in resposta.text
    assert "DRAFT" in resposta.text

    async with world.app.state.session_factory() as session:
        campanha = await session.scalar(select(WhatsappCampaign))
        assert campanha.status is CampaignStatus.DRAFT
        assert campanha.confirmation is None
        assert campanha.template_snapshot == {"status": "PENDENTE_CATALOGO_GATEWAY"}

        destinos = list(await session.scalars(select(WhatsappCampaignRecipient)))
        assert {d.customer_id for d in destinos} == {world.customer_a_id}


@pytest.mark.asyncio
async def test_destinatario_forjado_no_post_e_ignorado(world):
    """O rascunho é montado re-resolvendo os critérios.

    Mesmo que alguém acrescente campos de destinatário ao formulário, eles não
    são lidos: o público congelado continua sendo o que o resolvedor produziu.
    """
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(
            client,
            world,
            customer_id=str(world.customer_b_id),
            recipients=str(world.customer_b_id),
        )

    async with world.app.state.session_factory() as session:
        destinos = list(await session.scalars(select(WhatsappCampaignRecipient)))
        assert {d.customer_id for d in destinos} == {world.customer_a_id}


@pytest.mark.asyncio
async def test_mesma_chave_nao_cria_duas_campanhas(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(client, world, chave="repetida")
        await _criar_rascunho(client, world, chave="repetida")

    assert await _contar(world, WhatsappCampaign) == 1


@pytest.mark.asyncio
async def test_post_sem_csrf_nao_cria_campanha(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await client.post(
            "/portal/campaigns",
            data={
                "product_group_ids": str(world.grupo_id),
                "idempotency_key": "sem-csrf",
                "csrf_token": "forjado",
            },
        )

    assert await _contar(world, WhatsappCampaign) == 0


@pytest.mark.asyncio
async def test_criterio_aparece_legivel_e_nao_como_uuid(world):
    """Defeito encontrado rodando o app: a tela mostrava
    `product_group_ids: ['1a25b79f-…']`.

    O snapshot continua guardando o id — é ele que precisa continuar verdadeiro
    se alguém renomear o grupo —, mas quem lê a tela vê o rótulo e o nome.
    """
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        detalhe = await _criar_rascunho(client, world)

    # O rótulo vem dentro de <strong>, então o par não é contíguo no HTML.
    assert "Grupos de artigo" in detalhe.text
    assert "Poliéster" in detalhe.text
    assert "product_group_ids" not in detalhe.text
    assert str(world.grupo_id) not in detalhe.text

    # O id continua no snapshot, que é a prova auditável.
    async with world.app.state.session_factory() as session:
        campanha = await session.scalar(select(WhatsappCampaign))
        assert campanha.criteria_snapshot["product_group_ids"] == [str(world.grupo_id)]


# ------------------------------------------------------- escopo das telas


@pytest.mark.asyncio
async def test_representante_nao_abre_campanha_alheia(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(client, world)

    async with world.app.state.session_factory() as session:
        campanha_id = (await session.scalar(select(WhatsappCampaign))).id

    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_B_EMAIL)
        lista = await client.get("/portal/campaigns")
        detalhe = await client.get(f"/portal/campaigns/{campanha_id}")

    assert "Nenhuma campanha" in lista.text
    # Redirecionado para a lista com "não encontrado" — o mesmo desfecho de um
    # id inexistente, para não revelar que a campanha existe.
    assert "Registro não encontrado" in detalhe.text


@pytest.mark.asyncio
async def test_gestao_acompanha_o_tenant(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(client, world)

    async with _browser(world) as client:
        await _entrar(client, ADMIN_EMAIL)
        lista = await client.get("/portal/campaigns")

    assert "1 campanha(s)" in lista.text


@pytest.mark.asyncio
async def test_gestao_ve_mas_nao_cancela_rascunho_alheio(world):
    """Ler o tenant inteiro é uma coisa; desfazer o trabalho de outro é a
    alçada que a F6.0 ainda não decidiu."""
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(client, world)

    async with world.app.state.session_factory() as session:
        campanha_id = (await session.scalar(select(WhatsappCampaign))).id

    async with _browser(world) as client:
        await _entrar(client, ADMIN_EMAIL)
        detalhe = await client.get(f"/portal/campaigns/{campanha_id}")
        assert "Cancelar rascunho" not in detalhe.text

        await client.post(
            f"/portal/campaigns/{campanha_id}/cancelar",
            data={"csrf_token": _token(detalhe.text)},
        )

    async with world.app.state.session_factory() as session:
        campanha = await session.get(WhatsappCampaign, campanha_id)
        assert campanha.status is CampaignStatus.DRAFT


# ------------------------------------------------------------ cancelamento


@pytest.mark.asyncio
async def test_dona_cancela_o_proprio_rascunho(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(client, world)

        async with world.app.state.session_factory() as session:
            campanha_id = (await session.scalar(select(WhatsappCampaign))).id

        detalhe = await client.get(f"/portal/campaigns/{campanha_id}")
        resposta = await client.post(
            f"/portal/campaigns/{campanha_id}/cancelar",
            data={"csrf_token": _token(detalhe.text)},
        )

    assert "cancelada" in resposta.text.lower()
    async with world.app.state.session_factory() as session:
        campanha = await session.get(WhatsappCampaign, campanha_id)
        assert campanha.status is CampaignStatus.CANCELLED


# ------------------------------------------------------------ ficha do cliente


@pytest.mark.asyncio
async def test_campanha_aparece_na_ficha_do_cliente(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        await _criar_rascunho(client, world)
        ficha = await client.get(f"/portal/customers/{world.customer_a_id}")

    assert "Campanhas" in ficha.text
    assert "Abrir campanha" in ficha.text


@pytest.mark.asyncio
async def test_ficha_de_cliente_sem_campanha_diz_isso(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        ficha = await client.get(f"/portal/customers/{world.customer_a_id}")

    assert "não participou de nenhuma campanha" in ficha.text
