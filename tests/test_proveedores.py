"""Pruebas de las herramientas de catálogo con respuestas ficticias, sin red."""

import json
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from compras.schemas import ErrorConsulta
from tools.catalogos import presentacion_desde_nombre
from tools.cliente_http import ClienteCatalogo, RespuestaHttp
from tools.jumbo import consultar_jumbo
from tools.superboom import consultar_superboom

_HOY = date(2026, 11, 13)


def _cliente(cuerpo: str, status: int = 200, llamadas: list[str] | None = None) -> ClienteCatalogo:
    def fetcher(url: str, *, user_agent: str, timeout: float) -> RespuestaHttp:
        if llamadas is not None:
            llamadas.append(url)
        return RespuestaHttp(status, cuerpo, url)

    return ClienteCatalogo(
        pausa=0,
        max_resultados=8,
        fetcher=fetcher,
        hoy=lambda: _HOY,
    )


def _jumbo_json() -> str:
    return json.dumps(
        [
            {
                "productId": "345774",
                "productName": "Arroz Casanare Blanco 500 g",
                "brand": "CASANARE",
                "link": "https://www.jumbocolombia.com/arroz-casanare-blanco/p",
                "items": [
                    {
                        "itemId": "3655815",
                        "name": "Arroz Casanare Blanco 500 g",
                        "measurementUnit": "un",
                        "unitMultiplier": 1,
                        "sellers": [
                            {
                                "sellerName": "Cencosud - Colombia",
                                "commertialOffer": {
                                    "Price": 3290.0,
                                    "IsAvailable": True,
                                    "AvailableQuantity": 18,
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "productId": "999",
                "productName": "Producto sin precio",
                "brand": "X",
                "link": "https://www.jumbocolombia.com/sin-precio/p",
                "items": [{"itemId": "1", "name": "Producto sin precio", "sellers": []}],
            },
        ]
    )


_HTML_SUPERBOOM = """
<a itemprop="name" content="Tostadas De Arroz Integral 80Gr"
   href="/shop/tostadas-arroz-80gr-32486?search=arroz">Tostadas</a>
<span class="oe_currency_value">5.680</span>
<span itemprop="price">5680.0</span>
<span itemprop="priceCurrency">COP</span>
<a itemprop="name" content="Aceite importado 900 ml" href="/shop/aceite-900-ml-99">Aceite</a>
<span itemprop="price">12345.0</span>
<span itemprop="priceCurrency">USD</span>
<a itemprop="name" content="Carrito" href="/shop/cart">Carrito</a>
"""


def test_presentacion_toma_la_ultima_medida_del_nombre() -> None:
    texto, cantidad, unidad = presentacion_desde_nombre("Pack 6 und x 1.000 g")
    assert (texto, cantidad, unidad) == ("1000 g", Decimal("1000"), "g")
    assert presentacion_desde_nombre("Arroz Casanare Blanco") == (None, None, None)


def test_jumbo_arma_cotizacion_y_conserva_el_producto_sin_precio_como_error() -> None:
    resultado = consultar_jumbo("arroz", id_item="item-1", cliente=_cliente(_jumbo_json(), status=206))
    assert resultado.proveedor == "jumbo"
    assert len(resultado.ofertas) == 1
    oferta = resultado.ofertas[0]
    assert oferta.id_oferta == "jumbo-345774-3655815"
    assert oferta.marca == "CASANARE"
    assert oferta.presentacion == "500 g"
    assert oferta.cantidad == Decimal("500")
    assert oferta.unidad == "g"
    assert oferta.precio == Decimal("3290")
    assert oferta.moneda == "COP"
    assert oferta.disponibilidad == "disponible"
    assert oferta.estado_verificacion == "consulta_publica"
    assert oferta.fecha_consulta == _HOY
    assert oferta.id_item == "item-1"
    assert oferta.url_fuente == "https://www.jumbocolombia.com/arroz-casanare-blanco/p"
    assert len(resultado.errores) == 1
    assert "sin precio" in resultado.errores[0].mensaje


def test_jumbo_solo_usa_la_ruta_publica_de_busqueda() -> None:
    llamadas: list[str] = []
    consultar_jumbo("leche deslactosada", cliente=_cliente("[]", llamadas=llamadas))
    partes = urlparse(llamadas[0])
    assert partes.scheme == "https"
    assert partes.netloc == "www.jumbocolombia.com"
    assert partes.path == "/api/catalog_system/pub/products/search"
    assert set(parse_qs(partes.query)) == {"ft", "_from", "_to"}
    assert parse_qs(partes.query)["ft"] == ["leche deslactosada"]
    assert parse_qs(partes.query)["_to"] == ["7"]


def test_jumbo_vacio_no_llama_la_red() -> None:
    llamadas: list[str] = []
    resultado = consultar_jumbo("   ", cliente=_cliente("[]", llamadas=llamadas))
    assert llamadas == []
    assert resultado.ofertas == []
    assert "vacío" in resultado.errores[0].mensaje


def test_jumbo_http_500_no_inventa_precios() -> None:
    resultado = consultar_jumbo("arroz", cliente=_cliente(_jumbo_json(), status=500))
    assert resultado.ofertas == []
    assert "HTTP 500" in resultado.errores[0].mensaje


def test_superboom_usa_el_precio_schema_y_rechaza_otra_moneda() -> None:
    resultado = consultar_superboom("arroz", cliente=_cliente(_HTML_SUPERBOOM))
    assert len(resultado.ofertas) == 1
    oferta = resultado.ofertas[0]
    assert oferta.proveedor == "superboom"
    assert oferta.nombre.startswith("Tostadas")
    assert oferta.precio == Decimal("5680")
    assert oferta.presentacion == "80 g"
    assert oferta.cantidad == Decimal("80")
    assert oferta.unidad == "g"
    assert oferta.marca is None
    assert oferta.estado_verificacion == "consulta_publica"
    assert oferta.url_fuente == "https://web.superboom.net/shop/tostadas-arroz-80gr-32486"
    assert any("USD" in error.mensaje for error in resultado.errores)


def test_superboom_solo_pide_la_busqueda_de_la_tienda() -> None:
    llamadas: list[str] = []
    consultar_superboom("arroz", cliente=_cliente(_HTML_SUPERBOOM, llamadas=llamadas))
    partes = urlparse(llamadas[0])
    assert partes.netloc == "web.superboom.net"
    assert partes.path == "/shop"
    assert set(parse_qs(partes.query)) == {"search"}


def test_un_proveedor_puede_fallar_sin_borrar_al_otro() -> None:
    jumbo = consultar_jumbo("arroz", cliente=_cliente("no-json", status=200))
    superboom = consultar_superboom("arroz", cliente=_cliente(_HTML_SUPERBOOM))
    assert jumbo.ofertas == []
    assert jumbo.errores
    assert superboom.ofertas
    assert all(isinstance(error, ErrorConsulta) for error in jumbo.errores)
