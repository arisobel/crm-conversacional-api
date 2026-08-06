"""Resolução do ICMS e conversão de preço entre UFs.

Ver ADR-015. Duas regras que valem mais que qualquer conveniência:

1. **Ausência de regra é erro.** Não existe alíquota-padrão implícita — assumir
   uma produziria um preço plausível e errado, que é pior do que nenhum.
2. **Empate é erro.** Duas regras igualmente específicas e vigentes param o
   cálculo em vez de deixá-lo escolher uma delas em silêncio.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from crm_api.models.tax import IcmsRule
from crm_api.repositories.icms import IcmsRuleRepository

_CEM = Decimal("100")
_QUATRO_CASAS = Decimal("0.0001")


class ConversionMode(StrEnum):
    """Como o imposto se relaciona com o preço.

    `INSIDE` é o ICMS "por dentro": o imposto compõe a própria base, convenção
    brasileira. `OUTSIDE` o trata como acréscimo sobre o líquido. A escolha é de
    natureza fiscal e está pendente de confirmação contábil (Q1/Q2).
    """

    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"


class OriginNotConfigured(Exception):
    """O tenant não tem UF de origem; sem ela não há par para resolver."""


class IcmsRuleNotFound(Exception):
    """Nenhuma regra cobre este par de UFs na data de referência."""


class AmbiguousIcmsRule(Exception):
    """Mais de uma regra igualmente específica; a escolha não pode ser tácita."""


class InvalidTaxRate(Exception):
    """Alíquota que tornaria a conversão indefinida."""


@dataclass(frozen=True)
class IcmsResolution:
    rule_id: uuid.UUID
    tax_rate: Decimal
    origin_state: str
    destination_state: str
    specificity: int


@dataclass(frozen=True)
class ConvertedPrice:
    base_price: Decimal
    final_price: Decimal
    tax_rate: Decimal
    trace: dict


class IcmsResolver:
    def __init__(self, repository: IcmsRuleRepository) -> None:
        self._repository = repository

    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        origin_state: str | None,
        destination_state: str,
        product_id: uuid.UUID | None = None,
        family_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        at: date,
    ) -> IcmsResolution:
        if not origin_state:
            raise OriginNotConfigured(
                "configure a UF de origem do tenant antes de calcular ICMS"
            )

        candidatas = await self._repository.candidates(
            tenant_id=tenant_id,
            origin_state=origin_state,
            destination_state=destination_state,
            product_id=product_id,
            family_id=family_id,
            customer_id=customer_id,
            at=at,
        )
        if not candidatas:
            raise IcmsRuleNotFound(
                f"nenhuma regra de ICMS para {origin_state}->{destination_state} em {at}"
            )

        maior = max(regra.especificidade for regra in candidatas)
        no_topo = [regra for regra in candidatas if regra.especificidade == maior]

        if len(no_topo) > 1:
            no_topo = self._desempatar(no_topo)
        if len(no_topo) > 1:
            raise AmbiguousIcmsRule(
                f"{len(no_topo)} regras igualmente específicas para "
                f"{origin_state}->{destination_state} em {at}; ajuste prioridade ou vigência"
            )

        escolhida = no_topo[0]
        return IcmsResolution(
            rule_id=escolhida.id,
            tax_rate=escolhida.tax_rate,
            origin_state=origin_state,
            destination_state=destination_state,
            specificity=maior,
        )

    @staticmethod
    def _desempatar(regras: list[IcmsRule]) -> list[IcmsRule]:
        """Maior prioridade; entre iguais, a vigência mais recente."""
        maior_prioridade = max(regra.priority for regra in regras)
        restantes = [regra for regra in regras if regra.priority == maior_prioridade]
        if len(restantes) == 1:
            return restantes
        vigencia_recente = max(regra.valid_from for regra in restantes)
        return [regra for regra in restantes if regra.valid_from == vigencia_recente]


def convert_price(
    *,
    base_price: Decimal,
    base_tax_rate: Decimal | None,
    resolution: IcmsResolution,
    mode: ConversionMode,
) -> ConvertedPrice:
    """Converte o preço-base para a UF de destino.

    O `base_tax_rate` é o ICMS **já embutido** no preço-base. Ele é removido
    antes de aplicar a alíquota de destino; sem essa etapa o imposto seria
    cobrado duas vezes. Quando é nulo, o preço-base é tratado como líquido.
    """
    origem = (base_tax_rate or Decimal("0")) / _CEM
    destino = resolution.tax_rate / _CEM

    if mode is ConversionMode.INSIDE:
        if destino >= 1 or origem >= 1:
            raise InvalidTaxRate("alíquota de 100% torna o cálculo por dentro indefinido")
        liquido = base_price * (Decimal("1") - origem)
        final = liquido / (Decimal("1") - destino)
    else:
        liquido = base_price / (Decimal("1") + origem)
        final = liquido * (Decimal("1") + destino)

    final = final.quantize(_QUATRO_CASAS, rounding=ROUND_HALF_UP)
    return ConvertedPrice(
        base_price=base_price,
        final_price=final,
        tax_rate=resolution.tax_rate,
        trace={
            "mode": mode.value,
            "rule_id": str(resolution.rule_id),
            "specificity": resolution.specificity,
            "origin_state": resolution.origin_state,
            "destination_state": resolution.destination_state,
            "base_price": str(base_price),
            "base_tax_rate": str(base_tax_rate) if base_tax_rate is not None else None,
            "destination_tax_rate": str(resolution.tax_rate),
            "net_price": str(liquido.quantize(_QUATRO_CASAS, rounding=ROUND_HALF_UP)),
            "final_price": str(final),
        },
    )
