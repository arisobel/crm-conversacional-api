"""Composição do artigo por fibra — a primeira fatia da camada têxtil.

O que estes testes prendem, em ordem de importância:

1. **Ausência não é negativa.** Artigo sem composição nunca some de uma busca
   por fibra: ele volta num conjunto separado. Se algum dia alguém "otimizar"
   isso, cadastro incompleto vira resposta errada com cara de certa.
2. A composição é um conjunto que fecha 100%, e uma recusa não deixa o artigo
   sem a composição que ele já tinha.
3. A camada é aditiva: `products` e `price_entries` não mudam, e a busca de
   artigo que já existia continua igual.
"""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from sqlalchemy import func, select

from crm_api.imports.composition import import_compositions
from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.customer import Tenant
from crm_api.models.textile import Fiber, ProductComposition
from crm_api.models.user import AuditLog
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.textile import TextileRepository
from crm_api.services.textile import (
    SEED_FIBERS,
    CompositionDoesNotSumToHundred,
    DuplicateFiberInComposition,
    InvalidPercent,
    ProductNotFound,
    TextileService,
    UnknownFiber,
)


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


def _service(session) -> TextileService:
    return TextileService(
        textile=TextileRepository(session), audit=AuditRepository(session)
    )


async def _semear(world) -> None:
    async with world.app.state.session_factory() as session:
        await _service(session).seed_fibers(tenant_id=world.tenant_id)
        await session.commit()


async def _artigo_extra(world, sku: str = "PV-30-1") -> object:
    """Segundo artigo, para separar o classificado do não classificado."""
    async with world.app.state.session_factory() as session:
        familia = await session.scalar(select(ProductFamily))
        produto = Product(
            id=uuid4(),
            tenant_id=world.tenant_id,
            family_id=familia.id,
            sku=sku,
            commercial_name=f"Artigo {sku}",
        )
        session.add(produto)
        await session.commit()
        return produto.id


async def _compor(world, product_id, shares):
    async with world.app.state.session_factory() as session:
        resultado = await _service(session).set_composition(
            tenant_id=world.tenant_id, product_id=product_id, shares=shares
        )
        await session.commit()
        return resultado


async def _linhas(world) -> list[ProductComposition]:
    async with world.app.state.session_factory() as session:
        return list(await session.scalars(select(ProductComposition)))


# ------------------------------------------------------------------- o seed


@pytest.mark.asyncio
async def test_seed_cadastra_as_fibras_do_setor(world):
    async with world.app.state.session_factory() as session:
        criadas = await _service(session).seed_fibers(tenant_id=world.tenant_id)
        await session.commit()

    assert len(criadas) == len(SEED_FIBERS)
    async with world.app.state.session_factory() as session:
        fibras = list(await session.scalars(select(Fiber)))
    assert {f.code for f in fibras} == {code for code, _ in SEED_FIBERS}
    assert next(f.name for f in fibras if f.code == "PES") == "Poliéster"


@pytest.mark.asyncio
async def test_seed_e_idempotente(world):
    await _semear(world)
    async with world.app.state.session_factory() as session:
        segunda = await _service(session).seed_fibers(tenant_id=world.tenant_id)
        await session.commit()

    assert segunda == []
    async with world.app.state.session_factory() as session:
        assert await session.scalar(select(func.count(Fiber.id))) == len(SEED_FIBERS)


@pytest.mark.asyncio
async def test_seed_nao_sobrescreve_nome_corrigido_a_mao(world):
    """O seed semeia, não normaliza."""
    await _semear(world)
    async with world.app.state.session_factory() as session:
        fibra = await session.scalar(select(Fiber).where(Fiber.code == "PES"))
        fibra.name = "Poliéster (PET)"
        await session.commit()

    async with world.app.state.session_factory() as session:
        await _service(session).seed_fibers(tenant_id=world.tenant_id)
        await session.commit()
        fibra = await session.scalar(select(Fiber).where(Fiber.code == "PES"))
        assert fibra.name == "Poliéster (PET)"


