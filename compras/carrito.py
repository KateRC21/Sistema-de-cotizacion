"""Opciones para elegir y carrito por tienda. Lógica pura: no consulta tiendas.

La persona escoge una oferta por producto. Aquí se calcula cuántos empaques
comprar, el subtotal por tienda y los enlaces para continuar en cada sitio.
Los enlaces a cada producto los abre la persona en su navegador; el programa no entra al pago.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import quote

from compras.schemas import Cotizacion, EstadoCompra, ItemSolicitado
from tools.calculos import misma_dimension, normalizar_medida

# Éxito y Carulla prohíben en su robots.txt la búsqueda automática y sus APIs
# y protegen el sitio con Cloudflare. Solo se ofrece un enlace para que la
# persona busque ella misma.
_BUSQUEDA_MANUAL = {
    "Éxito": "https://www.exito.com/s?q=",
    "Carulla": "https://www.carulla.com/s?q=",
}


@dataclass(frozen=True)
class LineaCarrito:
    item: ItemSolicitado
    oferta: Cotizacion
    empaques: int
    subtotal: Decimal


def opciones_por_item(estado: EstadoCompra, limite: int = 8) -> dict[str, list[Cotizacion]]:
    """Ofertas disponibles por producto, de la más barata a la más cara.

    No se filtra por equivalencia: la persona decide entre lo que sí existe.
    """
    resultado: dict[str, list[Cotizacion]] = {}
    if estado.solicitud is None:
        return resultado
    for item in estado.solicitud.items:
        propias = [
            oferta
            for oferta in estado.ofertas
            if oferta.id_item == item.id_item
            and oferta.disponibilidad == "disponible"
            and oferta.precio > 0
        ]
        propias.sort(key=lambda oferta: (oferta.precio, oferta.proveedor, oferta.id_oferta))
        resultado[item.id_item] = propias[:limite]
    return resultado


def recomendada(estado: EstadoCompra, id_item: str) -> tuple[Cotizacion, str] | None:
    """La oferta que más se adapta y por qué.

    Entre los equivalentes gana la que cubre lo pedido al menor costo total
    (precio por empaques enteros), no la de menor precio por kilo: así 2 kg de
    arroz no se resuelven con un bulto de 10 kg. Sin equivalentes toma un
    sustituto. Sin ninguno comparable no recomienda nada.
    """
    item = next((i for i in estado.solicitud.items if i.id_item == id_item), None) if estado.solicitud else None
    if item is None:
        return None
    for relacion, texto in (
        ("equivalente", "Equivalente a lo que pediste, al menor costo para cubrir la cantidad."),
        ("sustituto", "Sustituto cercano: no hay un equivalente exacto disponible."),
    ):
        candidatas = [
            oferta
            for grupo in estado.grupos
            if grupo.id_item == id_item
            for oferta in grupo.ofertas
            if oferta.relacion == relacion and oferta.cumple_restricciones
        ]
        if candidatas:
            mejor = min(
                candidatas,
                key=lambda o: (
                    o.cotizacion.precio * empaques_necesarios(item, o.cotizacion),
                    o.precio_por_unidad_base or Decimal("0"),
                    o.cotizacion.id_oferta,
                ),
            )
            return mejor.cotizacion, texto
    return None


def empaques_necesarios(item: ItemSolicitado, oferta: Cotizacion) -> int:
    """Presentaciones enteras para cubrir lo pedido; 1 si no se puede comparar."""
    if item.cantidad is None or item.cantidad <= 0:
        return 1
    if item.unidad == "unidad":
        return max(1, math.ceil(item.cantidad))
    if (
        item.unidad
        and oferta.cantidad is not None
        and oferta.unidad
        and misma_dimension(item.unidad, oferta.unidad)
    ):
        pedido = normalizar_medida(item.cantidad, item.unidad)
        ofrecido = normalizar_medida(oferta.cantidad, oferta.unidad)
        if pedido is not None and ofrecido is not None:
            return max(1, math.ceil(pedido.cantidad / ofrecido.cantidad))
    return 1


def armar_carrito(
    solicitud_items: list[ItemSolicitado],
    elegidas: dict[str, Cotizacion],
    manual: dict[str, int] | None = None,
) -> list[LineaCarrito]:
    lineas: list[LineaCarrito] = []
    for item in solicitud_items:
        oferta = elegidas.get(item.id_item)
        if oferta is None:
            continue
        empaques = (manual or {}).get(item.id_item) or empaques_necesarios(item, oferta)
        lineas.append(LineaCarrito(item, oferta, empaques, oferta.precio * empaques))
    return lineas


def subtotal_por_tienda(lineas: list[LineaCarrito]) -> dict[str, Decimal]:
    totales: dict[str, Decimal] = {}
    for linea in lineas:
        proveedor = linea.oferta.proveedor
        totales[proveedor] = totales.get(proveedor, Decimal("0")) + linea.subtotal
    return totales


def enlaces_busqueda_manual(termino: str) -> dict[str, str]:
    """Enlaces de búsqueda en tiendas que no se consultan automáticamente."""
    texto = quote(" ".join(termino.split()))
    return {tienda: base + texto for tienda, base in _BUSQUEDA_MANUAL.items()}
