"""Rutas del grafo. No llaman a OpenAI ni a las tiendas."""

from datetime import date
from decimal import Decimal

from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from compras.grafo import construir_grafo, diagrama_mermaid
from compras.nodos.consulta import crear_nodo_consultar, termino_de_busqueda
from compras.nodos.validacion import aplicar_suposiciones, pregunta_aclaracion
from compras.routers import destino_tras_validar, proveedores_a_consultar
from compras.schemas import (
    ClasificacionEquivalenciasLLM,
    ClasificacionOfertaLLM,
    Cotizacion,
    EstadoCompra,
    ItemLLM,
    ItemSolicitado,
    ResultadoProveedor,
    SolicitudInterpretada,
    SolicitudLLM,
)

_FECHA = date(2026, 11, 13)
_CONTEXTOS: list[str] = []


def _config(hilo: str) -> dict:
    return {"configurable": {"thread_id": hilo}}


def _estado(valores: object) -> EstadoCompra:
    if isinstance(valores, EstadoCompra):
        return valores
    return EstadoCompra.model_validate(valores)


def _item_llm(**cambios: object) -> ItemLLM:
    datos: dict[str, object] = {
        "nombre": "Arroz",
        "cantidad": 2,
        "unidad": "kg",
        "marca": "Diana",
        "caracteristicas": [],
        "acepta_sustitutos": False,
    }
    datos.update(cambios)
    return ItemLLM.model_validate(datos)


def _solicitud_llm(texto: str) -> SolicitudLLM:
    completo = "kg" in texto.lower()
    proveedores: list[str] = []
    if "jumbo" in texto.lower() and "superboom" not in texto.lower():
        proveedores = ["jumbo"]
    elif "éxito" in texto.lower() or "exito" in texto.lower():
        proveedores = ["Éxito"]
    return SolicitudLLM(
        resumen="La persona pide arroz.",
        items=[
            _item_llm(
                cantidad=2 if completo else None,
                unidad="kg" if completo else None,
                marca=None if proveedores == ["Éxito"] else "Diana",
                acepta_sustitutos=proveedores == ["Éxito"],
            )
        ],
        ciudad="Medellín" if proveedores == ["Éxito"] else None,
        proveedores=proveedores,
        datos_faltantes=[] if completo else ["cantidad", "unidad"],
    )


def _interpretar(entrada: dict) -> SolicitudLLM:
    return _solicitud_llm(entrada["texto_usuario"])


def _clasificar(entrada: dict) -> ClasificacionEquivalenciasLLM:
    _CONTEXTOS.append(entrada["contexto"])
    clasificaciones = []
    for linea in entrada["contexto"].splitlines():
        if "id_oferta=" not in linea:
            continue
        datos: dict[str, str] = {}
        for fragmento in linea.split("|"):
            fragmento = fragmento.strip().removeprefix("-").strip()
            if "=" not in fragmento:
                continue
            clave, valor = fragmento.split("=", 1)
            datos[clave.strip()] = valor.strip()
        clasificaciones.append(
            ClasificacionOfertaLLM(
                id_item=datos["id_item"],
                id_oferta=datos["id_oferta"],
                relacion="equivalente",
                motivo="Misma clase de producto en la lista recibida.",
            )
        )
    return ClasificacionEquivalenciasLLM(clasificaciones=clasificaciones)


def _cotizacion(proveedor: str, id_oferta: str, *, precio: int, cantidad: str, unidad: str) -> Cotizacion:
    return Cotizacion(
        id_oferta=id_oferta,
        nombre="Arroz Diana 500 g" if unidad == "g" else "Arroz Diana 1 kg",
        marca="Diana",
        presentacion="bolsa",
        cantidad=cantidad,
        unidad=unidad,
        precio=precio,
        moneda="COP",
        proveedor=proveedor,  # type: ignore[arg-type]
        url_fuente=f"https://ejemplo.test/{proveedor}/{id_oferta}",
        fecha_consulta=_FECHA,
        disponibilidad="disponible",
        estado_verificacion="datos_de_prueba",
    )


def _consultas(fallo: str | None = None):
    llamadas: list[tuple[str, str, str | None]] = []

    def jumbo(termino: str, *, id_item: str | None = None, cliente=None):
        llamadas.append(("jumbo", termino, id_item))
        return ResultadoProveedor(
            proveedor="jumbo",
            ofertas=[
                _cotizacion(
                    "jumbo",
                    "jumbo-diana-500",
                    precio=2599,
                    cantidad="500",
                    unidad="g",
                ).model_copy(update={"id_item": id_item})
            ],
        )

    def superboom(termino: str, *, id_item: str | None = None, cliente=None):
        llamadas.append(("superboom", termino, id_item))
        if fallo == "superboom":
            raise RuntimeError("tiempo de espera")
        return ResultadoProveedor(
            proveedor="superboom",
            ofertas=[
                _cotizacion(
                    "superboom",
                    "superboom-diana-1kg",
                    precio=4000,
                    cantidad="1",
                    unidad="kg",
                ).model_copy(update={"id_item": id_item})
            ],
        )

    return llamadas, jumbo, superboom


