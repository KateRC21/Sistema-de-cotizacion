"""Tres presupuestos calculados en Python.

Se compra la presentación entera: si hacen falta 2 kg y la bolsa trae 500 g,
se cuentan cuatro bolsas. No se prorratea el precio de una bolsa cerrada.
El domicilio de estos catálogos no viene publicado, así que queda desconocido
y el total confirmado sigue vacío.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import pandas as pd

from compras.schemas import (
    CostoAdicional,
    EscenarioPresupuesto,
    GrupoItem,
    ItemSolicitado,
    LineaPresupuesto,
    OfertaEvaluada,
    Proveedor,
    SolicitudInterpretada,
    TipoEscenario,
)
from tools.calculos import normalizar_medida
from compras.carrito import empaques_necesarios
from compras.schemas import Cotizacion

_TIPOS: tuple[TipoEscenario, ...] = ("jumbo", "superboom", "combinado")
# A igual cobertura e igual total parcial, una sola tienda evita un segundo desplazamiento.
_PREFERENCIA = {"jumbo": 0, "superboom": 1, "combinado": 2}
# Mismo criterio que la comparación: equivalente, luego sustituto, luego precio.
_RELACION = {"equivalente": 0, "sustituto": 1, "no_comparable": 2}


def construir_escenarios(
    solicitud: SolicitudInterpretada,
    grupos: list[GrupoItem],
    elegidas: dict[str, Cotizacion] | None = None,
) -> list[EscenarioPresupuesto]:
    """Jumbo, Superboom y la combinación. Cada producto aparece una vez en cada uno.

    `elegidas` son las ofertas que la persona escogió: mandan en los escenarios
    de su tienda y en el combinado. En la otra tienda sigue la mejor automática.
    """
    por_item = {grupo.id_item: grupo.ofertas for grupo in grupos}
    return [
        _escenario(tipo, solicitud, por_item, elegidas or {})
        for tipo in _TIPOS
    ]


def elegir_oferta(
    item: ItemSolicitado,
    ofertas: list[OfertaEvaluada],
    proveedor: Proveedor | None = None,
) -> OfertaEvaluada | None:
    """La primera oferta que sí puede cubrir el pedido, con el mismo orden de la comparación."""
    candidatas = [
        oferta
        for oferta in ofertas
        if (proveedor is None or oferta.cotizacion.proveedor == proveedor)
        and _puede_cubrir(item, oferta)
    ]
    if not candidatas:
        return None
    return min(candidatas, key=lambda oferta: _clave_oferta(oferta, item))


def recomendar(
    escenarios: list[EscenarioPresupuesto],
) -> TipoEscenario | None:
    """Más productos cubiertos y, después, menor total parcial.

    Un escenario vacío no gana por tener total parcial 0.
    """
    if not escenarios or not any(_cubiertas(escenario) for escenario in escenarios):
        return None
    elegido = max(escenarios, key=_clave_recomendacion)
    return elegido.tipo


def tabla_comparacion(escenarios: list[EscenarioPresupuesto]) -> pd.DataFrame:
    """Costo de adquisición por producto y escenario. La celda vacía no es cero."""
    por_tipo = {escenario.tipo: escenario for escenario in escenarios}
    filas: list[dict[str, str]] = []
    vistos: set[str] = set()
    for tipo in _TIPOS:
        escenario = por_tipo.get(tipo)
        if escenario is None:
            continue
        for linea in escenario.lineas:
            if linea.id_item in vistos:
                continue
            vistos.add(linea.id_item)
            fila = {"producto": linea.nombre_solicitado}
            for columna in _TIPOS:
                fila[columna] = _texto_costo(por_tipo.get(columna), linea.id_item)
            filas.append(fila)
    return pd.DataFrame(filas, columns=["producto", "jumbo", "superboom", "combinado"])


def _escenario(
    tipo: TipoEscenario,
    solicitud: SolicitudInterpretada,
    por_item: dict[str, list[OfertaEvaluada]],
    elegidas: dict[str, Cotizacion],
) -> EscenarioPresupuesto:
    proveedor: Proveedor | None = None if tipo == "combinado" else tipo
    lineas = []
    for item in solicitud.items:
        ofertas = por_item.get(item.id_item, [])
        propia = elegidas.get(item.id_item)
        if propia is not None and (proveedor is None or propia.proveedor == proveedor):
            lineas.append(_linea_elegida(item, propia, ofertas))
        else:
            lineas.append(_linea(item, elegir_oferta(item, ofertas, proveedor)))
    subtotal = sum(
        (linea.costo_adquisicion for linea in lineas if linea.cubierta),
        Decimal("0"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    domicilio = CostoAdicional(concepto="domicilio", conocido=False, proveedor=proveedor)
    return EscenarioPresupuesto(
        tipo=tipo,
        lineas=lineas,
        productos_sin_cotizacion=[linea.id_item for linea in lineas if not linea.cubierta],
        subtotal_productos=subtotal,
        costos_adicionales=[domicilio],
        total_parcial=subtotal,
        total_confirmado=None,
    )


def _linea_elegida(
    item: ItemSolicitado,
    elegida: Cotizacion,
    ofertas: list[OfertaEvaluada],
) -> LineaPresupuesto:
    """Línea con la oferta que escogió la persona, aunque no sea la equivalente automática."""
    evaluada = next(
        (oferta for oferta in ofertas if oferta.cotizacion.id_oferta == elegida.id_oferta), None
    )
    if evaluada is not None and _puede_cubrir(item, evaluada):
        return _linea(item, evaluada)
    unidades = empaques_necesarios(item, elegida)
    costo = (Decimal(unidades) * elegida.precio).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    comparable = evaluada is not None and evaluada.relacion in ("equivalente", "sustituto")
    return LineaPresupuesto(
        id_item=item.id_item,
        nombre_solicitado=item.nombre,
        cubierta=True,
        id_oferta=elegida.id_oferta,
        proveedor=elegida.proveedor,
        nombre_oferta=elegida.nombre,
        presentacion=elegida.presentacion,
        precio_presentacion=elegida.precio,
        unidades_a_comprar=unidades,
        costo_adquisicion=costo,
        relacion=evaluada.relacion if comparable else "sustituto",
    )


def _linea(item: ItemSolicitado, oferta: OfertaEvaluada | None) -> LineaPresupuesto:
    if oferta is None or oferta.medida is None or oferta.precio_por_unidad_base is None:
        return LineaPresupuesto(id_item=item.id_item, nombre_solicitado=item.nombre, cubierta=False)
    pedida = _cantidad_pedida(item, oferta.medida.unidad)
    if pedida is None:
        return LineaPresupuesto(id_item=item.id_item, nombre_solicitado=item.nombre, cubierta=False)
    unidades = _empaques(pedida, oferta.medida.cantidad)
    costo = (Decimal(unidades) * oferta.cotizacion.precio).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return LineaPresupuesto(
        id_item=item.id_item,
        nombre_solicitado=item.nombre,
        cubierta=True,
        id_oferta=oferta.cotizacion.id_oferta,
        proveedor=oferta.cotizacion.proveedor,
        nombre_oferta=oferta.cotizacion.nombre,
        presentacion=oferta.cotizacion.presentacion,
        precio_presentacion=oferta.cotizacion.precio,
        precio_normalizado=oferta.precio_por_unidad_base,
        unidad_normalizada=oferta.medida.unidad,
        cantidad_requerida=pedida,
        unidades_a_comprar=unidades,
        costo_adquisicion=costo,
        relacion=oferta.relacion,
    )


def _puede_cubrir(item: ItemSolicitado, oferta: OfertaEvaluada) -> bool:
    if oferta.relacion == "no_comparable" or not oferta.cumple_restricciones:
        return False
    if oferta.relacion == "sustituto" and not item.acepta_sustitutos:
        return False
    if oferta.medida is None or oferta.precio_por_unidad_base is None:
        return False
    if oferta.cotizacion.disponibilidad != "disponible" or oferta.cotizacion.precio <= 0:
        return False
    return _cantidad_pedida(item, oferta.medida.unidad) is not None


def _cantidad_pedida(item: ItemSolicitado, unidad_base: str) -> Decimal | None:
    if item.cantidad is None or not (item.unidad or "").strip():
        return None
    medida = normalizar_medida(item.cantidad, item.unidad or "")
    if medida is None or medida.unidad != unidad_base:
        return None
    return medida.cantidad


def _empaques(pedida: Decimal, presentacion: Decimal) -> int:
    """Cuántas presentaciones completas cubren la cantidad pedida."""
    if presentacion <= 0:
        raise ValueError("La presentación debe ser mayor que cero.")
    return int((pedida / presentacion).to_integral_value(rounding=ROUND_CEILING))


def _costo_total(item: ItemSolicitado, oferta: OfertaEvaluada) -> Decimal:
    """Lo que cuesta cubrir lo pedido con esta oferta, en empaques enteros."""
    return oferta.cotizacion.precio * empaques_necesarios(item, oferta.cotizacion)


def _clave_oferta(oferta: OfertaEvaluada, item: ItemSolicitado) -> tuple:
    precio = oferta.precio_por_unidad_base
    return (
        _RELACION[oferta.relacion],
        _costo_total(item, oferta),
        precio is None,
        precio if precio is not None else Decimal("0"),
        oferta.cotizacion.proveedor,
        oferta.cotizacion.id_oferta,
    )


def _cubiertas(escenario: EscenarioPresupuesto) -> int:
    return sum(linea.cubierta for linea in escenario.lineas)


def _clave_recomendacion(escenario: EscenarioPresupuesto) -> tuple:
    return (
        _cubiertas(escenario),
        -escenario.total_parcial,
        -_PREFERENCIA[escenario.tipo],
    )


def _texto_costo(escenario: EscenarioPresupuesto | None, id_item: str) -> str:
    if escenario is None:
        return ""
    for linea in escenario.lineas:
        if linea.id_item == id_item and linea.cubierta and linea.costo_adquisicion is not None:
            return _plata(linea.costo_adquisicion)
    return ""


def _plata(monto: Decimal) -> str:
    valor = monto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if valor == valor.to_integral():
        return str(valor.to_integral())
    return format(valor, "f")
