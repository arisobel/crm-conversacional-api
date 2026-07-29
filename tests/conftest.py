import os

os.environ.setdefault("CRM_DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("CRM_TENANT_SLUG", "test-tenant")
os.environ.setdefault("CRM_INTERNAL_HMAC_SECRET", "test-secret")
