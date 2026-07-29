from fastapi import APIRouter

from crm_api.api.routes import customers, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(customers.router)

