"""Nodos del grafo. Cada uno devuelve solo los campos que actualiza."""

from compras.nodos.comparacion import crear_nodo_comparar
from compras.nodos.consulta import crear_nodo_consultar
from compras.nodos.interpretacion import completar_solicitud, crear_nodo_interpretar
from compras.nodos.normalizacion import crear_nodo_normalizar, evaluar_ofertas
from compras.nodos.presupuesto import crear_nodo_informar, crear_nodo_presupuestar
from compras.nodos.validacion import crear_nodo_aclarar, crear_nodo_cerrar, crear_nodo_validar

__all__ = [
    "completar_solicitud",
    "crear_nodo_aclarar",
    "crear_nodo_cerrar",
    "crear_nodo_comparar",
    "crear_nodo_consultar",
    "crear_nodo_informar",
    "crear_nodo_interpretar",
    "crear_nodo_presupuestar",
    "crear_nodo_normalizar",
    "crear_nodo_validar",
    "evaluar_ofertas",
]
