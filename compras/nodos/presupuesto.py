"""Nodos de presupuesto e informe. Leen los grupos ya comparados."""

from compras.informe import redactar_informe
from compras.presupuesto import construir_escenarios
from compras.routers import faltan_datos_esenciales
from compras.schemas import EstadoCompra


def crear_nodo_presupuestar():
    def presupuestar(state: EstadoCompra) -> dict:
        solicitud = state.solicitud
        if solicitud is None or faltan_datos_esenciales(solicitud):
            return {"historial": ["[presupuesto] Solicitud incompleta. No se calculan escenarios."]}
        escenarios = construir_escenarios(solicitud, state.grupos)
        partes = []
        for escenario in escenarios:
            cubiertas = sum(linea.cubierta for linea in escenario.lineas)
            partes.append(
                f"{escenario.tipo} cubre {cubiertas}/{len(escenario.lineas)}, "
                f"parcial {escenario.total_parcial} COP"
            )
        return {"escenarios": escenarios, "historial": ["[presupuesto] " + "; ".join(partes)]}

    return presupuestar


def crear_nodo_informar():
    def informar(state: EstadoCompra) -> dict:
        informe = redactar_informe(state)
        if informe.solicitud_incompleta:
            linea = "[informe] solicitud incompleta"
        else:
            linea = f"[informe] recomendado={informe.escenario_recomendado or 'ninguno'}"
        return {"informe": informe, "historial": [linea]}

    return informar