def _grafo(fallo: str | None = None):
    llamadas, jumbo, superboom = _consultas(fallo)
    _CONTEXTOS.clear()
    grafo = construir_grafo(
        RunnableLambda(_interpretar),
        RunnableLambda(_clasificar),
        consultar_jumbo=jumbo,
        consultar_superboom=superboom,
        ciudad_defecto="Medellín",
        max_aclaraciones=3,
    )
    return grafo, llamadas


def test_el_router_no_modifica_el_estado_y_cuenta_las_rondas() -> None:
    solicitud = SolicitudInterpretada(
        resumen="Arroz sin cantidad.",
        items=[ItemSolicitado(id_item="item-1", nombre="Arroz")],
    )
    estado = EstadoCompra(solicitud=solicitud)
    assert destino_tras_validar(estado, max_aclaraciones=3) == "aclarar"
    assert destino_tras_validar(
        estado.model_copy(update={"rondas_aclaracion": 3}),
        max_aclaraciones=3,
    ) == "cerrar"
    assert estado.rondas_aclaracion == 0
    assert estado.solicitud is solicitud
    assert "cantidad" in pregunta_aclaracion(solicitud)


def test_sin_tienda_ni_ciudad_se_registran_suposiciones_y_no_se_inventa_cantidad() -> None:
    solicitud = SolicitudInterpretada(
        resumen="Arroz.",
        items=[ItemSolicitado(id_item="item-1", nombre="Arroz", cantidad=Decimal("1"), unidad="kg")],
        datos_faltantes=["proveedor no disponible: éxito"],
    )
    nueva, suposiciones = aplicar_suposiciones(solicitud, ciudad_defecto="Medellín")
    assert nueva.ciudad == "Medellín"
    assert nueva.proveedores == ["jumbo", "superboom"]
    assert nueva.items[0].cantidad == Decimal("1")
    assert {item.campo for item in suposiciones} == {"ciudad", "proveedores"}
    assert "no está disponible" in suposiciones[1].motivo
    assert proveedores_a_consultar(EstadoCompra(solicitud=nueva)) == ["jumbo", "superboom"]


def test_la_busqueda_incluye_la_marca_exigida() -> None:
    item = ItemSolicitado(id_item="item-1", nombre="Arroz", marca="Diana", cantidad=Decimal("2"), unidad="kg")
    assert termino_de_busqueda(item) == "Arroz Diana"


def test_un_producto_fallido_no_borra_las_ofertas_del_otro() -> None:
    def consultar(termino: str, *, id_item: str | None = None, cliente=None):
        if id_item == "item-2":
            raise RuntimeError("caída")
        return ResultadoProveedor(
            proveedor="jumbo",
            ofertas=[_cotizacion("jumbo", "jumbo-arroz", precio=2500, cantidad="1", unidad="kg")],
        )

    solicitud = SolicitudInterpretada(
        resumen="Arroz y leche.",
        items=[
            ItemSolicitado(id_item="item-1", nombre="Arroz", cantidad=Decimal("2"), unidad="kg"),
            ItemSolicitado(id_item="item-2", nombre="Leche", cantidad=Decimal("1"), unidad="l"),
        ],
        ciudad="Medellín",
        proveedores=["jumbo"],
    )
    salida = crear_nodo_consultar("jumbo", consultar)(EstadoCompra(solicitud=solicitud))
    resultado = salida["resultados_proveedor"][0]
    assert [oferta.id_oferta for oferta in resultado.ofertas] == ["jumbo-arroz"]
    assert resultado.errores[0].id_item == "item-2"
    assert "caída" in resultado.errores[0].mensaje


def test_flujo_completo_consulta_en_paralelo_y_ordena_por_precio_base() -> None:
    grafo, llamadas = _grafo()
    resultado = _estado(grafo.invoke(EstadoCompra(texto_usuario="2 kg de arroz Diana"), _config("completo")))
    assert not grafo.get_state(_config("completo")).interrupts
    assert resultado.solicitud is not None
    assert resultado.solicitud.ciudad == "Medellín"
    assert resultado.solicitud.proveedores == ["jumbo", "superboom"]
    assert {item.campo for item in resultado.suposiciones} == {"ciudad", "proveedores"}
    assert {llamada[0] for llamada in llamadas} == {"jumbo", "superboom"}
    assert all(llamada[2] == "item-1" for llamada in llamadas)
    assert "2599" not in _CONTEXTOS[0]
    assert "COP" not in _CONTEXTOS[0]
    assert {oferta.proveedor for oferta in resultado.ofertas} == {"jumbo", "superboom"}
    primera = resultado.grupos[0].ofertas[0]
    assert primera.relacion == "equivalente"
    assert primera.cotizacion.proveedor == "superboom"
    assert primera.precio_por_unidad_base == Decimal("4000.00")
    texto = " ".join(resultado.historial)
    assert "[interpretar]" in texto
    assert "[consolidar]" in texto
    assert "[comparar]" in texto
    assert "[presupuesto]" in texto
    assert "[informe]" in texto
    assert "[cerrar]" not in texto
    assert resultado.informe is not None
    assert resultado.informe.escenario_recomendado == "superboom"
    superboom = next(escenario for escenario in resultado.informe.escenarios if escenario.tipo == "superboom")
    jumbo = next(escenario for escenario in resultado.informe.escenarios if escenario.tipo == "jumbo")
    assert superboom.lineas[0].unidades_a_comprar == 2
    assert superboom.total_parcial == Decimal("8000.00")
    assert superboom.total_confirmado is None
    assert superboom.costos_adicionales[0].monto is None
    assert jumbo.lineas[0].unidades_a_comprar == 4
    assert jumbo.lineas[0].costo_adquisicion == Decimal("10396.00")


