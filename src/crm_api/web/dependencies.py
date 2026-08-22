"""Sessão e renderização das páginas do portal.

As rotas do portal devolvem HTML, então não podem reaproveitar o tratamento de
erro da API: um 401 aqui precisa virar redirecionamento para o login, e não um
`application/problem+json` que o navegador exibiria como texto cru.
"""

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, build_auth_service
from crm_api.core.config import Settings
from crm_api.core.database import get_session

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# O canal é gravado em maiúsculas porque o Gateway grava assim e a coluna é
# compartilhada. Traduzir na exibição evita ter que escolher entre um banco
# legível e um banco compatível.
_ROTULOS_DE_MEIO = {
    "WHATSAPP": "WhatsApp",
    "PHONE": "Telefone",
    "VISIT": "Visita",
    "EMAIL": "E-mail",
    "OTHER": "Outro",
}


def rotulo_meio(canal: str | None) -> str:
    """Nome do meio para leitura humana; desconhecido passa como veio."""
    return _ROTULOS_DE_MEIO.get(canal or "", canal or "—")


templates.env.globals["rotulo_meio"] = rotulo_meio

LOGIN_PATH = "/portal/login"


class PortalRedirect(Exception):
    """Sinaliza que a página pedida deve virar um redirecionamento."""

    def __init__(self, location: str, *, clear_session: bool = False) -> None:
        self.location = location
        self.clear_session = clear_session
        super().__init__(location)


async def portal_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentUser:
    """Igual ao `get_current_user`, mas redireciona em vez de responder 401."""
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise PortalRedirect(LOGIN_PATH)

    service = build_auth_service(request, session)
    resolved = await service.resolve(token)
    # `resolve` pode revogar a sessão ou renovar a janela; ambos precisam ser
    # persistidos mesmo quando a página termina em redirecionamento.
    await session.commit()
    if resolved is None:
        raise PortalRedirect(f"{LOGIN_PATH}?expirada=1", clear_session=True)

    user_session, user = resolved
    return CurrentUser(
        session_id=user_session.id,
        user_id=user.id,
        tenant_id=user.tenant_id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
    )
