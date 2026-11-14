"""Consulta de la tienda pública de Superboom (Odoo) en el Valle de Aburrá.

El 13 de noviembre de 2026, https://web.superboom.net/robots.txt no prohibía
rutas. Esta herramienta solo pide `/shop?search=`. El precio se toma del
campo schema.org `itemprop="price"`, no del texto con separador de miles.
"""

from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin

from compras.schemas import ErrorConsulta, ResultadoProveedor

from tools.catalogos import armar_cotizacion, conteo_desde_nombre, presentacion_desde_nombre
from tools.cliente_http import ClienteCatalogo

BASE = "https://web.superboom.net"
_RUTAS_NO_PRODUCTO = {"cart", "wishlist", "all-brands"}


def consultar_superboom(
    termino: str,
    *,
    id_item: str | None = None,
    cliente: ClienteCatalogo | None = None,
) -> ResultadoProveedor:
    """Busca en la primera página de la tienda y conserva hasta el máximo configurado."""
    texto = " ".join(termino.split())
    if not texto:
        return ResultadoProveedor(
            proveedor="superboom",
            errores=[
                ErrorConsulta(
                    proveedor="superboom",
                    mensaje="El término de búsqueda está vacío.",
                    id_item=id_item,
                )
            ],
        )

    cliente = cliente or ClienteCatalogo.desde_config()
    url = f"{BASE}/shop?{urlencode({'search': texto})}"
    try:
        respuesta = cliente.obtener(url)
    except Exception as exc:
        return ResultadoProveedor(
            proveedor="superboom",
            errores=[
                ErrorConsulta(
                    proveedor="superboom",
                    mensaje=f"No se pudo consultar Superboom: {exc}",
                    id_item=id_item,
                )
            ],
        )
    if respuesta.status != 200:
        return ResultadoProveedor(
            proveedor="superboom",
            errores=[
                ErrorConsulta(
                    proveedor="superboom",
                    mensaje=f"Superboom respondió HTTP {respuesta.status}.",
                    id_item=id_item,
                )
            ],
        )

    fichas = _leer_fichas(respuesta.cuerpo)
    if not fichas:
        return ResultadoProveedor(
            proveedor="superboom",
            errores=[
                ErrorConsulta(
                    proveedor="superboom",
                    mensaje=f"Sin resultados en Superboom para «{texto}».",
                    id_item=id_item,
                )
            ],
        )

    ofertas = []
    errores = []
    fecha = cliente.hoy()
    for ficha in fichas[: cliente.max_resultados]:
        oferta, error = _cotizar(ficha, id_item=id_item, fecha=fecha)
        if oferta is not None:
            ofertas.append(oferta)
        elif error is not None:
            errores.append(error)
    return ResultadoProveedor(proveedor="superboom", ofertas=ofertas, errores=errores)


def _cotizar(ficha: dict[str, str], *, id_item: str | None, fecha):
    nombre = " ".join(ficha["nombre"].split())
    precio = ficha["precio"].strip()
    moneda = ficha["moneda"].strip().upper()
    if not nombre or not precio:
        return None, ErrorConsulta(
            proveedor="superboom",
            mensaje=f"Ficha incompleta en Superboom ({nombre or ficha['href']}).",
            id_item=id_item,
        )
    if moneda != "COP":
        return None, ErrorConsulta(
            proveedor="superboom",
            mensaje=f"Moneda {moneda or 'desconocida'} en {nombre}. Solo se acepta COP.",
            id_item=id_item,
        )
    ruta = ficha["href"].split("?")[0]
    slug = ruta.rstrip("/").split("/")[-1]
    presentacion, cantidad, unidad = presentacion_desde_nombre(nombre)
    if presentacion is None:
        presentacion, cantidad, unidad = conteo_desde_nombre(nombre)
    disponibilidad = "no_disponible" if "OutOfStock" in ficha["disponibilidad"] else "disponible"
    return armar_cotizacion(
        id_oferta=f"superboom-{slug}",
        nombre=nombre,
        marca=None,
        presentacion=presentacion,
        cantidad=cantidad,
        unidad=unidad,
        precio=precio,
        proveedor="superboom",
        url_fuente=urljoin(BASE, ruta),
        fecha_consulta=fecha,
        disponibilidad=disponibilidad,
        id_item=id_item,
        url_imagen=urljoin(BASE, ficha["imagen"]) if ficha.get("imagen") else None,
    )


def _leer_fichas(html: str) -> list[dict[str, str]]:
    parser = _Fichas()
    parser.feed(html)
    parser.close()
    return parser.fichas


def _es_producto(href: str) -> bool:
    ruta = href.split("?")[0]
    if not ruta.startswith("/shop/"):
        return False
    resto = ruta.removeprefix("/shop/").strip("/")
    return bool(resto) and "/" not in resto and resto not in _RUTAS_NO_PRODUCTO


class _Fichas(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fichas: list[dict[str, str]] = []
        self._actual: dict[str, str] | None = None
        self._campo: str | None = None
        self._imagen = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        atributos = {clave: valor or "" for clave, valor in attrs}
        if tag == "img" and "/web/image/product.template/" in atributos.get("src", ""):
            # La foto aparece justo antes del nombre de su ficha.
            self._imagen = atributos["src"]
            return
        itemprop = atributos.get("itemprop")
        if tag == "a" and itemprop == "name":
            self._cerrar()
            href = atributos.get("href", "")
            if not _es_producto(href):
                return
            nombre = atributos.get("content", "")
            self._actual = {
                "nombre": nombre,
                "href": href,
                "precio": "",
                "moneda": "",
                "disponibilidad": atributos.get("disponibilidad", ""),
                "imagen": self._imagen,
            }
            self._imagen = ""
            self._campo = None if nombre else "nombre"
            return
        if self._actual is None or not itemprop:
            return
        if itemprop == "availability":
            self._actual["disponibilidad"] = atributos.get("href") or atributos.get("content", "")
            self._campo = "disponibilidad"
            return
        if itemprop == "price":
            contenido = atributos.get("content", "")
            if contenido:
                self._actual["precio"] = contenido
                self._campo = None
            else:
                self._campo = "precio"
        elif itemprop == "priceCurrency":
            self._campo = "moneda"

    def handle_data(self, data: str) -> None:
        if self._actual is None or self._campo is None:
            return
        self._actual[self._campo] += data

    def handle_endtag(self, tag: str) -> None:
        self._campo = None

    def close(self) -> None:
        super().close()
        self._cerrar()

    def _cerrar(self) -> None:
        if self._actual is not None:
            self.fichas.append(self._actual)
            self._actual = None
            self._campo = None
