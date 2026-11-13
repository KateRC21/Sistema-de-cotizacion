"""Validación, suposiciones y pausa para aclarar.

La ciudad y la tienda se pueden suponer y quedan registradas. La cantidad,
la unidad y el producto no se inventan: se pide el dato con interrupt()
o se cierra la solicitud.
"""

from langgraph.types import interrupt

from compras.routers import faltan_datos_esenciales
from compras.schemas import EstadoCompra, SolicitudInterpretada, Suposicion


def crear_nodo_validar(ciudad_defecto: str):
    def validar(state: EstadoCompra) -> dict:
        solicitud = state.solicitud
        if solicitud is None:
            return {"historial": ["[validar] No hay solicitud interpretada."]}
        faltan = faltan_datos_esenciales(solicitud)
        if faltan:
            return {"historial": [f"[validar] faltan: {', '.join(faltan)}"]}

        nueva, suposiciones = aplicar_suposiciones(solicitud, ciudad_defecto=ciudad_defecto)
        ya = {(item.campo, item.valor) for item in state.suposiciones}
        nuevas = [item for item in suposiciones if (item.campo, item.valor) not in ya]
        tiendas = ",".join(nueva.proveedores) or "ninguna"
        return {
            "solicitud": nueva,
            "suposiciones": nuevas,
            "historial": [f"[validar] ciudad={nueva.ciudad}, proveedores={tiendas}"],
        }

    return validar


def aplicar_suposiciones(
    solicitud: SolicitudInterpretada,
    *,
    ciudad_defecto: str,
) -> tuple[SolicitudInterpretada, list[Suposicion]]:
    """Completa ciudad y tiendas solo cuando el producto ya se puede consultar."""
    cambios: dict[str, object] = {}
    suposiciones: list[Suposicion] = []
    if not (solicitud.ciudad or "").strip():
        cambios["ciudad"] = ciudad_defecto
        suposiciones.append(
            Suposicion(
                campo="ciudad",
                valor=ciudad_defecto,
                motivo="El texto no dice la ciudad. Se usa la ciudad por defecto del proyecto.",
            )
        )
    if not solicitud.proveedores:
        cambios["proveedores"] = ["jumbo", "superboom"]
        if any(dato.startswith("proveedor no disponible") for dato in solicitud.datos_faltantes):
            motivo = "La tienda pedida no está disponible. Se consultan Jumbo y Superboom."
        else:
            motivo = "El texto no nombra Jumbo ni Superboom. Se consultan las dos."
        suposiciones.append(
            Suposicion(campo="proveedores", valor="jumbo, superboom", motivo=motivo)
        )
    nueva = solicitud.model_copy(update=cambios) if cambios else solicitud
    return nueva, suposiciones


def pregunta_aclaracion(solicitud: SolicitudInterpretada) -> str:
    """Texto que ve la persona mientras el grafo está en pausa."""
    if not solicitud.items:
        return (
            "No identifiqué ningún producto. "
            "Indica qué quieres comprar, con la cantidad y la unidad."
        )
    incompletos = [
        item.nombre
        for item in solicitud.items
        if item.cantidad is None or not (item.unidad or "").strip()
    ]
    nombres = ", ".join(incompletos) or "la compra"
    faltan = faltan_datos_esenciales(solicitud)
    detalles: list[str] = []
    if "cantidad" in faltan:
        detalles.append("la cantidad")
    if "unidad" in faltan:
        detalles.append("la unidad, por ejemplo kg, g, l, ml o unidad")
    return f"Para {nombres} falta {' y '.join(detalles)}. Responde con ese dato."


def crear_nodo_aclarar(max_aclaraciones: int):
    """Pausa el grafo. Al reanudar, la respuesta entra al historial de aclaraciones."""

    def aclarar(state: EstadoCompra) -> dict:
        solicitud = state.solicitud
        if solicitud is None:
            return {"historial": ["[aclarar] No hay solicitud para aclarar."]}
        faltan = faltan_datos_esenciales(solicitud)
        pregunta = pregunta_aclaracion(solicitud)
        respuesta = interrupt(
            {
                "pregunta": pregunta,
                "faltantes": faltan,
                "ronda": state.rondas_aclaracion + 1,
                "maximo": max_aclaraciones,
            }
        )
        texto = respuesta.strip() if isinstance(respuesta, str) else str(respuesta).strip()
        ronda = state.rondas_aclaracion + 1
        return {
            "mensajes_aclaracion": [texto or "(sin respuesta)"],
            "rondas_aclaracion": ronda,
            "historial": [f"[aclarar] ronda={ronda}: {pregunta}"],
        }

    return aclarar


def crear_nodo_cerrar():
    def cerrar(state: EstadoCompra) -> dict:
        solicitud = state.solicitud
        faltan = faltan_datos_esenciales(solicitud) if solicitud is not None else ["solicitud"]
        detalle = ", ".join(faltan)
        return {
            "historial": [
                f"[cerrar] La solicitud sigue incompleta ({detalle}). "
                "No se consultan las tiendas."
            ]
        }

    return cerrar
