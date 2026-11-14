"""Normalización: Python convierte y valida; el LLM solo clasifica identificadores."""

import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from langchain_core.runnables import Runnable

from compras.schemas import (
    ClasificacionEquivalenciasLLM,
    ClasificacionOfertaLLM,
    Cotizacion,
    EstadoCompra,
    GrupoItem,
    ItemSolicitado,
    MedidaNormalizada,
    OfertaEvaluada,
    Relacion,
    SolicitudInterpretada,
)
from tools.calculos import misma_dimension, normalizar_medida, precio_por_unidad_base


@dataclass
class _Lista:
    cotizacion: Cotizacion
    medida: MedidaNormalizada | None
    precio_base: Decimal | None
    exclusion: str | None


def crear_nodo_normalizar(clasificador: Runnable):
    """Fábrica. El clasificador puede ser el LLM o un sustituto de prueba."""

    def normalizar(state: EstadoCompra) -> dict:
        if state.solicitud is None:
            return {"grupos": [], "historial": ["[normalizar] No hay solicitud interpretada."]}
        grupos = evaluar_ofertas(state.solicitud, state.ofertas, clasificador)
        return {
            "grupos": grupos,
            "historial": [_linea_historial(grupos)],
        }

    return normalizar


def evaluar_ofertas(
    solicitud: SolicitudInterpretada,
    ofertas: list[Cotizacion],
    clasificador: Runnable,
) -> list[GrupoItem]:
    """Arma un grupo por producto. Una oferta de otro ítem no entra en el grupo."""
    por_item = {item.id_item: item for item in solicitud.items}
    preparadas: dict[str, list[_Lista]] = {item.id_item: [] for item in solicitud.items}
    for oferta in ofertas:
        if oferta.id_item not in por_item:
            continue
        preparadas[oferta.id_item].append(_preparar(por_item[oferta.id_item], oferta))

    candidatos = [
        (por_item[id_item], lista)
        for id_item, listas in preparadas.items()
        for lista in listas
        if lista.exclusion is None
    ]
    clasificaciones = _clasificar(candidatos, clasificador) if candidatos else {}

    grupos: list[GrupoItem] = []
    for item in solicitud.items:
        evaluadas = [
            _evaluar(item, lista, clasificaciones.get((item.id_item, lista.cotizacion.id_oferta)))
            for lista in preparadas[item.id_item]
        ]
        grupos.append(GrupoItem(id_item=item.id_item, ofertas=evaluadas))
    return grupos


def _preparar(item: ItemSolicitado, oferta: Cotizacion) -> _Lista:
    medida = None
    if oferta.cantidad is not None and oferta.unidad:
        medida = normalizar_medida(oferta.cantidad, oferta.unidad)
    # «1 paquete», «1 bolsa»: se compara por empaque, sea cual sea su peso.
    por_empaque = item.unidad == "unidad"
    if por_empaque and (medida is None or medida.dimension != "conteo"):
        medida = MedidaNormalizada(cantidad=Decimal("1"), unidad="unidad", dimension="conteo")
    precio_base = None
    if medida is not None and oferta.precio > 0:
        precio_base = precio_por_unidad_base(oferta.precio, medida)
    exclusion = _motivo_exclusion(item, oferta, medida)
    if medida is None or precio_base is None:
        return _Lista(oferta, None, None, exclusion or "La oferta no tiene un precio por unidad base.")
    return _Lista(oferta, medida, precio_base, exclusion)


def _motivo_exclusion(
    item: ItemSolicitado,
    oferta: Cotizacion,
    medida: MedidaNormalizada | None,
) -> str | None:
    if oferta.disponibilidad != "disponible" or oferta.precio <= 0:
        return "La oferta no está disponible o no tiene un precio utilizable."
    if medida is None:
        return "La oferta no trae una cantidad y una unidad comparables."
    if item.unidad != "unidad" and item.unidad and not misma_dimension(item.unidad, oferta.unidad):
        # (un pedido por empaque acepta cualquier presentación)
        return "La unidad de la oferta no se puede comparar con la unidad pedida."
    marca = _marca_coincide(item.marca, oferta.marca)
    if marca is None:
        return "La oferta no informa la marca exigida."
    if marca is False and not item.acepta_sustitutos:
        return "La marca no coincide con la marca exigida."
    texto_oferta = " ".join(
        parte for parte in (oferta.nombre, oferta.presentacion, oferta.marca) if parte
    )
    for caracteristica in item.caracteristicas:
        if _plegar(caracteristica) not in _plegar(texto_oferta):
            return f"No se confirma la característica «{caracteristica}»."
    return None


