"""Importação revisável da composição por fibra.

Mesma disciplina do ADR-009 aplicada ao cadastro descritivo: a planilha entra,
o que não fecha é **reportado e não gravado**, e o resto do lote continua. A
diferença para `price_table` é que aqui não há lote em rascunho a publicar —
composição não é valor comercial, e não existe estado intermediário entre
cadastrada e não cadastrada.

Casa o artigo por **SKU**, que é a chave estável entre competências (ADR-021), e
a fibra pela sigla do setor.

Formato, separador `;`:

    sku;fiber_code;percent
    PUE-75-36-CRU;PES;100
    PV-30-1;PES;65
    PV-30-1;CV;35

Uma linha por fibra; o artigo é montado agrupando as linhas do mesmo SKU. Um
artigo cuja soma não fecha 100 é recusado **inteiro** — gravar metade da
composição seria pior do que não gravar nada, porque a consulta por percentual
passaria a mentir.
"""

import argparse
import asyncio
import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.core.config import get_settings
from crm_api.core.database import create_session_factory
from crm_api.models.customer import Tenant
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.textile import TextileRepository
from crm_api.services.textile import (
    CompositionDoesNotSumToHundred,
    DuplicateFiberInComposition,
    InvalidPercent,
    TextileService,
    UnknownFiber,
)

_COLUNAS = {"sku", "fiber_code", "percent"}


@dataclass
class CompositionImportResult:
    """O que entrou e o que ficou de fora, artigo a artigo.

    As recusas não abortam o lote: uma planilha de cem artigos não pode ser
    perdida porque três linhas têm sigla errada. Quem roda vê a lista e corrige
    só essas.
    """

    applied: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def report(self) -> str:
        linhas = [f"{len(self.applied)} artigo(s) com composição gravada"]
        if self.rejected:
            linhas.append(f"{len(self.rejected)} recusado(s):")
            linhas.extend(f"  {sku}  {motivo}" for sku, motivo in self.rejected)
        return "\n".join(linhas)


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    if not rows or set(rows[0]) != _COLUNAS:
        raise ValueError("CSV columns do not match the documented composition template")
    return rows


def _percent(value: str) -> Decimal:
    try:
        return Decimal(value.strip().replace(",", "."))
    except (InvalidOperation, AttributeError) as error:
        raise ValueError(f"percent is not a number: {value!r}") from error


def _group_by_sku(rows: list[dict[str, str]]) -> dict[str, list[tuple[str, Decimal]]]:
    """Agrupa as linhas do mesmo artigo, preservando a ordem de aparição.

    Uma linha ilegível derruba só o artigo dela: o valor sentinela mantém o SKU
    na lista para que ele seja recusado com motivo, em vez de sumir em silêncio.
    """
    por_sku: dict[str, list[tuple[str, Decimal]]] = {}
    for row in rows:
        sku = row["sku"].strip()
        if not sku:
            continue
        try:
            percent = _percent(row["percent"])
        except ValueError as error:
            por_sku.setdefault(sku, [])
            por_sku[sku].append((f"!{error}", Decimal("0")))
            continue
        por_sku.setdefault(sku, []).append((row["fiber_code"].strip().upper(), percent))
    return por_sku


async def import_compositions(
    session: AsyncSession, *, tenant_slug: str, source_path: Path
) -> CompositionImportResult:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.slug == tenant_slug, Tenant.active.is_(True))
    )
    if tenant is None:
        raise ValueError(f"active tenant not found: {tenant_slug}")

    repositorio = TextileRepository(session)
    servico = TextileService(textile=repositorio, audit=AuditRepository(session))
    resultado = CompositionImportResult()

    for sku, shares in _group_by_sku(_load_rows(source_path)).items():
        ilegivel = next((code for code, _ in shares if code.startswith("!")), None)
        if ilegivel is not None:
            resultado.rejected.append((sku, ilegivel[1:]))
            continue

        artigo = await repositorio.get_product_by_sku(tenant.id, sku)
        if artigo is None:
            resultado.rejected.append((sku, "SKU não encontrado no catálogo"))
            continue

        try:
            # Savepoint por artigo, como na ingestão de interações: uma recusa
            # do banco não pode invalidar a transação e derrubar o que já entrou.
            async with session.begin_nested():
                await servico.set_composition(
                    tenant_id=tenant.id, product_id=artigo.id, shares=shares
                )
        except CompositionDoesNotSumToHundred as error:
            resultado.rejected.append((sku, f"soma {error.total}%, esperado 100%"))
        except UnknownFiber as error:
            resultado.rejected.append((sku, f"fibra desconhecida: {error.code}"))
        except DuplicateFiberInComposition as error:
            resultado.rejected.append((sku, f"fibra repetida: {error.code}"))
        except InvalidPercent as error:
            resultado.rejected.append(
                (sku, f"percentual inválido em {error.code}: {error.percent}")
            )
        else:
            resultado.applied.append(sku)

    return resultado


async def _run(source_path: Path) -> int:
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    try:
        async with session_factory() as session:
            resultado = await import_compositions(
                session, tenant_slug=settings.tenant_slug, source_path=source_path
            )
            await session.commit()
            print(resultado.report())
            return 0 if not resultado.rejected else 1
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crm-import-compositions")
    parser.add_argument("--file", required=True, type=Path)
    arguments = parser.parse_args(argv)
    return asyncio.run(_run(arguments.file))


if __name__ == "__main__":
    raise SystemExit(main())
