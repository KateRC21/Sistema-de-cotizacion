"""Pantalla Streamlit del asistente.

La página no consulta Jumbo, Superboom ni OpenAI hasta que se envía una
solicitud. Si falta la cantidad o la unidad, el grafo se reanuda desde aquí.
"""

from uuid import uuid4

import pandas as pd
import streamlit as st
from langgraph.types import Command

from compras.informe import redactar_informe
from compras.presupuesto import construir_escenarios
from compras.carrito import (
    armar_carrito,
    recomendada,
    enlaces_busqueda_manual,
    opciones_por_item,
    subtotal_por_tienda,
)
from compras.aclaracion import preparar_propuesta, texto_productos
from compras.config import cargar_config
from compras.grafo import construir_grafo
from compras.interfaz import (
    detalle_pausa,
    ejecutar_turno,
    filas_detalle,
    indice_fuentes,
    nombre_escenario,
    plata,
    prosa_recomendacion,
    tabla_visible,
)
from compras.llm import (
    construir_clasificador_equivalencias,
    construir_facilitador_aclaraciones,
    construir_interpretador,
)
from compras.schemas import EstadoCompra


def obtener_grafo_real():
    """Grafo con el modelo y los catálogos públicos configurados en .env."""
    config = cargar_config()
    return construir_grafo(
        construir_interpretador(),
        construir_clasificador_equivalencias(),
        ciudad_defecto=config.ciudad_defecto,
        max_aclaraciones=config.max_aclaraciones,
        suponer_cantidad=True,
    )


def render(obtener_grafo=obtener_grafo_real, facilitar=None) -> None:
    st.set_page_config(page_title="Asistente de compras", layout="wide")
    _asegurar_estado()
    st.title("Asistente de compras")
    st.caption(
        "Compara Jumbo y Superboom para alimentos, aseo y hogar. "
        "Los precios son los del sitio web en la fecha de consulta. "
        "El domicilio no viene en esas fuentes, así que el total confirmado queda vacío."
    )

    with st.expander("¿Cómo pedir? Unidades que entiendo", expanded=False):
        st.markdown(
            "Puedes pedir por **kilos, libras, gramos, litros, mililitros, unidades, "
            "docenas** o por **paquete, bolsa, caja, botella, lata o frasco**.\n\n"
            "- **Conversiones automáticas:** 1 libra = 500 g, 1 kg = 1000 g, "
            "1 litro = 1000 ml y 1 docena = 12 unidades. Así comparo tiendas aunque "
            "vendan en presentaciones distintas.\n"
            "- **Si pides por empaque** («1 paquete de galletas»), comparo el precio de "
            "cada paquete sin importar su peso.\n"
            "- **Más abajo, en «Elige otras opciones»,** puedes cambiar el producto "
            "recomendado por otro. Los presupuestos y el carrito se actualizan solos.\n"
            "- **Si no dices la cantidad**, busco 1 empaque y lo anoto en «Suposiciones». "
            "Puedes cambiarla en el carrito.\n"
            "- Ejemplo: *2 kg de arroz, 1 libra de queso, 1 docena de huevos y 1 paquete de galletas*."
        )

    texto = st.text_area(
        "¿Qué necesitas comprar?",
        placeholder="2 kg de arroz, 1 libra de queso, 1 docena de huevos y 1 paquete de galletas",
        key="solicitud",
    )
    if st.button("Consultar", key="consultar", type="primary"):
        _consultar(obtener_grafo, texto)

    if st.session_state.pregunta:
        _formulario_aclaracion(facilitar)

    if st.session_state.error:
        st.error(st.session_state.error)

    estado = st.session_state.estado
    if estado is not None and estado.informe is not None and not st.session_state.pregunta:
        _mostrar(estado)


def _asegurar_estado() -> None:
    valores = {
        "hilo": None,
        "grafo": None,
        "pregunta": None,
        "ronda": None,
        "pausa": None,
        "propuesta": None,
        "facilitador": None,
        "estado": None,
        "elegidas": {},
        "error": None,
    }
    for clave, valor in valores.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


