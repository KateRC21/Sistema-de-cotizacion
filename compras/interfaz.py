"""Textos y tablas para la pantalla. No consulta tiendas ni llama al modelo."""

from decimal import Decimal, ROUND_HALF_UP

from compras.presupuesto import tabla_comparacion
from compras.schemas import EscenarioPresupuesto, EstadoCompra, Informe

_NOMBRE = {"jumbo": "Jumbo", "superboom": "Superboom", "combinado": "Combinado"}


def ejecutar_turno(grafo, config: dict, entrada) -> tuple[EstadoCompra, object | None]:
    """Avanza el grafo. Si está en pausa, devuelve el valor de interrupt()."""
    grafo.invoke(entrada, config)
    foto = grafo.get_state(config)
    valores = foto.values
    if isinstance(valores, EstadoCompra):
        estado = valores
    else:
        estado = EstadoCompra.model_validate(valores or {})
    if foto.interrupts:
        return estado, foto.interrupts[0].value
    return estado, None


def detalle_pausa(valor: object) -> tuple[str, str | None]:
    """Pregunta visible y, si viene, el número de aclaración."""
    if isinstance(valor, dict):
        pregunta = str(valor.get("pregunta") or "Hace falta un dato para continuar.")
        if valor.get("ronda") and valor.get("maximo"):
            return pregunta, f"Aclaración {valor['ronda']} de {valor['maximo']}"
        return pregunta, None
    return str(valor), None


def prosa_recomendacion(informe: Informe) -> str:
    """La recomendación sin la tabla de texto: la pantalla muestra la tabla aparte."""
    marca = "Comparación de costos de adquisición:"
    return informe.recomendacion.split(marca, 1)[0].strip()


def tabla_visible(escenarios: list[EscenarioPresupuesto]):
    """La celda sin oferta dice «sin cobertura» y no muestra un cero."""
    tabla = tabla_comparacion(escenarios)
    if tabla.empty:
        return tabla
    return tabla.replace("", "sin cobertura")


def filas_detalle(escenario: EscenarioPresupuesto, fuentes: dict[str, str]) -> list[dict[str, str]]:
    """Filas de un escenario. Una línea descubierta no lleva costo."""
    filas: list[dict[str, str]] = []
    for linea in escenario.lineas:
        if not linea.cubierta or linea.costo_adquisicion is None:
            filas.append(
                {
                    "Producto": linea.nombre_solicitado,
                    "Oferta": "sin cobertura",
                    "Presentación": "",
                    "Empaques": "",
                    "Costo COP": "",
                    "Relación": "",
                    "Fuente": "",
                }
            )
            continue
        filas.append(
            {
                "Producto": linea.nombre_solicitado,
                "Oferta": linea.nombre_oferta or linea.id_oferta or "",
                "Presentación": linea.presentacion or "",
                "Empaques": str(linea.unidades_a_comprar or ""),
                "Costo COP": plata(linea.costo_adquisicion),
                "Relación": linea.relacion or "",
                "Fuente": fuentes.get(linea.id_oferta or "", ""),
            }
        )
    return filas


def indice_fuentes(estado: EstadoCompra) -> dict[str, str]:
    indice: dict[str, str] = {}
    for grupo in estado.grupos:
        for oferta in grupo.ofertas:
            indice[oferta.cotizacion.id_oferta] = oferta.cotizacion.url_fuente
    return indice


def nombre_escenario(tipo: str) -> str:
    return _NOMBRE.get(tipo, tipo)


def plata(monto: Decimal) -> str:
    valor = monto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if valor == valor.to_integral():
        return str(valor.to_integral())
    return format(valor, "f")
