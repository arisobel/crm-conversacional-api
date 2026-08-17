"""Casamento de termos de busca de artigo.

O caso que motivou o descarte de ruído veio do resolvedor genérico do Gateway:
com a mensagem "quanto está o PUE 20", ele preenche o slot com `o PUE 20`. Como
o casamento exige **todos** os termos, o artigo sozinho fazia a busca não
encontrar um produto que existe — e a resposta ao cliente era "não encontrei".
"""

from uuid import uuid4

import pytest

from crm_api.schemas.price_lists import CurrentPriceListItemResponse
from crm_api.services.product_search import matches_search_terms, search_tokens


def _item(**overrides) -> CurrentPriceListItemResponse:
    base = {
        "product_id": uuid4(),
        "family_name": "Poliamida",
        "sku": "PUE-20",
        "display_name": "PUE 20 texturizado",
        "specification": None,
        "unit": "KG",
        "availability": "AVAILABLE",
        "base_price": None,
        "expected_arrival_date": None,
        "arrival_note": None,
        "notes": None,
    }
    base.update(overrides)
    return CurrentPriceListItemResponse(**base)


@pytest.mark.parametrize(
    ("termo", "esperado"),
    [
        ("PUE 20", ["pue", "20"]),
        ("o PUE 20", ["pue", "20"]),
        ("preço do PUE", ["preco", "pue"]),
        ("fio de seda", ["fio", "seda"]),
        ("75/36", ["75", "36"]),
    ],
)
def test_ruido_gramatical_sai_dos_termos(termo: str, esperado: list[str]):
    assert search_tokens(termo) == esperado


def test_termo_feito_so_de_ruido_e_preservado():
    """Descartar tudo viraria busca vazia, que casaria com o catálogo inteiro."""
    assert search_tokens("de") == ["de"]
    assert search_tokens("o a") == ["o", "a"]


def test_artigo_no_comeco_nao_impede_o_casamento():
    item = _item()
    assert matches_search_terms(item, search_tokens("o PUE 20")) is True
    assert matches_search_terms(item, search_tokens("PUE 20")) is True


def test_termo_que_nao_existe_continua_nao_casando():
    """O descarte de ruído não pode virar casamento frouxo."""
    item = _item()
    assert matches_search_terms(item, search_tokens("poliéster")) is False
    assert matches_search_terms(item, search_tokens("PUE 30")) is False


def test_busca_por_codigo_atravessa_a_pontuacao():
    item = _item(sku="TEX-75-36-CRU", display_name="75/36 trama cru")
    assert matches_search_terms(item, search_tokens("75/36")) is True
    assert matches_search_terms(item, search_tokens("75 36")) is True


def test_acento_nao_impede_o_casamento():
    item = _item(display_name="Fio poliéster texturizado")
    assert matches_search_terms(item, search_tokens("poliester")) is True
    assert matches_search_terms(item, search_tokens("poliéster")) is True