# ------------------------------------------------------- gravar a composição


@pytest.mark.asyncio
async def test_composicao_de_uma_fibra_so(world):
    await _semear(world)
    resultado = await _compor(world, world.product_id, [("PES", Decimal("100"))])

    assert [(s.fiber.code, s.percent) for s in resultado] == [("PES", Decimal("100"))]
    assert len(await _linhas(world)) == 1


@pytest.mark.asyncio
async def test_composicao_multivalorada(world):
    """`PV 30/1 65PES/35CV` — o caso que motivou a tabela."""
    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("65")), ("CV", Decimal("35"))])

    linhas = await _linhas(world)
    assert len(linhas) == 2
    assert sum(linha.percent for linha in linhas) == Decimal("100")


@pytest.mark.asyncio
async def test_soma_diferente_de_cem_e_recusada(world):
    await _semear(world)
    with pytest.raises(CompositionDoesNotSumToHundred) as erro:
        await _compor(world, world.product_id, [("PES", Decimal("65")), ("CV", Decimal("30"))])

    assert erro.value.total == Decimal("95")
    assert await _linhas(world) == []


@pytest.mark.asyncio
async def test_recusa_nao_apaga_a_composicao_anterior(world):
    """Valida antes de apagar: uma recusa não pode deixar o artigo pior."""
    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])

    with pytest.raises(CompositionDoesNotSumToHundred):
        await _compor(world, world.product_id, [("PES", Decimal("50"))])

    linhas = await _linhas(world)
    assert len(linhas) == 1
    assert linhas[0].percent == Decimal("100")


@pytest.mark.asyncio
async def test_fibra_desconhecida_e_recusada(world):
    await _semear(world)
    with pytest.raises(UnknownFiber) as erro:
        await _compor(world, world.product_id, [("XPTO", Decimal("100"))])

    assert erro.value.code == "XPTO"
    assert await _linhas(world) == []


@pytest.mark.asyncio
async def test_fibra_repetida_e_recusada(world):
    await _semear(world)
    with pytest.raises(DuplicateFiberInComposition):
        await _compor(
            world, world.product_id, [("PES", Decimal("50")), ("pes", Decimal("50"))]
        )


@pytest.mark.asyncio
async def test_percentual_fora_da_faixa_e_recusado(world):
    await _semear(world)
    with pytest.raises(InvalidPercent):
        await _compor(
            world, world.product_id, [("PES", Decimal("120")), ("CV", Decimal("-20"))]
        )


@pytest.mark.asyncio
async def test_artigo_inexistente_e_recusado(world):
    await _semear(world)
    with pytest.raises(ProductNotFound):
        await _compor(world, uuid4(), [("PES", Decimal("100"))])


@pytest.mark.asyncio
async def test_substituir_composicao_nao_deixa_orfao(world):
    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("65")), ("CV", Decimal("35"))])
    await _compor(world, world.product_id, [("PES", Decimal("100"))])

    linhas = await _linhas(world)
    assert len(linhas) == 1
    assert linhas[0].percent == Decimal("100")


@pytest.mark.asyncio
async def test_lista_vazia_limpa_a_composicao(world):
    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])
    await _compor(world, world.product_id, [])

    assert await _linhas(world) == []


@pytest.mark.asyncio
async def test_gravacao_fica_auditada_com_antes_e_depois(world):
    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])
    await _compor(world, world.product_id, [("PES", Decimal("65")), ("CV", Decimal("35"))])

    async with world.app.state.session_factory() as session:
        registros = list(
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "PRODUCT_COMPOSITION_SET")
            )
        )
    assert len(registros) == 2
    assert registros[0].before is None
    assert registros[1].before == {"composition": [{"code": "PES", "percent": "100.00"}]}


# ------------------------------------------- ausência não é negativa (dec. 3)


