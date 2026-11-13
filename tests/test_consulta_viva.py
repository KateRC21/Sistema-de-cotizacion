"""Consultas reales. Se excluyen del pytest normal; hay que pedirlas con -m red."""

import pytest

from tools.cliente_http import ClienteCatalogo, hoy_bogota
from tools.jumbo import consultar_jumbo
from tools.superboom import consultar_superboom

pytestmark = pytest.mark.red


def _cliente() -> ClienteCatalogo:
    return ClienteCatalogo(pausa=0, max_resultados=3, timeout=30)


def test_jumbo_responde_el_catalogo_publico() -> None:
    resultado = consultar_jumbo("arroz", cliente=_cliente())
    assert resultado.ofertas, [error.mensaje for error in resultado.errores]
    oferta = resultado.ofertas[0]
    assert oferta.proveedor == "jumbo"
    assert oferta.moneda == "COP"
    assert oferta.estado_verificacion == "consulta_publica"
    assert "jumbocolombia.com" in oferta.url_fuente
    assert oferta.fecha_consulta == hoy_bogota()
    assert oferta.precio >= 0
    assert oferta.nombre


def test_superboom_responde_la_tienda_publica() -> None:
    resultado = consultar_superboom("arroz", cliente=_cliente())
    assert resultado.ofertas, [error.mensaje for error in resultado.errores]
    oferta = resultado.ofertas[0]
    assert oferta.proveedor == "superboom"
    assert oferta.moneda == "COP"
    assert oferta.estado_verificacion == "consulta_publica"
    assert oferta.url_fuente.startswith("https://web.superboom.net/shop/")
    assert oferta.fecha_consulta == hoy_bogota()
    assert oferta.precio > 0
    assert oferta.nombre
