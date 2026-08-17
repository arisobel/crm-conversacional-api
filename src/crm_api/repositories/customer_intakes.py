"""Leitura e escrita da fila de pré-cadastros.

O escopo é aplicado **aqui**, como no `CustomerPortfolioRepository`: um
representante alcança apenas os pré-cadastros que ele abriu. Filtrar na rota
deixaria a próxima rota livre para esquecer.
"""

import uuid
from contextlib import AbstractAsyncContextManager

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer_intake import CustomerIntake, IntakeStatus
from crm_api.models.user import User


class CustomerIntakeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, entity: CustomerIntake) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()

    def savepoint(self) -> AbstractAsyncContextManager:
        """`SAVEPOINT` para isolar uma inserção que pode colidir.

        Sem ele, a violação de unicidade aborta a transação inteira e não sobra
        sessão utilizável para reler a linha que venceu a corrida.
        """
        return self._session.begin_nested()

    async def by_idempotency_key(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> CustomerIntake | None:
        """O pré-cadastro já aberto por esta mensagem, se houver.

        Devolve o registro em qualquer estado, inclusive resolvido: uma reentrega
        do webhook depois de alguém aceitar não pode abrir um segundo.
        """
        return await self._session.scalar(
            select(CustomerIntake).where(
                CustomerIntake.tenant_id == tenant_id,
                CustomerIntake.idempotency_key == idempotency_key,
            )
        )

    async def get(self, tenant_id: uuid.UUID, intake_id: uuid.UUID) -> CustomerIntake | None:
        return await self._session.scalar(
            select(CustomerIntake).where(
                CustomerIntake.tenant_id == tenant_id, CustomerIntake.id == intake_id
            )
        )

    def _scoped(
        self,
        tenant_id: uuid.UUID,
        *,
        author_user_id: uuid.UUID | None,
        status: IntakeStatus | None,
    ) -> Select:
        statement = select(CustomerIntake).where(CustomerIntake.tenant_id == tenant_id)
        if author_user_id is not None:
            statement = statement.where(CustomerIntake.created_by_user_id == author_user_id)
        if status is not None:
            statement = statement.where(CustomerIntake.status == status)
        return statement

    async def count(
        self,
        tenant_id: uuid.UUID,
        *,
        author_user_id: uuid.UUID | None = None,
        status: IntakeStatus | None = None,
    ) -> int:
        statement = self._scoped(tenant_id, author_user_id=author_user_id, status=status)
        return await self._session.scalar(
            select(func.count()).select_from(statement.subquery())
        ) or 0

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        author_user_id: uuid.UUID | None = None,
        status: IntakeStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[CustomerIntake, User]]:
        """Pré-cadastros com o autor já carregado.

        O autor vem no mesmo `SELECT` porque a fila mostra quem abriu em toda
        linha, e um `lazy load` por linha viraria N+1 na tela mais movimentada
        deste fluxo.
        """
        statement = (
            self._scoped(tenant_id, author_user_id=author_user_id, status=status)
            .join(User, User.id == CustomerIntake.created_by_user_id)
            .add_columns(User)
            .order_by(CustomerIntake.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(intake, author) for intake, author in await self._session.execute(statement)]
