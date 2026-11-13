"""Grafo de la compra.

interpretar → validar → aclarar (y volver a interpretar) o consultar Jumbo y
Superboom en paralelo → consolidar → normalizar → comparar → presupuesto → informe.

Una solicitud que sigue incompleta pasa de cerrar al informe, sin llamar a las tiendas.
"""

from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import BaseModel

import compras.schemas as esquemas

from compras.nodos.comparacion import crear_nodo_comparar
from compras.nodos.consolidacion import consolidar
from compras.nodos.consulta import Consultor, crear_nodo_consultar
from compras.nodos.interpretacion import crear_nodo_interpretar
from compras.nodos.normalizacion import crear_nodo_normalizar
from compras.nodos.presupuesto import crear_nodo_informar, crear_nodo_presupuestar
from compras.nodos.validacion import crear_nodo_aclarar, crear_nodo_cerrar, crear_nodo_validar
from compras.routers import destino_tras_validar, proveedores_a_consultar
from compras.schemas import EstadoCompra
from tools.jumbo import consultar_jumbo as consultar_jumbo_web
from tools.superboom import consultar_superboom as consultar_superboom_web


def construir_grafo(
    interpretador: Runnable,
    clasificador: Runnable,
    *,
    consultar_jumbo: Consultor = consultar_jumbo_web,
    consultar_superboom: Consultor = consultar_superboom_web,
    ciudad_defecto: str = "Medellín",
    max_aclaraciones: int = 3,
    checkpointer: MemorySaver | None = None,
) -> CompiledStateGraph:
    """Compila el grafo. Las pruebas inyectan el LLM y las consultas.

    Siempre lleva checkpointer: interrupt() lo exige para poder reanudar.
    """
    grafo = StateGraph(EstadoCompra)
    grafo.add_node("interpretar", crear_nodo_interpretar(interpretador))
    grafo.add_node("validar", crear_nodo_validar(ciudad_defecto))
    grafo.add_node("aclarar", crear_nodo_aclarar(max_aclaraciones))
    grafo.add_node("jumbo", crear_nodo_consultar("jumbo", consultar_jumbo))
    grafo.add_node("superboom", crear_nodo_consultar("superboom", consultar_superboom))
    grafo.add_node("consolidar", consolidar)
    grafo.add_node("normalizar", crear_nodo_normalizar(clasificador))
    grafo.add_node("comparar", crear_nodo_comparar())
    grafo.add_node("presupuesto", crear_nodo_presupuestar())
    grafo.add_node("informe", crear_nodo_informar())
    grafo.add_node("cerrar", crear_nodo_cerrar())

    grafo.add_edge(START, "interpretar")
    grafo.add_edge("interpretar", "validar")
    grafo.add_conditional_edges(
        "validar",
        _enrutar_validacion(max_aclaraciones),
        ["aclarar", "cerrar", "jumbo", "superboom"],
    )
    grafo.add_edge("aclarar", "interpretar")
    grafo.add_edge("jumbo", "consolidar")
    grafo.add_edge("superboom", "consolidar")
    grafo.add_edge("consolidar", "normalizar")
    grafo.add_edge("normalizar", "comparar")
    grafo.add_edge("comparar", "presupuesto")
    grafo.add_edge("presupuesto", "informe")
    grafo.add_edge("cerrar", "informe")
    grafo.add_edge("informe", END)

    return grafo.compile(checkpointer=checkpointer or _memoria())


def _memoria() -> MemorySaver:
    """Checkpointer que puede reanudar los modelos de este proyecto."""
    modelos: list[type[BaseModel]] = []
    for objeto in vars(esquemas).values():
        if not isinstance(objeto, type):
            continue
        try:
            if issubclass(objeto, BaseModel):
                modelos.append(objeto)
        except TypeError:
            continue
    return MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=tuple(modelos)))


def diagrama_mermaid(grafo: CompiledStateGraph) -> str:
    return grafo.get_graph().draw_mermaid()


def _enrutar_validacion(max_aclaraciones: int):
    def enrutar(state: EstadoCompra) -> str | list[Send]:
        destino = destino_tras_validar(state, max_aclaraciones=max_aclaraciones)
        if destino != "consultar":
            return destino
        datos = state.model_dump()
        envios = [Send(proveedor, datos) for proveedor in proveedores_a_consultar(state)]
        return envios or "cerrar"

    return enrutar
