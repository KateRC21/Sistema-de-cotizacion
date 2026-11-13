"""Nodo de interpretación: el LLM extrae y Python normaliza."""

from decimal import Decimal

from langchain_core.runnables import Runnable

from compras.schemas import (
    EstadoCompra,
    ItemSolicitado,
    SolicitudInterpretada,
    SolicitudLLM,
)

_UNIDADES = {
    "g": "g",
    "gr": "g",
    "grs": "g",
    "gramo": "g",
    "gramos": "g",
    "kg": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogramo": "kg",
    "kilogramos": "kg",
    "ml": "ml",
    "mililitro": "ml",
    "mililitros": "ml",
    "l": "l",
    "lt": "l",
    "litro": "l",
    "litros": "l",
    "unidad": "unidad",
    "unidades": "unidad",
    "und": "unidad",
    "un": "unidad",
    "u": "unidad",
}
_PROVEEDORES = {"jumbo", "superboom"}


def crear_nodo_interpretar(cadena: Runnable):
    """Fábrica: la cadena es `prompt | llm` y en pruebas puede ser un sustituto."""

    def interpretar(state: EstadoCompra) -> dict:
        texto = _texto_completo(state)
        salida = cadena.invoke({"texto_usuario": texto})
        if not isinstance(salida, SolicitudLLM):
            salida = SolicitudLLM.model_validate(salida)
        solicitud = completar_solicitud(salida)
        tiendas = ",".join(solicitud.proveedores) or "ninguna"
        return {
            "solicitud": solicitud,
            "historial": [
                f"[interpretar] items={len(solicitud.items)}, "
                f"ciudad={solicitud.ciudad or 'sin decir'}, proveedores={tiendas}"
            ],
        }

    return interpretar


def completar_solicitud(salida: SolicitudLLM) -> SolicitudInterpretada:
    """Asigna identificadores, normaliza unidades y descarta tiendas no habilitadas."""
    proveedores, avisos = _proveedores(salida.proveedores)
    faltantes = _unir(salida.datos_faltantes, avisos)
    items: list[ItemSolicitado] = []
    for bruto in salida.items:
        nombre = bruto.nombre.strip()
        if not nombre:
            continue
        items.append(
            ItemSolicitado(
                id_item=f"item-{len(items) + 1}",
                nombre=nombre,
                cantidad=_cantidad(bruto.cantidad),
                unidad=_unidad(bruto.unidad),
                marca=(bruto.marca or "").strip() or None,
                caracteristicas=[c.strip() for c in bruto.caracteristicas if c.strip()],
                acepta_sustitutos=bruto.acepta_sustitutos,
            )
        )
    faltantes = _faltantes_reales(items, faltantes)

    resumen = salida.resumen.strip() or "Solicitud sin resumen."
    ciudad = (salida.ciudad or "").strip() or None
    return SolicitudInterpretada(
        resumen=resumen,
        items=items,
        ciudad=ciudad,
        proveedores=proveedores,
        datos_faltantes=faltantes,
    )


def _faltantes_reales(items: list[ItemSolicitado], faltantes: list[str]) -> list[str]:
    """Python decide qué falta. Una etiqueta del LLM no se conserva si el dato sí está."""
    if not items:
        utiles = [dato for dato in faltantes if dato not in {"cantidad", "unidad", "producto"}]
        return _unir(utiles, ["producto"])
    utiles = [dato for dato in faltantes if dato not in {"cantidad", "unidad", "producto"}]
    if any(item.cantidad is None for item in items):
        utiles = _unir(utiles, ["cantidad"])
    if any(item.unidad is None for item in items):
        utiles = _unir(utiles, ["unidad"])
    return utiles


def _texto_completo(state: EstadoCompra) -> str:
    partes = [state.texto_usuario.strip()]
    for mensaje in state.mensajes_aclaracion:
        texto = mensaje.strip()
        if texto:
            partes.append(f"<aclaracion>\n{texto}\n</aclaracion>")
    return "\n".join(parte for parte in partes if parte)


def _cantidad(valor: float | None) -> Decimal | None:
    if valor is None or valor <= 0:
        return None
    cantidad = Decimal(str(valor))
    if not cantidad.is_finite() or cantidad <= 0:
        return None
    return cantidad


def _unidad(valor: str | None) -> str | None:
    texto = (valor or "").strip().lower()
    if not texto:
        return None
    return _UNIDADES.get(texto, texto)


def _proveedores(nombres: list[str]) -> tuple[list[str], list[str]]:
    validos: list[str] = []
    avisos: list[str] = []
    for nombre in nombres:
        token = nombre.strip().lower()
        if not token:
            continue
        if token in _PROVEEDORES:
            if token not in validos:
                validos.append(token)
        else:
            avisos.append(f"proveedor no disponible: {token}")
    return validos, avisos


def _unir(actual: list[str], nuevos: list[str]) -> list[str]:
    resultado = [dato.strip() for dato in actual if dato.strip()]
    for dato in nuevos:
        if dato not in resultado:
            resultado.append(dato)
    return resultado
