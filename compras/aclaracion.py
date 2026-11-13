"""La aclaración se propone y la persona la confirma antes de reanudar el grafo."""

from compras.nodos.interpretacion import _cantidad, _unidad
from compras.schemas import AclaracionLLM, ProductoAclarado, PropuestaAclaracion


def preparar_propuesta(salida: object, faltantes: list[str]) -> PropuestaAclaracion:
    """Python decide si la propuesta alcanza. Un true del modelo no rellena un null."""
    if not isinstance(salida, AclaracionLLM):
        salida = AclaracionLLM.model_validate(salida)

    productos = [
        ProductoAclarado(
            nombre=dato.nombre.strip() or "producto",
            cantidad=_cantidad(dato.cantidad),
            unidad=_unidad(dato.unidad),
        )
        for dato in salida.productos
        if dato.nombre.strip()
    ]
    texto = salida.texto_confirmado.strip()
    cubre_cantidad = "cantidad" not in faltantes or any(item.cantidad is not None for item in productos)
    cubre_unidad = "unidad" not in faltantes or any(item.unidad for item in productos)
    cubre_producto = "producto" not in faltantes or bool(productos or texto)
    suficiente = bool(texto) and cubre_cantidad and cubre_unidad and cubre_producto

    resumen = salida.resumen.strip() or "No pude armar una corrección con esa respuesta."
    return PropuestaAclaracion(
        texto_confirmado=texto,
        productos=productos,
        resumen=resumen,
        suficiente=suficiente,
    )


def texto_productos(productos: list[ProductoAclarado]) -> str:
    """Líneas que ve la persona al comprobar la corrección."""
    if not productos:
        return "Ningún producto con cantidad y unidad."
    lineas = []
    for item in productos:
        cantidad = _texto_cantidad(item.cantidad) if item.cantidad is not None else "sin cantidad"
        unidad = item.unidad or "sin unidad"
        lineas.append(f"{item.nombre}: {cantidad} {unidad}")
    return "\n".join(lineas)


def _texto_cantidad(cantidad) -> str:
    if cantidad == cantidad.to_integral():
        return str(cantidad.to_integral())
    return format(cantidad.normalize(), "f")
