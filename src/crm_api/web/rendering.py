"""Renderização e redirecionamento comuns às páginas do portal.

Extraído de `routes.py` quando as telas de campanha entraram: as duas funções
são puras e não têm nada a ver com o cadastro comercial que domina aquele
módulo, e mantê-las lá obrigaria o roteador novo a importar um helper privado
de outro roteador.
"""

from typing import Annotated

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from crm_api.api.authentication import CurrentUser
from crm_api.core.config import Settings
from crm_api.web import messages
from crm_api.web.csrf import attach_csrf_cookie, current_or_new_token
from crm_api.web.dependencies import templates

# Reexportado para que os roteadores declarem campos de formulário opcionais
# sem repetir a anotação.
FormField = Annotated[str | None, None]


def redirect(destino: str, codigo: str | None = None) -> RedirectResponse:
    # 303 força o navegador a trocar o POST por um GET, encerrando o ciclo de
    # reenvio ao atualizar a página.
    if not codigo:
        return RedirectResponse(destino, status_code=303)
    # O destino pode já levar query string própria — a publicação volta para a
    # competência que acabou de publicar.
    separador = "&" if "?" in destino else "?"
    return RedirectResponse(f"{destino}{separador}m={codigo}", status_code=303)


def render(
    request: Request,
    template: str,
    contexto: dict,
    *,
    current_user: CurrentUser | None = None,
    mensagem: str | None = None,
    erro_direto: str | None = None,
    status_code: int = 200,
) -> Response:
    """Renderiza uma página do portal com CSRF e mensagens já resolvidos.

    `erro_direto` existe para o erro que **não** pode virar código na query
    string: quando a mensagem do domínio é a informação útil — "porte ainda não
    é atributo do cliente" — e a página é devolvida na própria resposta do POST,
    sem redirecionamento. Como o texto não viaja pela URL, ele não abre o canal
    de injeção que `messages` evita.
    """
    settings: Settings = request.app.state.settings
    token = current_or_new_token(request)
    aviso, erro = messages.resolve(mensagem)
    resposta = templates.TemplateResponse(
        request,
        template,
        {
            **contexto,
            "current_user": current_user,
            "csrf_token": token,
            "aviso": aviso,
            "erro": erro_direto or erro,
        },
        status_code=status_code,
    )
    attach_csrf_cookie(resposta, token, secure=settings.session_cookie_secure)
    return resposta
