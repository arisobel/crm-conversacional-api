"""Portal server-rendered do representante.

Serve HTML a partir do mesmo processo da API, e não de um app separado, porque
a sessão de R0 usa cookie `httpOnly` `SameSite=Lax`: mesma origem dispensa CORS
com credenciais e evita baixar o cookie para `SameSite=None`. Ver ADR-017.
"""
