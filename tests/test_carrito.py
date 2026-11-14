from datetime import date
from decimal import Decimal

from compras.carrito import (
    armar_carrito,
    empaques_necesarios,
    enlaces_busqueda_manual,
    opciones_por_item,
    subtotal_por_tienda,
)
from compras.schemas import Cotizacion, EstadoCompra, ItemSolicitado, SolicitudInterpretada


def _oferta(id_oferta, proveedor, precio, cantidad=None, unidad=None, sku=None, disp="disponible"):
    return Cotizacion(
        id_oferta=id_oferta,
        nombre=f"Galletas {id_oferta}",
        precio=Decimal(precio),
        moneda="COP",
        proveedor=proveedor,
        url_fuente=f"https://t.co/{id_oferta}",
        fecha_consulta=date(2026, 11, 13),
        disponibilidad=disp,
        estado_verificacion="consulta_publica",
        id_item="item-1",
        cantidad=cantidad,
        unidad=unidad,
        id_sku=sku,
        id_vendedor="1" if sku else None,
        url_imagen="https://t.co/x.png",
    )


def _item(cantidad="1", unidad="unidad"):
    return ItemSolicitado(
        id_item="item-1", nombre="galletas", cantidad=Decimal(cantidad), unidad=unidad
    )


def test_opciones_ordenadas_y_solo_disponibles():
    estado = EstadoCompra(
        solicitud=SolicitudInterpretada(resumen="x", items=[_item()]),
        ofertas=[
            _oferta("a", "jumbo", "9000"),
            _oferta("b", "superboom", "5000"),
            _oferta("c", "jumbo", "1000", disp="no_disponible"),
        ],
    )
    ids = [o.id_oferta for o in opciones_por_item(estado)["item-1"]]
    assert ids == ["b", "a"]


def test_empaques_por_peso_y_por_unidad():
    oferta = _oferta("a", "jumbo", "5000", Decimal("250"), "g")
    assert empaques_necesarios(_item("1", "kg"), oferta) == 4
    assert empaques_necesarios(_item("3", "unidad"), oferta) == 3


def test_subtotal_por_tienda():
    j = _oferta("a", "jumbo", "5000", sku="158364")
    lineas = armar_carrito([_item("2")], {"item-1": j})
    assert subtotal_por_tienda(lineas) == {"jumbo": Decimal("10000")}


def test_busqueda_manual_exito_solo_enlace():
    enlaces = enlaces_busqueda_manual("galletas de chocolate")
    assert enlaces["Éxito"] == "https://www.exito.com/s?q=galletas%20de%20chocolate"


def test_empaques_manuales_mandan():
    j = _oferta("a", "jumbo", "5000", sku="1")
    lineas = armar_carrito([_item("1")], {"item-1": j}, {"item-1": 3})
    assert lineas[0].empaques == 3 and lineas[0].subtotal == Decimal("15000")


def test_validar_supone_cantidad_uno_y_la_registra():
    from compras.nodos.validacion import suponer_cantidades

    sol = SolicitudInterpretada(
        resumen="x",
        items=[ItemSolicitado(id_item="item-1", nombre="arroz")],
    )
    nueva, supos = suponer_cantidades(sol)
    assert nueva.items[0].cantidad == Decimal("1") and nueva.items[0].unidad == "unidad"
    assert supos and "arroz" in supos[0].campo


def test_libra_y_docena_se_convierten():
    from tools.calculos import normalizar_medida

    assert normalizar_medida(Decimal("1"), "libra").cantidad == Decimal("0.5")
    medida = normalizar_medida(Decimal("1"), "docena")
    assert medida.cantidad == Decimal("12") and medida.unidad == "unidad"


def test_conteo_desde_nombre_solo_sin_peso():
    from tools.catalogos import conteo_desde_nombre

    assert conteo_desde_nombre("Huevos AA x30")[1] == Decimal("30")
    assert conteo_desde_nombre("Galletas 18 Unidades")[1] == Decimal("18")
    assert conteo_desde_nombre("Arroz Roa x1kg")[1] is None
    assert conteo_desde_nombre("Leche entera")[1] is None


def test_pedido_por_empaque_compara_por_paquete():
    from compras.nodos.normalizacion import _preparar

    lista = _preparar(_item("1"), _oferta("a", "jumbo", "5000", Decimal("250"), "g"))
    assert lista.exclusion is None
    assert lista.medida.unidad == "unidad" and lista.precio_base == Decimal("5000.00")


def test_la_eleccion_de_la_persona_cubre_un_producto_sin_cobertura():
    from compras.presupuesto import construir_escenarios
    from compras.schemas import GrupoItem

    item = _item("1")
    elegida = _oferta("a", "jumbo", "5000", Decimal("250"), "g")
    solicitud = SolicitudInterpretada(resumen="x", items=[item])
    grupos = [GrupoItem(id_item="item-1", ofertas=[])]
    sin = {e.tipo: e for e in construir_escenarios(solicitud, grupos)}
    con = {e.tipo: e for e in construir_escenarios(solicitud, grupos, {"item-1": elegida})}
    assert sin["jumbo"].productos_sin_cotizacion == ["item-1"]
    assert con["jumbo"].total_parcial == Decimal("5000.00")
    assert con["combinado"].total_parcial == Decimal("5000.00")
    assert con["superboom"].productos_sin_cotizacion == ["item-1"]


def test_el_presupuesto_elige_por_costo_total_no_por_precio_por_kilo():
    from compras.presupuesto import elegir_oferta
    from compras.schemas import MedidaNormalizada, OfertaEvaluada

    def evaluada(id_oferta, precio, kg):
        cot = _oferta(id_oferta, "jumbo", precio, Decimal(kg), "kg")
        medida = MedidaNormalizada(cantidad=Decimal(kg), unidad="kg", dimension="masa")
        return OfertaEvaluada(
            id_item="item-1", cotizacion=cot, medida=medida,
            precio_por_unidad_base=(Decimal(precio) / Decimal(kg)).quantize(Decimal("0.01")),
            relacion="equivalente", motivo="x", cumple_restricciones=True, origen="reglas",
        )

    bulto = evaluada("bulto", "30000", "10")   # 3000 por kg, pero 30000 en total
    bolsa = evaluada("bolsa", "7000", "1")     # 7000 por kg, pero 14000 por 2 kg
    elegida = elegir_oferta(_item("2", "kg"), [bulto, bolsa], "jumbo")
    assert elegida.cotizacion.id_oferta == "bolsa"
