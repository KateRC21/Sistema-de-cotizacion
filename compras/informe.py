"""Informe determinista. No recalcula precios: copia los escenarios ya cuadrados."""

from decimal import Decimal, ROUND_HALF_UP

from compras.presupuesto import recomendar, tabla_comparacion
from compras.routers import faltan_datos_esenciales
from compras.schemas import ErrorConsulta, EscenarioPresupuesto, EstadoCompra, Informe, TipoEscenario

_NOMBRE = {"jumbo": "Jumbo", "superboom": "Superboom", "combinado": "la compra combinada"}


def redactar_informe(state: EstadoCompra) -> Informe:
    """Arma el informe final. Una solicitud incompleta no trae escenario recomendado."""
    solicitud = state.solicitud
    if solicitud is None or faltan_datos_esenciales(solicitud):
        return _incompleto(state)

    escenarios = list(state.escenarios)
    if {escenario.tipo for escenario in escenarios} != {"jumbo", "superboom", "combinado"}:
        raise ValueError("El informe completo necesita los tres escenarios.")

    elegido = recomendar(escenarios)
    return Informe(
        resumen_solicitud=solicitud.resumen,
        suposiciones=list(state.suposiciones),
        escenarios=escenarios,
        recomendacion=_recomendacion(elegido, escenarios, state.errores_consulta, solicitud.proveedores),
        escenario_recomendado=elegido,
        fuentes=_fuentes(state, escenarios),
        solicitud_incompleta=False,
    )


def _incompleto(state: EstadoCompra) -> Informe:
    solicitud = state.solicitud
    if solicitud is None:
        resumen = "No hay una solicitud interpretada."
        faltan = ["solicitud"]
    else:
        resumen = solicitud.resumen
        faltan = faltan_datos_esenciales(solicitud)
    return Informe(
        resumen_solicitud=resumen,
        suposiciones=list(state.suposiciones),
        escenarios=[],
        recomendacion=(
            "La solicitud sigue incompleta "
            f"({', '.join(faltan)}). No se arma un presupuesto."
        ),
        escenario_recomendado=None,
        fuentes=["No se consultaron las tiendas porque faltan datos esenciales."],
        solicitud_incompleta=True,
    )


def _recomendacion(
    elegido: TipoEscenario | None,
    escenarios: list[EscenarioPresupuesto],
    errores: list[ErrorConsulta],
    proveedores: list[str],
) -> str:
    frases: list[str] = []
    if elegido is None:
        frases.append("Ningún escenario cubre los productos con una oferta utilizable.")
    else:
        escenario = next(item for item in escenarios if item.tipo == elegido)
        cubiertas = sum(linea.cubierta for linea in escenario.lineas)
        frases.append(
            f"Se recomienda {_NOMBRE[elegido]}: cubre {cubiertas} de {len(escenario.lineas)} productos."
        )
        frases.append(f"El total parcial es {_plata(escenario.total_parcial)} COP.")
        if escenario.productos_sin_cotizacion:
            frases.append(
                "Quedan sin cotización: " + ", ".join(escenario.productos_sin_cotizacion) + "."
            )
    frases.append(
        "El domicilio no viene en las fuentes consultadas, así que el total confirmado queda vacío."
    )
    if errores:
        tiendas = ", ".join(sorted({error.proveedor for error in errores}))
        detalle = "; ".join(error.mensaje for error in errores)
        frases.append(f"Errores de consulta en {tiendas}: {detalle}.")
    ausentes = [nombre for nombre in ("jumbo", "superboom") if nombre not in proveedores]
    if len(ausentes) == 1:
        frases.append(
            f"{_NOMBRE[ausentes[0]]} no estaba en la solicitud, así que ese escenario queda sin compras."
        )
    tabla = _tabla(escenarios)
    if tabla:
        frases.append(tabla)
    return " ".join(frases)


def _tabla(escenarios: list[EscenarioPresupuesto]) -> str:
    tabla = tabla_comparacion(escenarios)
    if tabla.empty:
        return ""
    visible = tabla.replace("", "sin cobertura")
    return "Comparación de costos de adquisición:\n" + visible.to_string(index=False)


def _fuentes(state: EstadoCompra, escenarios: list[EscenarioPresupuesto]) -> list[str]:
    usadas = {
        linea.id_oferta
        for escenario in escenarios
        for linea in escenario.lineas
        if linea.id_oferta
    }
    urls: list[str] = []
    for grupo in state.grupos:
        for oferta in grupo.ofertas:
            url = oferta.cotizacion.url_fuente
            if oferta.cotizacion.id_oferta in usadas and url not in urls:
                urls.append(url)
    if urls:
        return urls
    return ["No hubo ofertas utilizadas en Jumbo ni en Superboom."]


def _plata(monto: Decimal) -> str:
    valor = monto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if valor == valor.to_integral():
        return str(valor.to_integral())
    return format(valor, "f")
