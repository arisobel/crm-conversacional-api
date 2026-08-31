"""Confere, contra um PostgreSQL real, o que só as migrações constroem.

A suíte exercita `Base.metadata`. As migrações constroem outra coisa — e é a
outra coisa que roda em produção, porque o `docker-entrypoint.sh` chama
`alembic upgrade head` no start. Nada, até aqui, comparava as duas.

Este script fecha esse buraco em três frentes:

1. **Estrutura.** As invariantes da `0014` existem no banco migrado, e com a
   forma declarada: o `CHECK` do percentual, a UNIQUE por
   `(product_id, fiber_id)` e o `ON DELETE CASCADE` do artigo. São as três
   coisas de que o serviço depende sem checar.

2. **Criabilidade.** `Base.metadata.create_all` roda sem erro no PostgreSQL.
   Parece óbvio; não era. Até a fatia 1.5 o modelo de `customers` carregava um
   `CHECK` com `GLOB`, operador que só o SQLite entende, e a suíte inteira
   validava um esquema impossível de criar em produção.

3. **Acordo.** O `CHECK` de UF que o modelo cria e o que a migração criou são
   textualmente iguais, comparados por `pg_get_constraintdef`. O nome diverge
   de propósito — a `0001` deixou o `CHECK` sem nome e o PostgreSQL batizou de
   `customers_state_code_check`, enquanto o modelo chama de `ck_customers_state`
   —, então a comparação é por texto e por tabela, nunca por nome.

Uso:

    CRM_DATABASE_URL=postgresql+asyncpg://...           # onde rodou o upgrade
    CRM_METADATA_DATABASE_URL=postgresql+asyncpg://...  # banco descartável
    python ops/ci/check_pg_schema.py

Imprime todos os veredictos e sai com 1 se algum falhar.
"""

import asyncio
import os
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RAIZ / "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from crm_api.models.base import Base  # noqa: E402
from crm_api.models.catalog import Product, ProductFamily  # noqa: E402, F401
from crm_api.models.customer import Customer, Tenant  # noqa: E402, F401
from crm_api.models.customer_contact import CustomerContact  # noqa: E402, F401
from crm_api.models.customer_intake import CustomerIntake  # noqa: E402, F401
from crm_api.models.interaction import CustomerInteraction  # noqa: E402, F401
from crm_api.models.pricing import PriceList, PriceListItem  # noqa: E402, F401
from crm_api.models.tax import IcmsRule  # noqa: E402, F401
from crm_api.models.textile import Fiber, ProductComposition  # noqa: E402, F401
from crm_api.models.user import User  # noqa: E402, F401

# O texto que a `0001` produziu no banco de produção. Está aqui como âncora: se
# um dia um dos dois lados mudar, o job cai dizendo qual deles saiu do lugar.
UF_ESPERADA = "CHECK ((state_code ~ '^[A-Z]{2}$'::text))"

_CHECK_DE_UF = text(
    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
    "WHERE c.conrelid = 'customers'::regclass AND c.contype = 'c' "
    "AND pg_get_constraintdef(c.oid) LIKE '%state_code%'"
)

_INDICES_DA_COMPOSICAO = [
    "ix_product_compositions_fiber",
    "ix_product_compositions_product",
    "product_compositions_pkey",
    "ux_product_composition",
]


class Relatorio:
    """Acumula os veredictos para que a saída mostre todos, não só o primeiro."""

    def __init__(self) -> None:
        self.falhas = 0

    def afirma(self, descricao: str, condicao: bool, observado: object = None) -> None:
        if condicao:
            print(f"  ok    {descricao}")
            return
        self.falhas += 1
        print(f"  FALHA {descricao}")
        if observado is not None:
            print(f"        observado: {observado!r}")


async def _confere_estrutura(url: str, relatorio: Relatorio) -> str:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conexao:
            versao = await conexao.scalar(text("SHOW server_version"))
            revisao = await conexao.scalar(text("SELECT version_num FROM alembic_version"))
            print(f"\nBanco migrado — PostgreSQL {versao}, alembic_version={revisao}")

            relatorio.afirma(
                "a cabeça migrada é a 0014",
                revisao == "0014_product_compositions",
                revisao,
            )

            percentual = await conexao.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_product_composition_percent' "
                    "AND conrelid = 'product_compositions'::regclass"
                )
            )
            relatorio.afirma(
                "ck_product_composition_percent existe em product_compositions",
                percentual is not None,
                percentual,
            )
            if percentual:
                print(f"        {percentual}")

            unica = await conexao.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ux_product_composition' "
                    "AND conrelid = 'product_compositions'::regclass AND contype = 'u'"
                )
            )
            relatorio.afirma(
                "ux_product_composition é UNIQUE em (product_id, fiber_id)",
                unica == "UNIQUE (product_id, fiber_id)",
                unica,
            )

            cascata = await conexao.scalar(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "WHERE c.conrelid = 'product_compositions'::regclass AND c.contype = 'f' "
                    "AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute "
                    "WHERE attrelid = 'product_compositions'::regclass "
                    "AND attname = 'product_id')]::smallint[]"
                )
            )
            relatorio.afirma(
                "a FK de product_id apaga em cascata com o artigo",
                cascata is not None and "ON DELETE CASCADE" in cascata,
                cascata,
            )
            if cascata:
                print(f"        {cascata}")

            indices = sorted(
                (
                    await conexao.scalars(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE tablename = 'product_compositions'"
                        )
                    )
                ).all()
            )
            relatorio.afirma(
                "os índices de product_compositions são os quatro declarados",
                indices == _INDICES_DA_COMPOSICAO,
                indices,
            )

            uf = await conexao.scalar(_CHECK_DE_UF)
            relatorio.afirma("o CHECK de UF migrado é o da 0001", uf == UF_ESPERADA, uf)
            print(f"        migração: {uf}")
            return uf or ""
    finally:
        await engine.dispose()


async def _confere_modelo(url: str, uf_migrada: str, relatorio: Relatorio) -> None:
    engine = create_async_engine(url)
    try:
        print("\nEsquema criado a partir de Base.metadata")
        async with engine.begin() as conexao:
            await conexao.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conexao.exec_driver_sql("CREATE SCHEMA public")
            await conexao.run_sync(Base.metadata.create_all)
        relatorio.afirma(
            f"create_all criou as {len(Base.metadata.tables)} tabelas sem erro", True
        )

        async with engine.connect() as conexao:
            uf = await conexao.scalar(_CHECK_DE_UF)
            print(f"        modelo:   {uf}")
            relatorio.afirma("o CHECK de UF do modelo é o texto da 0001", uf == UF_ESPERADA, uf)
            relatorio.afirma(
                "modelo e migração dizem a mesma coisa sobre a UF", uf == uf_migrada, uf
            )
    finally:
        await engine.dispose()


async def _principal() -> int:
    migrado = os.environ.get("CRM_DATABASE_URL")
    metadados = os.environ.get("CRM_METADATA_DATABASE_URL")
    if not migrado or not metadados:
        print("defina CRM_DATABASE_URL e CRM_METADATA_DATABASE_URL", file=sys.stderr)
        return 2

    relatorio = Relatorio()
    uf_migrada = await _confere_estrutura(migrado, relatorio)
    await _confere_modelo(metadados, uf_migrada, relatorio)

    print()
    if relatorio.falhas:
        print(f"{relatorio.falhas} verificação(ões) falharam")
        return 1
    print("esquema migrado e modelo conferem")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_principal()))
