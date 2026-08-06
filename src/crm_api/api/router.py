from fastapi import APIRouter

from crm_api.api.routes import (
    admin_customer_records,
    admin_customers,
    admin_prices,
    admin_users,
    auth,
    customers,
    health,
    interaction_capabilities,
    interactions,
    price_lists,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(interaction_capabilities.router)
api_router.include_router(interactions.router)
api_router.include_router(customers.router)
api_router.include_router(price_lists.router)
api_router.include_router(auth.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_customers.router)
api_router.include_router(admin_customer_records.router)
api_router.include_router(admin_prices.router)
