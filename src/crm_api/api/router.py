from fastapi import APIRouter

from crm_api.api.routes import customers, health, interaction_capabilities, price_lists

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(interaction_capabilities.router)
api_router.include_router(customers.router)
api_router.include_router(price_lists.router)
