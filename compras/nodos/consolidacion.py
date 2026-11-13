"""Reúne las respuestas de las tiendas sin descartar la que sí contestó."""

from compras.schemas import Cotizacion, ErrorConsulta, EstadoCompra


def consolidar(state: EstadoCompra) -> dict:
    ofertas: list[Cotizacion] = []
    errores: list[ErrorConsulta] = []
    for resultado in state.resultados_proveedor:
        ofertas.extend(resultado.ofertas)
        errores.extend(resultado.errores)
    ofertas = sorted(
        ofertas,
        key=lambda oferta: (oferta.proveedor, oferta.id_item or "", oferta.id_oferta),
    )
    errores = sorted(
        errores,
        key=lambda error: (error.proveedor, error.id_item or "", error.mensaje),
    )
    tiendas = ",".join(resultado.proveedor for resultado in state.resultados_proveedor) or "ninguna"
    return {
        "ofertas": ofertas,
        "errores_consulta": errores,
        "historial": [
            f"[consolidar] ofertas={len(ofertas)}, errores={len(errores)}, tiendas={tiendas}"
        ],
    }
