"""Conversa entre representante e cliente, registrada à mão na ficha.

O que estes testes protegem, em ordem de importância:

1. A forma nova é **aceita** — `customer_id` e `actor_user_id` juntos, que o
   `CHECK` da `0010` recusava.
2. As duas formas antigas continuam **exatamente como eram**. Se a `0012` tiver
   afrouxado a garantia de dono, é aqui que aparece.
3. Só nota é editável. Evento de canal continua imutável.
4. Escopo de carteira e autoria valem também na correção.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crm_api.models.interaction import (
    GATEWAY_SOURCE,
    PORTAL_SOURCE,
    CustomerInteraction,
    InteractionDirection,
    InteractionKind,
)
from crm_api.models.user import AuditLog, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.services.interactions import (
    EmptyNote,
    InteractionService,
    NotEditable,
    NoteNotFound,
    NoteNotOwned,
    UnknownNoteChannel,
)
from crm_api.services.portfolio import CustomerNotInScope


@pytest_asyncio.fixture
async def world():
    return await build_portal_world()


def _service(session) -> InteractionService:
    return InteractionService(
        session=session,
        interactions=InteractionRepository(session),
        portfolio=CustomerPortfolioRepository(session),
        audit=AuditRepository(session),
    )


def _scope(world, user_id=None) -> PortfolioScope:
    return PortfolioScope(tenant_id=world.tenant_id, owner_user_id=user_id)


# ------------------------------------------------------- a forma que faltava


@pytest.mark.asyncio
async def test_nota_grava_cliente_e_autor_na_mesma_linha(world):
    """O caso central: o `CHECK` da `0010` recusava exatamente esta linha."""
    async with world.app.state.session_factory() as session:
        nota = await _service(session).register_note(
            scope=_scope(world, world.representative_a_id),
            customer_id=world.customer_a_id,
            author_user_id=world.representative_a_id,
            summary="Liguei; pediu cotação de 75/36 cru para agosto.",
            channel="PHONE",
            direction=InteractionDirection.OUTBOUND,
        )
        await session.commit()

        assert nota.kind is InteractionKind.REPRESENTATIVE_NOTE
        assert nota.customer_id == world.customer_a_id
        assert nota.actor_user_id == world.representative_a_id
        assert nota.source == PORTAL_SOURCE
        # A nota é a própria origem: não há sistema externo a referenciar.
        assert nota.external_ref == str(nota.id)


@pytest.mark.asyncio
async def test_nota_aparece_na_timeline_do_cliente(world):
    async with world.app.state.session_factory() as session:
        servico = _service(session)
        await servico.register_note(
            scope=_scope(world, world.representative_a_id),
            customer_id=world.customer_a_id,
            author_user_id=world.representative_a_id,
            summary="Visita na fábrica.",
            channel="VISIT",
            direction=None,
        )
        await session.commit()

        linhas, total = await servico.timeline(
            _scope(world, world.representative_a_id),
            world.customer_a_id,
            limit=20,
            offset=0,
        )
        assert total == 1
        assert linhas[0].summary == "Visita na fábrica."


@pytest.mark.asyncio
async def test_visita_pode_nao_ter_sentido(world):
    """"Visitei o cliente" não é recebida nem enviada, e não deve ser forçada."""
    async with world.app.state.session_factory() as session:
        nota = await _service(session).register_note(
            scope=_scope(world, world.representative_a_id),
            customer_id=world.customer_a_id,
            author_user_id=world.representative_a_id,
            summary="Passei na fábrica, conversamos sobre volume.",
            channel="VISIT",
            direction=None,
        )
        await session.commit()
        assert nota.direction is None


# ------------------------------------- as formas antigas continuam guardadas


@pytest.mark.asyncio
async def test_evento_de_canal_sem_dono_continua_recusado_pelo_banco(world):
    """A `0012` não pode ter virado "pelo menos um dono"."""
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerInteraction(
                id=uuid4(),
                tenant_id=world.tenant_id,
                kind=InteractionKind.CUSTOMER_CHANNEL,
                customer_id=None,
                actor_user_id=None,
                direction=InteractionDirection.INBOUND,
                source=GATEWAY_SOURCE,
                external_ref="wamid.orfao",
                occurred_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_conversa_de_representante_com_o_robo_nao_ganha_cliente(world):
    """O caso que a `0010` protegeu: "bom dia" ao robô não é de cliente nenhum."""
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerInteraction(
                id=uuid4(),
                tenant_id=world.tenant_id,
                kind=InteractionKind.ACTOR_CHANNEL,
                customer_id=world.customer_a_id,
                actor_user_id=world.representative_a_id,
                direction=InteractionDirection.INBOUND,
                source=GATEWAY_SOURCE,
                external_ref="wamid.misturado",
                occurred_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_evento_de_canal_exige_sentido(world):
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerInteraction(
                id=uuid4(),
                tenant_id=world.tenant_id,
                kind=InteractionKind.CUSTOMER_CHANNEL,
                customer_id=world.customer_a_id,
                direction=None,
                source=GATEWAY_SOURCE,
                external_ref="wamid.sem-sentido",
                occurred_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


# ------------------------------------------------------------------- escopo


@pytest.mark.asyncio
async def test_representante_nao_registra_nota_em_carteira_alheia(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(CustomerNotInScope):
            await _service(session).register_note(
                scope=_scope(world, world.representative_a_id),
                customer_id=world.customer_b_id,
                author_user_id=world.representative_a_id,
                summary="Não deveria entrar.",
                channel="PHONE",
                direction=None,
            )


@pytest.mark.asyncio
async def test_nota_vazia_e_recusada(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(EmptyNote):
            await _service(session).register_note(
                scope=_scope(world, world.representative_a_id),
                customer_id=world.customer_a_id,
                author_user_id=world.representative_a_id,
                summary="   \n  ",
                channel="PHONE",
                direction=None,
            )


@pytest.mark.asyncio
async def test_meio_fora_da_lista_e_recusado(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(UnknownNoteChannel):
            await _service(session).register_note(
                scope=_scope(world, world.representative_a_id),
                customer_id=world.customer_a_id,
                author_user_id=world.representative_a_id,
                summary="Pombo-correio.",
                channel="PIGEON",
                direction=None,
            )


# ------------------------------------------------------------------- edição


async def _nota_de(session, world, *, autor=None, cliente=None):
    nota = await _service(session).register_note(
        scope=_scope(world),
        customer_id=cliente or world.customer_a_id,
        author_user_id=autor or world.representative_a_id,
        summary="Texto original.",
        channel="PHONE",
        direction=InteractionDirection.OUTBOUND,
    )
    await session.commit()
    return nota


@pytest.mark.asyncio
async def test_autor_corrige_a_propria_nota_e_a_versao_anterior_fica_na_auditoria(world):
    async with world.app.state.session_factory() as session:
        nota = await _nota_de(session, world)

        corrigida = await _service(session).edit_note(
            scope=_scope(world, world.representative_a_id),
            note_id=nota.id,
            editor_user_id=world.representative_a_id,
            editor_role=UserRole.REPRESENTATIVE,
            summary="Texto corrigido.",
        )
        await session.commit()

        assert corrigida.summary == "Texto corrigido."
        assert corrigida.edited_at is not None

        trilha = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "INTERACTION_NOTE_EDITED")
            )
        ).all()
        assert len(trilha) == 1
        assert trilha[0].before == {"summary": "Texto original."}
        assert trilha[0].after == {"summary": "Texto corrigido."}
        assert trilha[0].actor_user_id == world.representative_a_id


@pytest.mark.asyncio
async def test_evento_de_canal_nao_pode_ser_reescrito(world):
    """A exceção da imutabilidade vale só para nota, e o serviço garante isso."""
    async with world.app.state.session_factory() as session:
        evento = CustomerInteraction(
            id=uuid4(),
            tenant_id=world.tenant_id,
            kind=InteractionKind.CUSTOMER_CHANNEL,
            customer_id=world.customer_a_id,
            direction=InteractionDirection.INBOUND,
            source=GATEWAY_SOURCE,
            external_ref="wamid.do-cliente",
            occurred_at=datetime.now(UTC),
            summary="Tem 75/36 cru?",
        )
        session.add(evento)
        await session.commit()

        with pytest.raises(NotEditable):
            await _service(session).edit_note(
                scope=_scope(world),
                note_id=evento.id,
                editor_user_id=world.admin_id,
                editor_role=UserRole.ADMIN,
                summary="O cliente nunca disse isso.",
            )


@pytest.mark.asyncio
async def test_representante_nao_reescreve_nota_de_outro(world):
    async with world.app.state.session_factory() as session:
        # Nota escrita pelo B, sobre um cliente que passa a ser do A.
        nota = await _nota_de(session, world, autor=world.representative_b_id)

        with pytest.raises(NoteNotOwned):
            await _service(session).edit_note(
                scope=_scope(world, world.representative_a_id),
                note_id=nota.id,
                editor_user_id=world.representative_a_id,
                editor_role=UserRole.REPRESENTATIVE,
                summary="Reescrevendo o relato alheio.",
            )


@pytest.mark.asyncio
async def test_gestao_corrige_nota_de_qualquer_um(world):
    async with world.app.state.session_factory() as session:
        nota = await _nota_de(session, world, autor=world.representative_b_id)

        corrigida = await _service(session).edit_note(
            scope=_scope(world),
            note_id=nota.id,
            editor_user_id=world.admin_id,
            editor_role=UserRole.ADMIN,
            summary="Corrigido pela gestão.",
        )
        await session.commit()
        assert corrigida.summary == "Corrigido pela gestão."


@pytest.mark.asyncio
async def test_correcao_respeita_escopo_de_carteira(world):
    """Perder a titularidade tira o alcance do histórico junto."""
    async with world.app.state.session_factory() as session:
        nota = await _nota_de(session, world, cliente=world.customer_b_id,
                              autor=world.representative_a_id)

        with pytest.raises(CustomerNotInScope):
            await _service(session).edit_note(
                scope=_scope(world, world.representative_a_id),
                note_id=nota.id,
                editor_user_id=world.representative_a_id,
                editor_role=UserRole.REPRESENTATIVE,
                summary="Fora da carteira.",
            )


@pytest.mark.asyncio
async def test_nota_inexistente(world):
    async with world.app.state.session_factory() as session:
        with pytest.raises(NoteNotFound):
            await _service(session).edit_note(
                scope=_scope(world),
                note_id=uuid4(),
                editor_user_id=world.admin_id,
                editor_role=UserRole.ADMIN,
                summary="Nada aqui.",
            )


@pytest.mark.asyncio
async def test_correcao_vazia_nao_apaga_a_nota(world):
    async with world.app.state.session_factory() as session:
        nota = await _nota_de(session, world)

        with pytest.raises(EmptyNote):
            await _service(session).edit_note(
                scope=_scope(world),
                note_id=nota.id,
                editor_user_id=world.admin_id,
                editor_role=UserRole.ADMIN,
                summary="  ",
            )


# ------------------------------------------------------- convivência na ficha


@pytest.mark.asyncio
async def test_nota_e_evento_de_canal_convivem_na_mesma_timeline(world):
    """A ficha é uma linha do tempo só, com as duas origens em ordem."""
    agora = datetime.now(UTC)
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerInteraction(
                id=uuid4(),
                tenant_id=world.tenant_id,
                kind=InteractionKind.CUSTOMER_CHANNEL,
                customer_id=world.customer_a_id,
                direction=InteractionDirection.INBOUND,
                source=GATEWAY_SOURCE,
                external_ref="wamid.antigo",
                occurred_at=agora - timedelta(hours=2),
                summary="Mensagem pelo WhatsApp.",
            )
        )
        await session.commit()

        servico = _service(session)
        await servico.register_note(
            scope=_scope(world),
            customer_id=world.customer_a_id,
            author_user_id=world.representative_a_id,
            summary="Liguei depois da mensagem.",
            channel="PHONE",
            direction=InteractionDirection.OUTBOUND,
        )
        await session.commit()

        linhas, total = await servico.timeline(
            _scope(world), world.customer_a_id, limit=20, offset=0
        )
        assert total == 2
        # Mais recente primeiro: a nota, depois o evento de canal.
        assert linhas[0].kind is InteractionKind.REPRESENTATIVE_NOTE
        assert linhas[1].kind is InteractionKind.CUSTOMER_CHANNEL