def _consultar(obtener_grafo, texto: str) -> None:
    st.session_state.error = None
    if not texto or not texto.strip():
        st.warning("Escribe el producto, la cantidad y la unidad.")
        return
    if st.session_state.grafo is None:
        try:
            st.session_state.grafo = obtener_grafo()
        except RuntimeError as exc:
            st.session_state.error = str(exc)
            return
    st.session_state.hilo = str(uuid4())
    st.session_state.pregunta = None
    st.session_state.ronda = None
    st.session_state.pausa = None
    st.session_state.propuesta = None
    st.session_state.estado = None
    st.session_state.elegidas = {}
    _turno(EstadoCompra(texto_usuario=texto.strip()))


def _formulario_aclaracion(facilitar) -> None:
    if st.session_state.ronda:
        st.caption(st.session_state.ronda)
    st.warning(st.session_state.pregunta)
    if st.session_state.propuesta is not None:
        _confirmar_propuesta()
        return
    respuesta = st.text_input(
        "Tu respuesta",
        placeholder="Por ejemplo: 2 kg",
        key="aclaracion",
    )
    if st.button("Revisar con el modelo", key="revisar"):
        _revisar_respuesta(facilitar, respuesta)


def _revisar_respuesta(facilitar, respuesta: str) -> None:
    st.session_state.error = None
    if not respuesta or not respuesta.strip():
        st.warning("Escribe el dato que falta.")
        return
    try:
        if st.session_state.facilitador is None:
            st.session_state.facilitador = facilitar or construir_facilitador_aclaraciones()
        salida = st.session_state.facilitador.invoke(_contexto_aclaracion(respuesta.strip()))
        st.session_state.propuesta = preparar_propuesta(salida, _faltantes())
    except Exception as exc:
        st.session_state.error = f"No se pudo revisar la respuesta: {exc}"
        return
    st.rerun()


def _confirmar_propuesta() -> None:
    propuesta = st.session_state.propuesta
    st.info(propuesta.resumen)
    if propuesta.texto_confirmado:
        st.markdown("**Corrección que se enviaría al asistente:**")
        st.text(propuesta.texto_confirmado)
    if propuesta.productos:
        st.markdown("**Así quedarían los productos:**")
        st.text(texto_productos(propuesta.productos))
    if not propuesta.suficiente:
        st.warning(
            "Con esa respuesta todavía no queda la cantidad o la unidad. "
            "Puedes reformularla. Esta revisión no gasta un intento."
        )
        if st.button("Escribir otra respuesta", key="reintentar"):
            st.session_state.propuesta = None
            st.rerun()
        return
    st.caption("Comprueba que esa sea la corrección. Si no lo es, no continúa la consulta.")
    aceptar, rechazar = st.columns(2)
    if aceptar.button("Sí, es correcto", key="confirmar", type="primary"):
        texto = propuesta.texto_confirmado
        st.session_state.propuesta = None
        _turno(Command(resume=texto))
    if rechazar.button("No, la corrijo", key="rechazar"):
        st.session_state.propuesta = None
        st.rerun()


def _contexto_aclaracion(respuesta: str) -> dict[str, str]:
    estado = st.session_state.estado
    lineas = []
    if estado is not None and estado.solicitud is not None:
        for item in estado.solicitud.items:
            lineas.append(
                f"{item.nombre} | cantidad={item.cantidad} | unidad={item.unidad or 'null'}"
            )
    return {
        "solicitud": estado.texto_usuario if estado is not None else "",
        "productos": "\n".join(lineas) or "ninguno",
        "faltantes": ", ".join(_faltantes()) or "cantidad, unidad",
        "pregunta": st.session_state.pregunta or "",
        "respuesta": respuesta,
    }


def _faltantes() -> list[str]:
    pausa = st.session_state.pausa
    if isinstance(pausa, dict) and isinstance(pausa.get("faltantes"), list):
        return [str(dato) for dato in pausa["faltantes"]]
    return ["cantidad", "unidad"]