def test_solo_jumbo_no_llama_a_superboom() -> None:
    grafo, llamadas = _grafo()
    resultado = _estado(
        grafo.invoke(EstadoCompra(texto_usuario="2 kg de arroz Diana en Jumbo"), _config("solo-jumbo"))
    )
    assert [llamada[0] for llamada in llamadas] == ["jumbo"]
    assert resultado.solicitud is not None
    assert resultado.solicitud.proveedores == ["jumbo"]
    assert "proveedores" not in {item.campo for item in resultado.suposiciones}
    assert resultado.solicitud.ciudad == "Medellín"


def test_una_tienda_caida_conserva_las_ofertas_de_la_otra() -> None:
    grafo, llamadas = _grafo(fallo="superboom")
    resultado = _estado(grafo.invoke(EstadoCompra(texto_usuario="2 kg de arroz Diana"), _config("caida")))
    assert {llamada[0] for llamada in llamadas} == {"jumbo", "superboom"}
    assert [oferta.proveedor for oferta in resultado.ofertas] == ["jumbo"]
    assert resultado.errores_consulta[0].proveedor == "superboom"
    assert "tiempo de espera" in resultado.errores_consulta[0].mensaje
    assert resultado.grupos[0].ofertas[0].cotizacion.proveedor == "jumbo"
    assert any(grupo.ofertas for grupo in resultado.grupos)


def test_la_tienda_no_disponible_se_reemplaza_con_suposicion() -> None:
    grafo, llamadas = _grafo()
    resultado = _estado(
        grafo.invoke(EstadoCompra(texto_usuario="2 kg de arroz en Éxito, Medellín"), _config("exito"))
    )
    assert resultado.solicitud is not None
    assert resultado.solicitud.proveedores == ["jumbo", "superboom"]
    assert resultado.solicitud.ciudad == "Medellín"
    motivos = [item.motivo for item in resultado.suposiciones]
    assert any("no está disponible" in motivo for motivo in motivos)
    assert not any(item.campo == "ciudad" for item in resultado.suposiciones)
    assert {llamada[0] for llamada in llamadas} == {"jumbo", "superboom"}


def test_falta_la_cantidad_pausa_y_al_reanudar_consulta() -> None:
    grafo, llamadas = _grafo()
    config = _config("pausa")
    grafo.invoke(EstadoCompra(texto_usuario="arroz Diana"), config)
    pausa = grafo.get_state(config)
    assert pausa.interrupts
    pregunta = pausa.interrupts[0].value["pregunta"]
    assert "cantidad" in pregunta
    assert llamadas == []

    resultado = _estado(grafo.invoke(Command(resume="2 kg"), config))
    assert not grafo.get_state(config).interrupts
    assert resultado.rondas_aclaracion == 1
    assert resultado.mensajes_aclaracion == ["2 kg"]
    assert resultado.solicitud is not None
    assert resultado.solicitud.items[0].cantidad == Decimal("2")
    assert {llamada[0] for llamada in llamadas} == {"jumbo", "superboom"}


def test_tras_tres_aclaraciones_inutiles_no_consulta_ni_inventa() -> None:
    grafo, llamadas = _grafo()
    config = _config("incompleta")
    grafo.invoke(EstadoCompra(texto_usuario="arroz"), config)
    for respuesta in ("no sé", "tampoco", "nada"):
        assert grafo.get_state(config).interrupts
        grafo.invoke(Command(resume=respuesta), config)

    assert not grafo.get_state(config).interrupts
    resultado = _estado(grafo.get_state(config).values)
    assert resultado.rondas_aclaracion == 3
    assert resultado.mensajes_aclaracion == ["no sé", "tampoco", "nada"]
    assert resultado.solicitud is not None
    assert resultado.solicitud.items[0].cantidad is None
    assert resultado.ofertas == []
    assert llamadas == []
    assert resultado.informe is not None
    assert resultado.informe.solicitud_incompleta is True
    assert resultado.informe.escenario_recomendado is None
    assert resultado.informe.escenarios == []
    assert any(linea.startswith("[cerrar]") for linea in resultado.historial)


def test_el_diagrama_incluye_la_pausa_y_las_dos_tiendas() -> None:
    grafo, _ = _grafo()
    diagrama = diagrama_mermaid(grafo)
    for nombre in (
        "interpretar",
        "validar",
        "aclarar",
        "jumbo",
        "superboom",
        "consolidar",
        "normalizar",
        "comparar",
        "presupuesto",
        "informe",
        "cerrar",
    ):
        assert nombre in diagrama
