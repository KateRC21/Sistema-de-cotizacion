"""Lectura del catálogo público de VTEX usado por Jumbo.

Ruta permitida el 13 de noviembre de 2026: el robots.txt de
www.jumbocolombia.com no prohíbe `/api/`. Esta módulo solo llama
`/api/catalog_system/pub/products/search` con `ft`, `_from` y `_to`.
No envía canal de venta: el precio es el del sitio público, no el de una
sede confirmada en Medellín.
"""

import json
from datetime import date
from decimal import Decimal
from urllib.parse import urljoin

from compras.schemas import Cotizacion, ErrorConsulta, Proveedor

from tools.catalogos import armar_cotizacion, presentacion_desde_sku


def interpretar_vtex(
    cuerpo: str,
    *,
    proveedor: Proveedor,
    base_url: str,
    termino: str,
    id_item: str | None,
    fecha: date,
    max_resultados: int,
) -> tuple[list[Cotizacion], list[ErrorConsulta]]:
    try:
        payload = json.loads(cuerpo, parse_float=Decimal)
    except json.JSONDecodeError:
        return [], [
            ErrorConsulta(
                proveedor=proveedor,
                mensaje=f"{_etiqueta(proveedor)} no devolvió JSON de catálogo.",
                id_item=id_item,
            )
        ]
    if not isinstance(payload, list):
        return [], [
            ErrorConsulta(
                proveedor=proveedor,
                mensaje=f"{_etiqueta(proveedor)} respondió un error de catálogo.",
                id_item=id_item,
            )
        ]
    if not payload:
        return [], [_sin_resultados(proveedor, termino, id_item)]

    ofertas: list[Cotizacion] = []
    errores: list[ErrorConsulta] = []
    for producto in payload:
        if len(ofertas) >= max_resultados:
            break
        if not isinstance(producto, dict):
            continue
        nombre_producto = str(producto.get("productName") or "").strip()
        marca = str(producto.get("brand") or "").strip() or None
        enlace = str(producto.get("link") or "").strip()
        items = producto.get("items") or []
        if not items:
            errores.append(
                ErrorConsulta(
                    proveedor=proveedor,
                    mensaje=f"Sin SKU para {nombre_producto or 'un producto'}.",
                    id_item=id_item,
                )
            )
            continue
        for sku in items:
            if len(ofertas) >= max_resultados:
                break
            oferta, error = _oferta_sku(
                sku if isinstance(sku, dict) else {},
                proveedor=proveedor,
                base_url=base_url,
                nombre_producto=nombre_producto,
                marca=marca,
                enlace=enlace,
                product_id=str(producto.get("productId") or ""),
                id_item=id_item,
                fecha=fecha,
            )
            if oferta is not None:
                ofertas.append(oferta)
            elif error is not None:
                errores.append(error)
    if not ofertas and not errores:
        errores.append(_sin_resultados(proveedor, termino, id_item))
    return ofertas, errores


def _oferta_sku(
    sku: dict,
    *,
    proveedor: Proveedor,
    base_url: str,
    nombre_producto: str,
    marca: str | None,
    enlace: str,
    product_id: str,
    id_item: str | None,
    fecha: date,
) -> tuple[Cotizacion | None, ErrorConsulta | None]:
    nombre = str(sku.get("name") or nombre_producto).strip()
    vendedores = sku.get("sellers") or []
    if not vendedores or not isinstance(vendedores[0], dict):
        return None, ErrorConsulta(
            proveedor=proveedor,
            mensaje=f"Sin vendedor para {nombre or product_id}.",
            id_item=id_item,
        )
    oferta_comercial = vendedores[0].get("commertialOffer") or vendedores[0].get("commercialOffer")
    if not isinstance(oferta_comercial, dict) or oferta_comercial.get("Price") is None:
        return None, ErrorConsulta(
            proveedor=proveedor,
            mensaje=f"Sin precio publicado para {nombre or product_id}.",
            id_item=id_item,
        )
    precio = oferta_comercial["Price"]
    disponible = bool(oferta_comercial.get("IsAvailable"))
    cantidad_stock = oferta_comercial.get("AvailableQuantity")
    if not disponible or cantidad_stock == 0 or _es_cero(precio):
        disponibilidad = "no_disponible"
    elif oferta_comercial.get("IsAvailable") is None:
        disponibilidad = "desconocida"
    else:
        disponibilidad = "disponible"

    presentacion, cantidad, unidad = presentacion_desde_sku(
        nombre,
        str(sku.get("measurementUnit") or ""),
        sku.get("unitMultiplier"),
    )
    item_id = str(sku.get("itemId") or "sku")
    imagenes = sku.get("images") or []
    url_imagen = None
    if imagenes and isinstance(imagenes[0], dict):
        url_imagen = str(imagenes[0].get("imageUrl") or "").strip() or None
    id_vendedor = str(vendedores[0].get("sellerId") or "").strip() or None
    url = enlace or urljoin(base_url, str(sku.get("detailUrl") or ""))
    if url.startswith("/"):
        url = urljoin(base_url, url)
    return armar_cotizacion(
        id_oferta=f"{proveedor}-{product_id or item_id}-{item_id}",
        nombre=nombre or nombre_producto,
        marca=marca,
        presentacion=presentacion,
        cantidad=cantidad,
        unidad=unidad,
        precio=precio,
        proveedor=proveedor,
        url_fuente=url or base_url,
        fecha_consulta=fecha,
        disponibilidad=disponibilidad,
        id_item=id_item,
        url_imagen=url_imagen,
        id_sku=item_id if sku.get("itemId") else None,
        id_vendedor=id_vendedor,
    )


def _sin_resultados(proveedor: Proveedor, termino: str, id_item: str | None) -> ErrorConsulta:
    return ErrorConsulta(
        proveedor=proveedor,
        mensaje=f"Sin resultados en {_etiqueta(proveedor)} para «{termino}».",
        id_item=id_item,
    )


def _etiqueta(proveedor: Proveedor) -> str:
    return "Jumbo" if proveedor == "jumbo" else proveedor


def _es_cero(precio: object) -> bool:
    try:
        return Decimal(precio) == 0  # type: ignore[arg-type]
    except Exception:
        return False
