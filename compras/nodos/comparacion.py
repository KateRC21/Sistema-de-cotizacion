"""Comparación: ordena alternativas ya evaluadas. No recalcula precios."""

from decimal import Decimal

from compras.schemas import EstadoCompra, GrupoItem, OfertaEvaluada

_ORDEN = {"equivalente": 0, "sustituto": 1, "no_comparable": 2}


def crear_nodo_comparar():
    def comparar(state: EstadoCompra) -> dict:
        grupos = [ordenar_grupo(grupo) for grupo in state.grupos]
        return {"grupos": grupos, "historial": [_linea(grupos)]}

    return comparar


def ordenar_grupo(grupo: GrupoItem) -> GrupoItem:
    """Equivalentes primero, luego sustitutos y al final lo no comparable.

    Dentro de cada relación, el menor precio por unidad base va primero.
    Un sustituto más barato no adelanta a un equivalente.
    """
    ofertas = sorted(grupo.ofertas, key=_clave)
    return grupo.model_copy(update={"ofertas": ofertas})


def _clave(oferta: OfertaEvaluada) -> tuple:
    precio = oferta.precio_por_unidad_base
    return (
        _ORDEN[oferta.relacion],
        precio is None,
        precio if precio is not None else Decimal("0"),
        oferta.cotizacion.proveedor,
        oferta.cotizacion.id_oferta,
    )


def _linea(grupos: list[GrupoItem]) -> str:
    if not grupos:
        return "[comparar] Sin grupos para ordenar."
    partes = []
    for grupo in grupos:
        primera = next(
            (oferta for oferta in grupo.ofertas if oferta.relacion == "equivalente"),
            None,
        )
        if primera is None or primera.precio_por_unidad_base is None:
            partes.append(f"{grupo.id_item}: sin equivalente comparable")
            continue
        unidad = primera.medida.unidad if primera.medida is not None else "unidad"
        partes.append(
            f"{grupo.id_item}: {primera.cotizacion.proveedor} "
            f"a {primera.precio_por_unidad_base} COP/{unidad}"
        )
    return "[comparar] " + "; ".join(partes)
