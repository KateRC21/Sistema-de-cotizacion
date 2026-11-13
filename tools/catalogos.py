"""Convierte texto de catálogo en campos de una cotización.

Solo copia medidas que ya están escritas en el nombre o en la unidad física
del SKU. Si no aparecen, la cantidad queda vacía: no se inventa un gramaje.
"""

import re
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from compras.schemas import Cotizacion, ErrorConsulta, Proveedor

_UNIDADES = {
    "kg": "kg",
    "g": "g",
    "gr": "g",
    "grs": "g",
    "ml": "ml",
    "cc": "ml",
    "l": "l",
    "lt": "l",
    "litro": "l",
    "litros": "l",
}
_MEDIDA = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
    r"(kg|grs|gr|g|ml|cc|litros|litro|lt|l)\b",
    re.IGNORECASE,
)
_UNIDADES_API = {"kg": "kg", "g": "g", "gr": "g", "grs": "g", "ml": "ml", "l": "l"}


def presentacion_desde_nombre(nombre: str) -> tuple[str | None, Decimal | None, str | None]:
    """Usa la última medida del nombre. «6 und x 500 g» queda en 500 g."""
    coincidencias = list(_MEDIDA.finditer(nombre))
    if not coincidencias:
        return None, None, None
    ultima = coincidencias[-1]
    cantidad = _numero(ultima.group(1))
    unidad = _UNIDADES[ultima.group(2).lower()]
    return f"{_texto_cantidad(cantidad)} {unidad}", cantidad, unidad


def presentacion_desde_sku(
    nombre: str,
    unidad_api: str | None,
    multiplicador: Decimal | int | None,
) -> tuple[str | None, Decimal | None, str | None]:
    explicita = presentacion_desde_nombre(nombre)
    if explicita[0] is not None:
        return explicita
    unidad = _UNIDADES_API.get((unidad_api or "").strip().lower())
    if unidad is None or multiplicador is None:
        return None, None, None
    cantidad = multiplicador if isinstance(multiplicador, Decimal) else Decimal(multiplicador)
    if cantidad <= 0:
        return None, None, None
    return f"{_texto_cantidad(cantidad)} {unidad}", cantidad, unidad


def armar_cotizacion(
    *,
    id_oferta: str,
    nombre: str,
    marca: str | None,
    presentacion: str | None,
    cantidad: Decimal | None,
    unidad: str | None,
    precio: Decimal | int | str,
    proveedor: Proveedor,
    url_fuente: str,
    fecha_consulta: date,
    disponibilidad: str,
    id_item: str | None,
) -> tuple[Cotizacion | None, ErrorConsulta | None]:
    """Valida una oferta. Si los datos no cuadran, devuelve el error y no un precio supuesto."""
    try:
        oferta = Cotizacion(
            id_oferta=id_oferta,
            nombre=nombre.strip(),
            marca=(marca or "").strip() or None,
            presentacion=presentacion,
            cantidad=cantidad,
            unidad=unidad,
            precio=precio,
            moneda="COP",
            proveedor=proveedor,
            url_fuente=url_fuente,
            fecha_consulta=fecha_consulta,
            disponibilidad=disponibilidad,  # type: ignore[arg-type]
            estado_verificacion="consulta_publica",
            id_item=id_item,
        )
    except (ValidationError, ValueError) as exc:
        return None, ErrorConsulta(
            proveedor=proveedor,
            mensaje=f"Oferta descartada ({nombre.strip() or id_oferta}): {_primer_error(exc)}",
            id_item=id_item,
        )
    return oferta, None


def _numero(texto: str) -> Decimal:
    if re.fullmatch(r"\d+[.,]\d{3}", texto):
        return Decimal(texto.replace(".", "").replace(",", ""))
    return Decimal(texto.replace(",", "."))


def _texto_cantidad(cantidad: Decimal) -> str:
    if cantidad == cantidad.to_integral():
        return str(cantidad.to_integral())
    return format(cantidad.normalize(), "f")


def _primer_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError) and exc.errors():
        return str(exc.errors()[0].get("msg", exc))
    return str(exc)
