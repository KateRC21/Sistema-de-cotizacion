"""Punto de entrada por línea de comandos.

Uso:
    uv run python main.py
    uv run python main.py --interpretar "2 kg de arroz Diana en Jumbo"
    uv run python main.py --mermaid
"""

import argparse
from pathlib import Path

from compras.config import cargar_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Asistente de compras Jumbo y Superboom")
    parser.add_argument(
        "--interpretar",
        metavar="TEXTO",
        help="Interpreta una solicitud con OpenAI y termina.",
    )
    parser.add_argument(
        "--mermaid",
        action="store_true",
        help="Imprime el grafo y lo guarda en docs/grafo.mmd. No llama a OpenAI ni a las tiendas.",
    )
    args = parser.parse_args()
    if args.mermaid:
        _mermaid()
        return
    if args.interpretar:
        _interpretar(args.interpretar)
        return
    _mostrar_configuracion()


def _mostrar_configuracion() -> None:
    config = cargar_config()
    clave = "configurada" if config.api_key else "ausente"
    print("Asistente de compras — configuración")
    print(f"Modelo            : {config.modelo}")
    print(f"Temperatura       : {config.temperatura}")
    print(f"Clave OpenAI      : {clave}")
    print(f"Fuente Jumbo      : {config.fuente_jumbo} (catálogo público)")
    print(f"Fuente Superboom  : {config.fuente_superboom} (catálogo público)")
    print(f"Ciudad por defecto: {config.ciudad_defecto}")
    print(f"Resultados máx.   : {config.catalogo_max_resultados}")
    print(f"Pausa entre consultas: {config.catalogo_pausa} s")


def _texto_cantidad(cantidad) -> str:
    if cantidad == cantidad.to_integral():
        return str(cantidad.to_integral())
    return format(cantidad.normalize(), "f")


def _mermaid() -> None:
    from langchain_core.runnables import RunnableLambda

    from compras.grafo import construir_grafo, diagrama_mermaid

    def no_ejecutar(_: object) -> object:
        raise RuntimeError("El diagrama no ejecuta el modelo ni las tiendas.")

    texto = diagrama_mermaid(
        construir_grafo(RunnableLambda(no_ejecutar), RunnableLambda(no_ejecutar))
    )
    destino = Path(__file__).resolve().parent / "docs" / "grafo.mmd"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(texto if texto.endswith("\n") else texto + "\n", encoding="utf-8")
    print(texto)
    print(f"Diagrama guardado en {destino}")


def _interpretar(texto: str) -> None:
    from compras.llm import construir_interpretador
    from compras.nodos.interpretacion import crear_nodo_interpretar
    from compras.schemas import EstadoCompra

    nodo = crear_nodo_interpretar(construir_interpretador())
    solicitud = nodo(EstadoCompra(texto_usuario=texto))["solicitud"]
    print(solicitud.resumen)
    print(f"Ciudad: {solicitud.ciudad or 'no dicha'}")
    print(f"Tiendas: {', '.join(solicitud.proveedores) or 'no dichas'}")
    print(f"Faltantes: {', '.join(solicitud.datos_faltantes) or 'ninguno'}")
    for item in solicitud.items:
        marca = item.marca or "sin marca exigida"
        cantidad = _texto_cantidad(item.cantidad) if item.cantidad is not None else "sin cantidad"
        unidad = item.unidad or "sin unidad"
        sustituto = "acepta sustitutos" if item.acepta_sustitutos else "sin sustitutos"
        print(f"- {item.id_item}: {item.nombre} | {cantidad} {unidad} | {marca} | {sustituto}")


if __name__ == "__main__":
    main()
