"""Presupuestos e informe. No llaman a OpenAI ni a las tiendas."""

from datetime import date
from decimal import Decimal

from compras.informe import redactar_informe
from compras.presupuesto import construir_escenarios, tabla_comparacion
from compras.schemas import (
    Cotizacion,
    ErrorConsulta,
    EstadoCompra,
    GrupoItem,
    ItemSolicitado,
    OfertaEvaluada,
    SolicitudInterpretada,
)
from tools.calculos import normalizar_medida, precio_por_unidad_base

_FECHA = date(2026, 11, 13)


def _item(id_item: str = "item-1", nombre: str = "Arroz", **cambios: object) -> ItemSolicitado:
    datos: dict[str, object] = {
        "id_item": id_item,
        "nombre": nombre,
        "cantidad": Decimal("2"),
        "unidad": "kg",
        "marca": "Diana",
        "acepta_sustitutos": False,
    }
    datos.update(cambios)
    return ItemSolicitado.model_validate(datos)


def _solicitud(*items: ItemSolicitado, proveedores: list[str] | None = None) -> SolicitudInterpretada:
    return SolicitudInterpretada(
        resumen="La persona pide productos de mercado.",
        items=list(items),
        ciudad="Medellín",
        proveedores=proveedores if proveedores is not None else ["jumbo", "superboom"],
    )


def _oferta(
    proveedor: str,
    id_oferta: str,
    *,
    precio: str,
    cantidad: str,
    unidad: str,
    relacion: str = "equivalente",
    id_item: str = "item-1",
    nombre: str = "Arroz Diana",
) -> OfertaEvaluada:
    medida = normalizar_medida(Decimal(cantidad), unidad)
    assert medida is not None
    monto = Decimal(precio)
    return OfertaEvaluada(
        id_item=id_item,
        cotizacion=Cotizacion(
            id_oferta=id_oferta,
            nombre=nombre,
            marca="Diana",
            presentacion=f"{cantidad} {unidad}",
            cantidad=cantidad,
            unidad=unidad,
            precio=monto,
            moneda="COP",
            proveedor=proveedor,  # type: ignore[arg-type]
            url_fuente=f"https://ejemplo.test/{id_oferta}",
            fecha_consulta=_FECHA,
            disponibilidad="disponible",
            estado_verificacion="datos_de_prueba",
            id_item=id_item,
        ),
        medida=medida,
        precio_por_unidad_base=precio_por_unidad_base(monto, medida),
        relacion=relacion,  # type: ignore[arg-type]
        motivo="Oferta de prueba.",
        cumple_restricciones=relacion != "no_comparable",
        origen="reglas",
    )


def _grupo(item: str, *ofertas: OfertaEvaluada) -> GrupoItem:
    return GrupoItem(id_item=item, ofertas=list(ofertas))


def _escenario(tipo: str, escenarios):
    return next(escenario for escenario in escenarios if escenario.tipo == tipo)


def test_compra_empaques_completos_y_deja_el_domicilio_vacio() -> None:
    solicitud = _solicitud(_item(cantidad=Decimal("2"), unidad="kg"))
    escenarios = construir_escenarios(
        solicitud,
        [
            _grupo(
                "item-1",
                _oferta("jumbo", "jumbo-500", precio="2500", cantidad="500", unidad="g"),
                _oferta("superboom", "boom-1kg", precio="4000", cantidad="1", unidad="kg"),
            )
        ],
    )
    jumbo = _escenario("jumbo", escenarios)
    superboom = _escenario("superboom", escenarios)
    combinado = _escenario("combinado", escenarios)
    assert jumbo.lineas[0].unidades_a_comprar == 4
    assert jumbo.lineas[0].costo_adquisicion == Decimal("10000.00")
    assert superboom.lineas[0].unidades_a_comprar == 2
    assert superboom.lineas[0].costo_adquisicion == Decimal("8000.00")
    assert combinado.lineas[0].proveedor == "superboom"
    assert combinado.lineas[0].costo_adquisicion == Decimal("8000.00")
    for escenario in escenarios:
        domicilio = escenario.costos_adicionales[0]
        assert domicilio.concepto == "domicilio"
        assert domicilio.conocido is False
        assert domicilio.monto is None
        assert escenario.total_parcial == escenario.subtotal_productos
        assert escenario.total_confirmado is None


def test_no_prorratea_una_presentacion_mas_grande() -> None:
    escenarios = construir_escenarios(
        _solicitud(_item(cantidad=Decimal("1"), unidad="kg")),
        [_grupo("item-1", _oferta("jumbo", "jumbo-3kg", precio="9000", cantidad="3", unidad="kg"))],
    )
    linea = _escenario("jumbo", escenarios).lineas[0]
    assert linea.unidades_a_comprar == 1
    assert linea.costo_adquisicion == Decimal("9000.00")


def test_un_sustituto_mas_barato_no_reemplaza_al_equivalente() -> None:
    solicitud = _solicitud(_item(cantidad=Decimal("1"), unidad="kg", acepta_sustitutos=True))
    escenarios = construir_escenarios(
        solicitud,
        [
            _grupo(
                "item-1",
                _oferta("jumbo", "jumbo-eq", precio="5000", cantidad="1", unidad="kg"),
                _oferta(
                    "superboom",
                    "boom-sust",
                    precio="1000",
                    cantidad="1",
                    unidad="kg",
                    relacion="sustituto",
                ),
            )
        ],
    )
    combinado = _escenario("combinado", escenarios).lineas[0]
    assert combinado.relacion == "equivalente"
    assert combinado.id_oferta == "jumbo-eq"
    assert combinado.costo_adquisicion == Decimal("5000.00")
    assert _escenario("superboom", escenarios).lineas[0].relacion == "sustituto"


