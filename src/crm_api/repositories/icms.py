import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.tax import IcmsRule


class IcmsRuleRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def candidates(
        self,
        *,
        tenant_id: uuid.UUID,
        origin_state: str,
        destination_state: str,
        product_id: uuid.UUID | None,
        family_id: uuid.UUID | None,
        customer_id: uuid.UUID | None,
        at: date,
    ) -> list[IcmsRule]:
        """Regras aplicáveis ao caso, sem escolher entre elas.

        O banco filtra o que é aplicável; a escolha por especificidade fica no
        serviço, onde o empate pode virar erro explícito em vez de um
        `ORDER BY ... LIMIT 1` que decidiria em silêncio.
        """
        statement = select(IcmsRule).where(
            IcmsRule.tenant_id == tenant_id,
            IcmsRule.origin_state == origin_state,
            IcmsRule.destination_state == destination_state,
            IcmsRule.active.is_(True),
            IcmsRule.valid_from <= at,
            or_(IcmsRule.valid_until.is_(None), IcmsRule.valid_until > at),
            # Uma regra especializada só entra se a especialização casar; a
            # regra genérica (coluna nula) sempre entra.
            or_(IcmsRule.product_id.is_(None), IcmsRule.product_id == product_id),
            or_(IcmsRule.family_id.is_(None), IcmsRule.family_id == family_id),
            or_(IcmsRule.customer_id.is_(None), IcmsRule.customer_id == customer_id),
        )
        return list(await self._session.scalars(statement))

    async def list_rules(
        self, tenant_id: uuid.UUID, *, active: bool | None = None
    ) -> list[IcmsRule]:
        statement = select(IcmsRule).where(IcmsRule.tenant_id == tenant_id)
        if active is not None:
            statement = statement.where(IcmsRule.active.is_(active))
        return list(
            await self._session.scalars(
                statement.order_by(
                    IcmsRule.origin_state,
                    IcmsRule.destination_state,
                    IcmsRule.valid_from.desc(),
                )
            )
        )

    def add(self, rule: IcmsRule) -> None:
        self._session.add(rule)