@pytest.mark.asyncio
async def test_artigo_sem_composicao_nao_some_da_busca_por_fibra(world):
    """A regra mais importante desta fatia.

    Devolver só os confirmados transformaria cadastro incompleto em resposta
    errada: "não temos poliéster" quando o certo é "ninguém cadastrou ainda".
    """
    await _semear(world)
    sem_cadastro = await _artigo_extra(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])

    async with world.app.state.session_factory() as session:
        resultado = await _service(session).products_by_fiber(
            tenant_id=world.tenant_id, fiber_code="PES"
        )

    assert [p.id for p, _ in resultado.confirmed] == [world.product_id]
    assert [p.id for p in resultado.unclassified] == [sem_cadastro]


@pytest.mark.asyncio
async def test_filtro_por_percentual_minimo(world):
    await _semear(world)
    outro = await _artigo_extra(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])
    await _compor(world, outro, [("PES", Decimal("30")), ("CV", Decimal("70"))])

    async with world.app.state.session_factory() as session:
        resultado = await _service(session).products_by_fiber(
            tenant_id=world.tenant_id, fiber_code="PES", min_percent=Decimal("60")
        )

    assert [p.id for p, _ in resultado.confirmed] == [world.product_id]
    # O de 30% tem composição cadastrada: ele foi filtrado, não é desconhecido.
    assert resultado.unclassified == []


@pytest.mark.asyncio
async def test_busca_por_fibra_desconhecida_falha_explicitamente(world):
    await _semear(world)
    async with world.app.state.session_factory() as session:
        with pytest.raises(UnknownFiber):
            await _service(session).products_by_fiber(
                tenant_id=world.tenant_id, fiber_code="XPTO"
            )


# ------------------------------------------------------------- isolamento


@pytest.mark.asyncio
async def test_composicao_e_isolada_por_tenant(world):
    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])

    async with world.app.state.session_factory() as session:
        vizinho = Tenant(id=uuid4(), name="Outro", slug="outro-tenant")
        session.add(vizinho)
        await session.commit()

        servico = _service(session)
        await servico.seed_fibers(tenant_id=vizinho.id)
        await session.commit()

        resultado = await servico.products_by_fiber(
            tenant_id=vizinho.id, fiber_code="PES"
        )

    assert resultado.confirmed == []
    assert resultado.unclassified == []


@pytest.mark.asyncio
async def test_fibra_de_outro_tenant_nao_serve_para_compor(world):
    async with world.app.state.session_factory() as session:
        vizinho = Tenant(id=uuid4(), name="Outro", slug="outro-tenant")
        session.add(vizinho)
        await session.commit()
        await _service(session).seed_fibers(tenant_id=vizinho.id)
        await session.commit()

    # O tenant do cenário não semeou nada; a fibra do vizinho não vale aqui.
    with pytest.raises(UnknownFiber):
        await _compor(world, world.product_id, [("PES", Decimal("100"))])


# ---------------------------------------------------------------- o CSV


def _csv(tmp_path: Path, conteudo: str) -> Path:
    caminho = tmp_path / "composicao.csv"
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


@pytest.mark.asyncio
async def test_csv_grava_composicao_agrupando_por_sku(world, tmp_path):
    await _semear(world)
    await _artigo_extra(world)
    arquivo = _csv(
        tmp_path,
        "sku;fiber_code;percent\n"
        "TEX-75-36-CRU;PES;100\n"
        "PV-30-1;PES;65\n"
        "PV-30-1;CV;35\n",
    )

    async with world.app.state.session_factory() as session:
        resultado = await import_compositions(
            session, tenant_slug="test-tenant", source_path=arquivo
        )
        await session.commit()

    assert sorted(resultado.applied) == ["PV-30-1", "TEX-75-36-CRU"]
    assert resultado.rejected == []
    assert len(await _linhas(world)) == 3