def test_sin_equivalente_el_sustituto_solo_cubre_si_fue_aceptado() -> None:
    oferta = _oferta(
        "superboom",
        "boom-sust",
        precio="1000",
        cantidad="1",
        unidad="kg",
        relacion="sustituto",
    )
    rechazado = construir_escenarios(
        _solicitud(_item(cantidad=Decimal("1"), unidad="kg", acepta_sustitutos=False)),
        [_grupo("item-1", oferta)],
    )
    assert _escenario("superboom", rechazado).lineas[0].cubierta is False
    assert _escenario("superboom", rechazado).subtotal_productos == Decimal("0.00")

    aceptado = construir_escenarios(
        _solicitud(_item(cantidad=Decimal("1"), unidad="kg", acepta_sustitutos=True)),
        [_grupo("item-1", oferta)],
    )
    linea = _escenario("superboom", aceptado).lineas[0]
    assert linea.cubierta is True
    assert linea.relacion == "sustituto"
    assert linea.costo_adquisicion == Decimal("1000.00")


def test_lo_no_comparable_no_suma_y_la_tabla_no_escribe_cero() -> None:
    escenarios = construir_escenarios(
        _solicitud(_item()),
        [
            _grupo(
                "item-1",
                _oferta("jumbo", "jumbo-x", precio="2500", cantidad="500", unidad="g", relacion="no_comparable"),
            )
        ],
    )
    jumbo = _escenario("jumbo", escenarios)
    assert jumbo.lineas[0].cubierta is False
    assert jumbo.lineas[0].costo_adquisicion is None
    assert jumbo.subtotal_productos == Decimal("0.00")
    assert jumbo.total_confirmado is None
    assert jumbo.productos_sin_cotizacion == ["item-1"]
    tabla = tabla_comparacion(escenarios)
    assert tabla.loc[0, "jumbo"] == ""
    assert tabla.loc[0, "superboom"] == ""
    assert "0" not in tabla.loc[0].tolist()


def test_el_combinado_gana_cuando_cubre_mas_aunque_cueste_mas() -> None:
    escenarios = construir_escenarios(
        _solicitud(
            _item(id_item="item-1", nombre="Arroz", cantidad=Decimal("1"), unidad="kg"),
            _item(id_item="item-2", nombre="Leche", cantidad=Decimal("1"), unidad="l", marca=None),
        ),
        [
            _grupo("item-1", _oferta("jumbo", "jumbo-arroz", precio="10000", cantidad="1", unidad="kg")),
            _grupo(
                "item-2",
                _oferta(
                    "superboom",
                    "boom-leche",
                    precio="3000",
                    cantidad="1",
                    unidad="l",
                    id_item="item-2",
                    nombre="Leche",
                ),
            ),
        ],
    )
    informe = redactar_informe(
        EstadoCompra(
            solicitud=_solicitud(
                _item(id_item="item-1", nombre="Arroz", cantidad=Decimal("1"), unidad="kg"),
                _item(id_item="item-2", nombre="Leche", cantidad=Decimal("1"), unidad="l", marca=None),
            ),
            grupos=[
                _grupo("item-1", _oferta("jumbo", "jumbo-arroz", precio="10000", cantidad="1", unidad="kg")),
                _grupo(
                    "item-2",
                    _oferta(
                        "superboom",
                        "boom-leche",
                        precio="3000",
                        cantidad="1",
                        unidad="l",
                        id_item="item-2",
                        nombre="Leche",
                    ),
                ),
            ],
            escenarios=escenarios,
        )
    )
    assert informe.escenario_recomendado == "combinado"
    combinado = _escenario("combinado", informe.escenarios)
    assert combinado.subtotal_productos == Decimal("13000.00")
    assert combinado.total_confirmado is None
    assert "13000" in informe.recomendacion
    assert "https://ejemplo.test/jumbo-arroz" in informe.fuentes
    assert "https://ejemplo.test/boom-leche" in informe.fuentes


def test_el_informe_menciona_el_error_de_una_tienda_y_conserva_la_otra() -> None:
    oferta = _oferta("jumbo", "jumbo-500", precio="2500", cantidad="500", unidad="g")
    escenarios = construir_escenarios(_solicitud(_item()), [_grupo("item-1", oferta)])
    informe = redactar_informe(
        EstadoCompra(
            solicitud=_solicitud(_item()),
            grupos=[_grupo("item-1", oferta)],
            escenarios=escenarios,
            errores_consulta=[
                ErrorConsulta(proveedor="superboom", mensaje="tiempo de espera", id_item="item-1")
            ],
        )
    )
    assert informe.escenario_recomendado == "jumbo"
    assert _escenario("superboom", informe.escenarios).productos_sin_cotizacion == ["item-1"]
    assert _escenario("superboom", informe.escenarios).total_confirmado is None
    assert "tiempo de espera" in informe.recomendacion
    assert informe.solicitud_incompleta is False


def test_la_solicitud_incompleta_no_recomienda_escenario() -> None:
    informe = redactar_informe(
        EstadoCompra(
            solicitud=_solicitud(_item(cantidad=None, unidad=None)),
        )
    )
    assert informe.solicitud_incompleta is True
    assert informe.escenario_recomendado is None
    assert informe.escenarios == []
    assert "cantidad" in informe.recomendacion
