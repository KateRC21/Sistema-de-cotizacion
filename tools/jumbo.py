"""Consulta del catálogo público de Jumbo Colombia."""

from urllib.parse import quote, urlencode

from compras.schemas import ErrorConsulta, ResultadoProveedor

from tools.cliente_http import ClienteCatalogo
from tools.vtex import interpretar_vtex

BASE = "https://www.jumbocolombia.com"
RUTA = "/api/catalog_system/pub/products/search"


def consultar_jumbo(
    termino: str,
    *,
    id_item: str | None = None,
    cliente: ClienteCatalogo | None = None,
) -> ResultadoProveedor:
    """Busca un término y devuelve cotizaciones homogéneas, o el error de esta tienda."""
    texto = " ".join(termino.split())
    if not texto:
        return ResultadoProveedor(
            proveedor="jumbo",
            errores=[
                ErrorConsulta(
                    proveedor="jumbo",
                    mensaje="El término de búsqueda está vacío.",
                    id_item=id_item,
                )
            ],
        )

    cliente = cliente or ClienteCatalogo.desde_config()
    url = f"{BASE}{RUTA}?{urlencode({'ft': texto, '_from': 0, '_to': cliente.max_resultados - 1}, quote_via=quote)}"
    try:
        respuesta = cliente.obtener(url)
    except Exception as exc:
        return ResultadoProveedor(
            proveedor="jumbo",
            errores=[
                ErrorConsulta(
                    proveedor="jumbo",
                    mensaje=f"No se pudo consultar Jumbo: {exc}",
                    id_item=id_item,
                )
            ],
        )
    if respuesta.status not in (200, 206):
        return ResultadoProveedor(
            proveedor="jumbo",
            errores=[
                ErrorConsulta(
                    proveedor="jumbo",
                    mensaje=f"Jumbo respondió HTTP {respuesta.status}.",
                    id_item=id_item,
                )
            ],
        )
    ofertas, errores = interpretar_vtex(
        respuesta.cuerpo,
        proveedor="jumbo",
        base_url=BASE,
        termino=texto,
        id_item=id_item,
        fecha=cliente.hoy(),
        max_resultados=cliente.max_resultados,
    )
    return ResultadoProveedor(proveedor="jumbo", ofertas=ofertas, errores=errores)
