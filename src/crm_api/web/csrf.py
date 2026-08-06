"""Proteção CSRF por double-submit cookie.

O cookie de sessão é `SameSite=Lax`, o que já impede um POST vindo de outro site
de carregar a sessão da vítima. Este token é a segunda camada, e é o que cobre o
formulário de login — onde ainda não existe sessão para o `Lax` proteger.

Não exige armazenamento: o valor vive em um cookie próprio e é repetido em um
campo oculto do formulário. Um site terceiro consegue provocar o envio do
formulário, mas não consegue ler o cookie para preencher o campo.
"""

import hmac
import secrets

from fastapi import Request, Response

CSRF_COOKIE_NAME = "crm_csrf"
CSRF_FIELD_NAME = "csrf_token"
_TOKEN_BYTES = 32


def current_or_new_token(request: Request) -> str:
    """Token desta requisição; criado quando o cookie ainda não existe.

    Separado de `attach_csrf_cookie` porque o token precisa entrar no contexto
    antes da renderização, e o cookie só pode ser definido depois, na resposta.
    """
    return request.cookies.get(CSRF_COOKIE_NAME) or secrets.token_urlsafe(_TOKEN_BYTES)


def attach_csrf_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def csrf_is_valid(request: Request, submitted: str | None) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token or not submitted:
        return False
    return hmac.compare_digest(cookie_token, submitted)