@pytest.mark.asyncio
async def test_csv_com_sku_inexistente_e_reportado_sem_abortar(world, tmp_path):
    await _semear(world)
    arquivo = _csv(
        tmp_path,
        "sku;fiber_code;percent\n"
        "TEX-75-36-CRU;PES;100\n"
        "NAO-EXISTE;PES;100\n",
    )

    async with world.app.state.session_factory() as session:
        resultado = await import_compositions(
            session, tenant_slug="test-tenant", source_path=arquivo
        )
        await session.commit()

    assert resultado.applied == ["TEX-75-36-CRU"]
    assert resultado.rejected == [("NAO-EXISTE", "SKU não encontrado no catálogo")]
    assert len(await _linhas(world)) == 1


@pytest.mark.asyncio
async def test_csv_recusa_o_artigo_cuja_soma_nao_fecha_e_mantem_os_outros(world, tmp_path):
    await _semear(world)
    await _artigo_extra(world)
    arquivo = _csv(
        tmp_path,
        "sku;fiber_code;percent\n"
        "TEX-75-36-CRU;PES;100\n"
        "PV-30-1;PES;65\n"
        "PV-30-1;CV;30\n",
    )

    async with world.app.state.session_factory() as session:
        resultado = await import_compositions(
            session, tenant_slug="test-tenant", source_path=arquivo
        )
        await session.commit()

    assert resultado.applied == ["TEX-75-36-CRU"]
    assert resultado.rejected == [("PV-30-1", "soma 95%, esperado 100%")]
    # Recusado inteiro: nem a linha de 65% entra.
    assert len(await _linhas(world)) == 1


@pytest.mark.asyncio
async def test_csv_com_fibra_desconhecida_e_reportado(world, tmp_path):
    await _semear(world)
    arquivo = _csv(tmp_path, "sku;fiber_code;percent\nTEX-75-36-CRU;XPTO;100\n")

    async with world.app.state.session_factory() as session:
        resultado = await import_compositions(
            session, tenant_slug="test-tenant", source_path=arquivo
        )
        await session.commit()

    assert resultado.rejected == [("TEX-75-36-CRU", "fibra desconhecida: XPTO")]
    assert await _linhas(world) == []


@pytest.mark.asyncio
async def test_csv_com_percentual_ilegivel_e_reportado(world, tmp_path):
    await _semear(world)
    arquivo = _csv(tmp_path, "sku;fiber_code;percent\nTEX-75-36-CRU;PES;cem\n")

    async with world.app.state.session_factory() as session:
        resultado = await import_compositions(
            session, tenant_slug="test-tenant", source_path=arquivo
        )
        await session.commit()

    assert len(resultado.rejected) == 1
    assert "não" not in resultado.rejected[0][1]  # é erro de número, não de SKU
    assert await _linhas(world) == []


@pytest.mark.asyncio
async def test_csv_com_cabecalho_errado_falha_cedo(world, tmp_path):
    arquivo = _csv(tmp_path, "sku;fibra;pct\nTEX-75-36-CRU;PES;100\n")
    async with world.app.state.session_factory() as session:
        with pytest.raises(ValueError):
            await import_compositions(
                session, tenant_slug="test-tenant", source_path=arquivo
            )


# ------------------------------------------------------- a camada é aditiva


@pytest.mark.asyncio
async def test_compor_nao_altera_o_artigo(world):
    """`products` não é tocado: a camada é aditiva (ADR-027)."""
    async with world.app.state.session_factory() as session:
        antes = await session.get(Product, world.product_id)
        instantaneo = (antes.sku, antes.commercial_name, antes.family_id, antes.updated_at)

    await _semear(world)
    await _compor(world, world.product_id, [("PES", Decimal("100"))])

    async with world.app.state.session_factory() as session:
        depois = await session.get(Product, world.product_id)
        assert (
            depois.sku,
            depois.commercial_name,
            depois.family_id,
            depois.updated_at,
        ) == instantaneo
