"""Hashing e política de senha do portal.

Argon2id com os parâmetros padrão do `argon2-cffi`. O hash nunca sai daqui em
log, resposta ou mensagem de erro.
"""

from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import Argon2Error, InvalidHashError

_MAX_PASSWORD_LENGTH = 128

# Senhas óbvias que passariam na regra de comprimento e composição.
_FORBIDDEN = frozenset(
    {
        "123456789012",
        "senha123456789",
        "password1234",
        "administrador1",
        "qwerty123456",
    }
)


class WeakPassword(ValueError):
    """A senha proposta não atende à política mínima."""


@lru_cache
def _hasher() -> PasswordHasher:
    return PasswordHasher(type=Type.ID)


@lru_cache
def dummy_hash() -> str:
    """Hash descartável usado para equalizar o tempo de um login sem usuário.

    Sem ele, responder mais rápido quando o e-mail não existe transforma o
    endpoint de login em um oráculo de enumeração de usuários.
    """
    return _hasher().hash("dummy-password-for-constant-time-login")


def validate_password_policy(password: str, *, email: str, min_length: int) -> None:
    if len(password) < min_length:
        raise WeakPassword(f"password must have at least {min_length} characters")
    if len(password) > _MAX_PASSWORD_LENGTH:
        raise WeakPassword(f"password must have at most {_MAX_PASSWORD_LENGTH} characters")
    if not any(character.isalpha() for character in password):
        raise WeakPassword("password must contain at least one letter")
    if not any(character.isdigit() for character in password):
        raise WeakPassword("password must contain at least one digit")
    if password.lower() in _FORBIDDEN:
        raise WeakPassword("password is too common")

    local_part = email.split("@", 1)[0].strip().lower()
    if local_part and local_part in password.lower():
        raise WeakPassword("password must not contain the email address")


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher().check_needs_rehash(password_hash)
    except (Argon2Error, InvalidHashError):
        return False
