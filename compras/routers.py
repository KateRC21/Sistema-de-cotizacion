"""Routers puros: leen el estado y no lo modifican."""

from typing import Literal

from compras.schemas import EstadoCompra, SolicitudInterpretada

DestinoValidacion = Literal["aclarar", "consultar", "cerrar"]
_PROVEEDORES = ("jumbo", "superboom")


def faltan_datos_esenciales(solicitud: SolicitudInterpretada) -> list[str]:
    """Producto, cantidad o unidad. La ciudad y la tienda no entran aquí."""
    if not solicitud.items:
        return ["producto"]
    faltan: list[str] = []
    if any(item.cantidad is None for item in solicitud.items):
        faltan.append("cantidad")
    if any(item.unidad is None for item in solicitud.items):
        faltan.append("unidad")
    return faltan


def destino_tras_validar(state: EstadoCompra, *, max_aclaraciones: int) -> DestinoValidacion:
    """aclarar, consultar o cerrar.

    Cada aclaración cuenta en `rondas_aclaracion`. Al llegar al máximo se cierra
    sin inventar la cantidad ni la unidad.
    """
    solicitud = state.solicitud
    if solicitud is None or faltan_datos_esenciales(solicitud):
        if solicitud is not None and state.rondas_aclaracion < max_aclaraciones:
            return "aclarar"
        return "cerrar"
    return "consultar"


def proveedores_a_consultar(state: EstadoCompra) -> list[str]:
    """Tiendas habilitadas que ya quedaron en la solicitud, sin repetir."""
    solicitud = state.solicitud
    if solicitud is None:
        return []
    elegidos: list[str] = []
    for proveedor in solicitud.proveedores:
        if proveedor in _PROVEEDORES and proveedor not in elegidos:
            elegidos.append(proveedor)
    return elegidos
