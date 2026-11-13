"""Consulta de una tienda para todos los productos de la solicitud.

Un fallo en un producto no borra las ofertas de los demás, ni las de la otra tienda.
"""

from collections.abc import Callable

from compras.schemas import ErrorConsulta, EstadoCompra, ItemSolicitado, Proveedor, ResultadoProveedor

Consultor = Callable[..., ResultadoProveedor]


def crear_nodo_consultar(proveedor: Proveedor, consultar: Consultor):
    def consultar_tienda(state: EstadoCompra | dict) -> dict:
        # Send entrega el estado como diccionario, no como el modelo del grafo.
        if not isinstance(state, EstadoCompra):
            state = EstadoCompra.model_validate(state)
        solicitud = state.solicitud
        if solicitud is None:
            return {"historial": [f"[{proveedor}] Sin solicitud."]}

        ofertas = []
        errores: list[ErrorConsulta] = []
        for item in solicitud.items:
            try:
                resultado = consultar(termino_de_busqueda(item), id_item=item.id_item)
            except Exception as exc:
                errores.append(
                    ErrorConsulta(
                        proveedor=proveedor,
                        mensaje=f"No se pudo consultar {proveedor}: {exc}",
                        id_item=item.id_item,
                    )
                )
                continue
            ofertas.extend(_ofertas_de(resultado, proveedor, item.id_item))
            errores.extend(_errores_de(resultado, proveedor, item.id_item))

        paquete = ResultadoProveedor(proveedor=proveedor, ofertas=ofertas, errores=errores)
        return {
            "resultados_proveedor": [paquete],
            "historial": [f"[{proveedor}] ofertas={len(ofertas)}, errores={len(errores)}"],
        }

    return consultar_tienda


def termino_de_busqueda(item: ItemSolicitado) -> str:
    """Nombre del producto y, si hace falta, la marca exigida."""
    nombre = " ".join(item.nombre.split())
    marca = " ".join((item.marca or "").split())
    if marca and marca.lower() not in nombre.lower():
        return f"{nombre} {marca}"
    return nombre


def _ofertas_de(resultado: ResultadoProveedor, proveedor: Proveedor, id_item: str):
    propias = []
    for oferta in resultado.ofertas:
        if oferta.proveedor != proveedor:
            continue
        if oferta.id_item is None:
            oferta = oferta.model_copy(update={"id_item": id_item})
        propias.append(oferta)
    return propias


def _errores_de(resultado: ResultadoProveedor, proveedor: Proveedor, id_item: str):
    propios = []
    for error in resultado.errores:
        if error.proveedor != proveedor:
            continue
        if error.id_item is None:
            error = error.model_copy(update={"id_item": id_item})
        propios.append(error)
    if any(oferta.proveedor != proveedor for oferta in resultado.ofertas):
        propios.append(
            ErrorConsulta(
                proveedor=proveedor,
                mensaje="La respuesta incluyó una oferta de otra tienda y se descartó.",
                id_item=id_item,
            )
        )
    return propios