def _turno(entrada) -> None:
    config = {"configurable": {"thread_id": st.session_state.hilo}}
    try:
        with st.spinner("Consultando Jumbo y Superboom. Con varios productos puede tardar cerca de un minuto..."):
            estado, pausa = ejecutar_turno(st.session_state.grafo, config, entrada)
    except Exception as exc:
        st.session_state.error = f"No se pudo completar la consulta: {exc}"
        return
    st.session_state.estado = estado
    st.session_state.propuesta = None
    if pausa is None:
        st.session_state.pregunta = None
        st.session_state.ronda = None
        st.session_state.pausa = None
    else:
        pregunta, ronda = detalle_pausa(pausa)
        st.session_state.pregunta = pregunta
        st.session_state.ronda = ronda
        st.session_state.pausa = pausa if isinstance(pausa, dict) else {"pregunta": str(pausa)}
    st.rerun()


def _preparar_seleccion(estado: EstadoCompra) -> tuple[dict, dict, dict]:
    """Preselecciona la oferta recomendada. No dibuja nada.

    Devuelve las opciones por producto, las recomendadas y las ofertas elegidas.
    """
    opciones = opciones_por_item(estado)
    elegidas = st.session_state.elegidas
    recomendadas: dict[str, tuple] = {}
    for item in estado.solicitud.items:
        sugerida = recomendada(estado, item.id_item)
        if sugerida is not None:
            recomendadas[item.id_item] = sugerida
            elegidas.setdefault(item.id_item, sugerida[0].id_oferta)
            lista = opciones.get(item.id_item, [])
            if all(o.id_oferta != sugerida[0].id_oferta for o in lista):
                opciones[item.id_item] = [sugerida[0], *lista]

    por_id = {oferta.id_oferta: oferta for lista in opciones.values() for oferta in lista}
    escogidas = {
        id_item: por_id[id_oferta]
        for id_item, id_oferta in elegidas.items()
        if id_oferta in por_id
    }
    return opciones, recomendadas, escogidas


def _otras_opciones(estado: EstadoCompra, opciones: dict, recomendadas: dict) -> None:
    """Todas las ofertas con foto, para cambiar la recomendada."""
    elegidas = st.session_state.elegidas
    st.header("Elige otras opciones")
    st.caption(
        "Ya elegimos la que más se adapta a lo que pediste. "
        "Si prefieres otra, pulsa «Elegir»: de la más barata a la más cara."
    )
    for item in estado.solicitud.items:
        st.subheader(item.nombre)
        lista = opciones.get(item.id_item, [])
        if not lista:
            st.info("Ninguna tienda consultada tiene este producto disponible.")
        sugerida = recomendadas.get(item.id_item)
        if sugerida is None and lista:
            st.caption("No hay una opción equivalente clara: escoge la que prefieras.")
        for inicio in range(0, len(lista), 4):
            columnas = st.columns(4)
            for columna, oferta in zip(columnas, lista[inicio : inicio + 4]):
                with columna:
                    if oferta.url_imagen:
                        st.image(oferta.url_imagen, use_container_width=True)
                    if sugerida is not None and oferta.id_oferta == sugerida[0].id_oferta:
                        st.markdown("⭐ **Recomendada**")
                    st.markdown(f"**{oferta.nombre}**")
                    st.caption(f"{nombre_escenario(oferta.proveedor)} · {oferta.presentacion or 'presentación no informada'}")
                    st.markdown(f"### {plata(oferta.precio)} COP")
                    st.markdown(f"[Ver en la tienda]({oferta.url_fuente})")
                    elegida = elegidas.get(item.id_item) == oferta.id_oferta
                    if st.button(
                        "✔ Elegido" if elegida else "Elegir",
                        key=f"elegir-{item.id_item}-{oferta.id_oferta}",
                        type="primary" if elegida else "secondary",
                    ):
                        elegidas[item.id_item] = oferta.id_oferta
                        st.rerun()
        otras = enlaces_busqueda_manual(item.nombre)
        st.caption(
            "Éxito y Carulla no permiten consulta automática. Búscalo tú: "
            + " · ".join(f"[{tienda}]({url})" for tienda, url in otras.items())
        )


