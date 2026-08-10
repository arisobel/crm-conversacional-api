"""Leitura de número decimal digitado em português.

Vive fora da importação de CSV porque o formulário do portal recebe o mesmo
formato pela tela: quem digita "1.234,56" numa planilha digita igual num campo.
"""

from decimal import Decimal, InvalidOperation


class InvalidDecimal(ValueError):
    """Texto que não descreve um decimal.

    Herda de `ValueError` para que a importação de CSV, que já reportava assim,
    continue com o mesmo contrato de erro na linha de comando.
    """


def parse_decimal(value: str, *, field: str = "value") -> Decimal:
    """Converte "1.234,56" e "1234.56" no mesmo `Decimal`.

    A vírgula decide: quando ela aparece, o ponto é separador de milhar e sai.
    Sem vírgula, o ponto é o separador decimal — que é como o CSV exportado por
    ferramenta em inglês chega.
    """
    try:
        normalized = value.strip()
        if "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        return Decimal(normalized)
    except (AttributeError, InvalidOperation) as error:
        raise InvalidDecimal(f"{field} must be a decimal") from error
