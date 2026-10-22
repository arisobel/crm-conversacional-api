import unittest
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crm_api.models.assistant_settings import (
    AssistantOrganizationSettings,
    AssistantRepresentativeCapability,
    AssistantRepresentativeSettings,
)
from crm_api.models.customer import Tenant
from crm_api.models.user import User, UserRole
from crm_api.repositories.assistant_settings import get_assistant_policy


class AssistantStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")

        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as connection:
            for model in (Tenant, User, AssistantOrganizationSettings,
                          AssistantRepresentativeSettings, AssistantRepresentativeCapability):
                await connection.run_sync(model.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tenant_a, self.tenant_b, self.user = uuid4(), uuid4(), uuid4()
        async with self.sessions() as session:
            session.add_all([Tenant(id=self.tenant_a, name="A", slug="a"),
                             Tenant(id=self.tenant_b, name="B", slug="b")])
            await session.flush()
            session.add(User(id=self.user, tenant_id=self.tenant_a, full_name="Rep",
                             email="r@example.com", password_hash="hash",
                             role=UserRole.REPRESENTATIVE))
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_defaults_and_scoped_capabilities(self):
        async with self.sessions() as session:
            self.assertFalse((await get_assistant_policy(session, self.tenant_a, self.user)).allows(
                "CRM_REP_SEARCH_PRICE_ITEMS"))
            org = AssistantOrganizationSettings(tenant_id=self.tenant_a)
            rep = AssistantRepresentativeSettings(tenant_id=self.tenant_a, user_id=self.user)
            session.add_all([org, rep])
            await session.flush()
            self.assertFalse(org.enabled)
            self.assertFalse(rep.enabled)
            org.enabled = rep.enabled = True
            session.add(AssistantRepresentativeCapability(
                tenant_id=self.tenant_a, user_id=self.user,
                capability_id="CRM_REP_SEARCH_PRICE_ITEMS"))
            await session.commit()
            policy = await get_assistant_policy(session, self.tenant_a, self.user)
            self.assertTrue(policy.allows("CRM_REP_SEARCH_PRICE_ITEMS"))
            self.assertFalse(policy.allows("CRM_REP_LOOKUP_CUSTOMER"))
            self.assertFalse((await get_assistant_policy(session, self.tenant_b, self.user)).allows(
                "CRM_REP_SEARCH_PRICE_ITEMS"))

    async def test_database_rejects_user_from_another_tenant(self):
        async with self.sessions() as session:
            session.add(AssistantRepresentativeSettings(tenant_id=self.tenant_b, user_id=self.user))
            with self.assertRaises(IntegrityError):
                await session.commit()

    async def test_inactive_user_is_denied(self):
        async with self.sessions() as session:
            session.add_all([AssistantOrganizationSettings(tenant_id=self.tenant_a, enabled=True),
                             AssistantRepresentativeSettings(tenant_id=self.tenant_a, user_id=self.user, enabled=True)])
            await session.commit()
            user = await session.get(User, self.user)
            user.active = False
            await session.commit()
            self.assertEqual((await get_assistant_policy(session, self.tenant_a, self.user)).effective_capabilities(), frozenset())