def _carrito(estado: EstadoCompra, escogidas: dict, recomendadas: dict) -> None:
    st.header("Tu compra recomendada")
    if not escogidas:
        st.info("No hay una opción clara para tus productos. Elígelos abajo.")
        return
    st.caption("Ajusta cuántos empaques quieres de cada producto.")
    manual: dict[str, int] = {}
    for item in estado.solicitud.items:
        oferta = escogidas.get(item.id_item)
        if oferta is None:
            continue
        motivo = recomendadas.get(item.id_item)
        if motivo is not None and motivo[0].id_oferta == oferta.id_oferta:
            st.caption(f"{item.nombre}: {motivo[1]}")
        sugerido = armar_carrito([item], {item.id_item: oferta})[0].empaques
        manual[item.id_item] = int(
            st.number_input(
                f"{item.nombre}: empaques de «{oferta.nombre}»",
                min_value=1,
                value=sugerido,
                step=1,
                key=f"empaques-{item.id_item}-{oferta.id_oferta}",
            )
        )
    lineas = armar_carrito(estado.solicitud.items, escogidas, manual)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Producto": linea.item.nombre,
                    "Oferta": linea.oferta.nombre,
                    "Tienda": nombre_escenario(linea.oferta.proveedor),
                    "Empaques": linea.empaques,
                    "Subtotal COP": plata(linea.subtotal),
                }
                for linea in lineas
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    for tienda, total in subtotal_por_tienda(lineas).items():
        st.markdown(
            f"**{nombre_escenario(tienda)}:** {plata(total)} COP en productos. "
            "El domicilio no está publicado, así que el total final no está confirmado."
        )
        propias = [linea for linea in lineas if linea.oferta.proveedor == tienda]
        st.caption("Abre cada producto en la tienda para comprarlo:")
        for linea in propias:
            st.markdown(f"- [{linea.oferta.nombre}]({linea.oferta.url_fuente}) × {linea.empaques}")


def _mostrar(estado: EstadoCompra) -> None:
    informe = estado.informe
    assert informe is not None
    prosa = prosa_recomendacion(informe)
    if informe.solicitud_incompleta:
        st.warning(prosa)
        return

    # Los presupuestos se recalculan con lo que la persona tiene elegido.
    opciones, recomendadas, escogidas = _preparar_seleccion(estado)
    escenarios = construir_escenarios(estado.solicitud, estado.grupos, escogidas)
    informe = redactar_informe(estado.model_copy(update={"escenarios": escenarios}))
    prosa = prosa_recomendacion(informe)

    st.success(prosa)
    if estado.errores_consulta:
        for error in estado.errores_consulta:
            st.warning(f"{nombre_escenario(error.proveedor)}: {error.mensaje}")

    _carrito(estado, escogidas, recomendadas)

    st.header("Comparación de presupuestos")
    columnas = st.columns(3)
    for columna, escenario in zip(columnas, informe.escenarios):
        cubiertas = sum(linea.cubierta for linea in escenario.lineas)
        with columna:
            titulo = nombre_escenario(escenario.tipo)
            if escenario.tipo == informe.escenario_recomendado:
                titulo = f"{titulo} · recomendado"
            if cubiertas == 0:
                st.metric(titulo, "Sin cobertura")
            else:
                st.metric(titulo, f"{plata(escenario.total_parcial)} COP")
            st.caption("Domicilio: no publicado")
            st.caption("Total confirmado: sin dato")

    st.subheader("Costos de adquisición")
    st.dataframe(tabla_visible(informe.escenarios), hide_index=True, use_container_width=True)

    fuentes = indice_fuentes(estado)
    for escenario in informe.escenarios:
        with st.expander(nombre_escenario(escenario.tipo), expanded=escenario.tipo == informe.escenario_recomendado):
            st.dataframe(
                pd.DataFrame(filas_detalle(escenario, fuentes)),
                hide_index=True,
                use_container_width=True,
                column_config={"Fuente": st.column_config.LinkColumn("Fuente")},
            )

    if informe.suposiciones:
        st.header("Suposiciones")
        for suposicion in informe.suposiciones:
            st.markdown(f"**{suposicion.campo}:** {suposicion.valor}. {suposicion.motivo}")

    _otras_opciones(estado, opciones, recomendadas)

    if informe.fuentes:
        st.subheader("Fuentes")
        for url in informe.fuentes:
            if url.startswith("http"):
                st.markdown(f"- [{url}]({url})")
            else:
                st.markdown(f"- {url}")

    if estado.historial:
        with st.expander("Recorrido del grafo"):
            for linea in estado.historial:
                st.text(linea)


if __name__ == "__main__":
    render()
