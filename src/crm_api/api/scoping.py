"""Peças comuns às rotas de cadastro comercial.

Concentra a construção do escopo de carteira e a tradução de erros de domínio
para HTTP, de modo que cada rota nova herde as mesmas decisões — em especial a
de responder `404`, e não `403`, para um cliente fora da carteira.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser
from crm_api.core.states import InvalidStateCode
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.services.customer_admin import (
    ContactNotFound,
    CustomerAdminService,
    DefaultLocationRequired,
    DuplicateDocument,
    DuplicateWhatsapp,
    LocationNotFound,
)
from crm_api.services.customers import InvalidWhatsappNumber
from crm_api.services.portfolio import CustomerNotInScope


def scope_for(current_user: CurrentUser, *, only_own: bool = False) -> PortfolioScope:
    return PortfolioScope.for_user(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
        only_own=only_own,
    )


def build_customer_admin_service(session: AsyncSession) -> CustomerAdminService:
    return CustomerAdminService(
        portfolio=CustomerPortfolioRepository(session),
        admin=CustomerAdminRepository(session),
        audit=AuditRepository(session),
    )


@contextmanager
def translated_errors() -> Iterator[None]:
    """Traduz erros de domínio para respostas HTTP."""
    try:
        yield
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="customer not found"
        ) from error
    except ContactNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="contact not found"
        ) from error
    except LocationNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="location not found"
        ) from error
    except DuplicateDocument as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document already used"
        ) from error
    except DuplicateWhatsapp as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="whatsapp already used"
        ) from error
    except (InvalidStateCode, InvalidWhatsappNumber, DefaultLocationRequired) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