def _clasificar(
    candidatos: list[tuple[ItemSolicitado, _Lista]],
    clasificador: Runnable,
) -> dict[tuple[str, str], ClasificacionOfertaLLM]:
    # Una llamada por producto, en paralelo: una sola con todas las ofertas
    # tarda minutos cuando la lista es larga.
    por_item: dict[str, list[tuple[ItemSolicitado, _Lista]]] = {}
    for item, lista in candidatos:
        por_item.setdefault(item.id_item, []).append((item, lista))
    entradas = [{"contexto": _contexto(grupo)} for grupo in por_item.values()]
    try:
        salidas = clasificador.batch(
            entradas, config={"max_concurrency": 8}, return_exceptions=True
        )
    except Exception:
        return {}
    clasificaciones: list[ClasificacionOfertaLLM] = []
    for salida in salidas:
        if isinstance(salida, Exception):
            continue  # Ese producto queda sin clasificar: no comparable, sin inventar.
        try:
            if not isinstance(salida, ClasificacionEquivalenciasLLM):
                salida = ClasificacionEquivalenciasLLM.model_validate(salida)
        except Exception:
            continue
        clasificaciones.extend(salida.clasificaciones)

    validos = {
        (item.id_item, lista.cotizacion.id_oferta) for item, lista in candidatos
    }
    indice: dict[tuple[str, str], ClasificacionOfertaLLM] = {}
    for clasificacion in clasificaciones:
        clave = (clasificacion.id_item.strip(), clasificacion.id_oferta.strip())
        if clave not in validos or not clasificacion.motivo.strip():
            continue
        indice.setdefault(clave, clasificacion)
    return indice


def _contexto(candidatos: list[tuple[ItemSolicitado, _Lista]]) -> str:
    bloques: list[str] = []
    vistos: set[str] = set()
    for item, lista in candidatos:
        if item.id_item not in vistos:
            vistos.add(item.id_item)
            caracteristicas = ", ".join(item.caracteristicas) or "ninguna"
            bloques.append(
                "\n".join(
                    [
                        f"Producto {item.id_item}: {item.nombre}",
                        f"Marca exigida: {item.marca or 'ninguna'}",
                        f"Unidad pedida: {item.unidad or 'no dicha'}",
                        f"Acepta sustitutos: {'sí' if item.acepta_sustitutos else 'no'}",
                        f"Características: {caracteristicas}",
                        "Ofertas:",
                    ]
                )
            )
        oferta = lista.cotizacion
        bloques.append(
            "- "
            + " | ".join(
                [
                    f"id_item={item.id_item}",
                    f"id_oferta={oferta.id_oferta}",
                    oferta.nombre,
                    f"marca {oferta.marca or 'no informada'}",
                    f"presentación {oferta.presentacion or 'no informada'}",
                    f"contenido {oferta.cantidad} {oferta.unidad}",
                ]
            )
        )
    return "\n".join(bloques)


def _evaluar(
    item: ItemSolicitado,
    lista: _Lista,
    clasificacion: ClasificacionOfertaLLM | None,
) -> OfertaEvaluada:
    cotizacion = lista.cotizacion.model_copy(update={"id_item": item.id_item})
    if lista.exclusion is not None or clasificacion is None:
        motivo = lista.exclusion or "El clasificador no citó esta oferta con una relación válida."
        return _oferta(item.id_item, cotizacion, lista, "no_comparable", motivo, False, "reglas")

    relacion, motivo_extra = _ajustar_relacion(item, cotizacion, clasificacion.relacion)
    motivo = motivo_extra or clasificacion.motivo.strip()
    comparable = relacion in {"equivalente", "sustituto"}
    return _oferta(
        item.id_item,
        cotizacion,
        lista,
        relacion,
        motivo,
        comparable,
        "llm_validado",
    )


def _ajustar_relacion(
    item: ItemSolicitado,
    oferta: Cotizacion,
    relacion: Relacion,
) -> tuple[Relacion, str | None]:
    if relacion == "no_comparable":
        return relacion, None
    if relacion == "sustituto" and not item.marca and not item.caracteristicas:
        # Sin marca ni característica pedidas, otra marca o variedad común no
        # es un sustituto: es lo que la persona aceptó al pedir el producto en general.
        return "equivalente", "No pediste marca ni característica: se toma como equivalente."
    marca = _marca_coincide(item.marca, oferta.marca)
    if marca is False and relacion == "equivalente":
        if item.acepta_sustitutos:
            return "sustituto", "La marca es distinta, así que queda como sustituto."
        return "no_comparable", "La marca exigida no coincide."
    if marca is None and item.marca:
        return "no_comparable", "La oferta no informa la marca exigida."
    return relacion, None


def _oferta(
    id_item: str,
    cotizacion: Cotizacion,
    lista: _Lista,
    relacion: Relacion,
    motivo: str,
    cumple: bool,
    origen: str,
) -> OfertaEvaluada:
    return OfertaEvaluada(
        id_item=id_item,
        cotizacion=cotizacion,
        medida=lista.medida,
        precio_por_unidad_base=lista.precio_base,
        relacion=relacion,
        motivo=motivo,
        cumple_restricciones=cumple,
        origen=origen,  # type: ignore[arg-type]
    )


def _marca_coincide(exigida: str | None, oferta: str | None) -> bool | None:
    if not (exigida or "").strip():
        return True
    if not (oferta or "").strip():
        return None
    pedida = _plegar(exigida or "")
    publicada = _plegar(oferta or "")
    if pedida == publicada:
        return True
    return pedida in publicada.split() or publicada in pedida.split()


def _plegar(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))
    return " ".join(sin_tildes.lower().split())


def _linea_historial(grupos: list[GrupoItem]) -> str:
    partes = []
    for grupo in grupos:
        equivalentes = sum(oferta.relacion == "equivalente" for oferta in grupo.ofertas)
        partes.append(f"{grupo.id_item}: {equivalentes} equivalentes de {len(grupo.ofertas)}")
    detalle = ", ".join(partes) or "sin productos"
    return f"[normalizar] {detalle}"
