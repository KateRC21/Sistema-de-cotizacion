"""Pruebas de los modelos. No usan red ni la API de OpenAI."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from compras.schemas import (
    ClasificacionEquivalencias,
    CostoAdicional,
    Cotizacion,
    ErrorConsulta,
    EscenarioPresupuesto,
    EstadoCompra,
    Informe,
    ItemSolicitado,
    LineaPresupuesto,
    MedidaNormalizada,
    OfertaEvaluada,
    ResultadoProveedor,
    SolicitudInterpretada,
)


def _cotizacion(**cambios: object) -> Cotizacion:
    datos: dict[str, object] = {
        "id_oferta": "jumbo-arroz-1",
        "nombre": "Arroz Diana 500 g",
        "marca": "Diana",
        "presentacion": "bolsa 500 g",
        "cantidad": "0.5",
        "unidad": "kg",
        "precio": 2500,
        "moneda": "COP",
        "proveedor": "jumbo",
        "url_fuente": "https://www.jumbocolombia.com/arroz-diana-500-g/p",
        "fecha_consulta": date(2026, 1, 15),
        "disponibilidad": "disponible",
        "estado_verificacion": "consulta_publica",
        "id_item": "item-1",
    }
    datos.update(cambios)
    return Cotizacion.model_validate(datos)


def _linea_cubierta(costo: str = "5000") -> LineaPresupuesto:
    return LineaPresupuesto(
        id_item="item-1",
        nombre_solicitado="Arroz",
        cubierta=True,
        id_oferta="jumbo-arroz-1",
        proveedor="jumbo",
        nombre_oferta="Arroz Diana 500 g",
        presentacion="bolsa 500 g",
        precio_presentacion=Decimal("2500"),
        precio_normalizado=Decimal("5000"),
        unidad_normalizada="kg",
        cantidad_requerida=Decimal("1"),
        unidades_a_comprar=2,
        costo_adquisicion=Decimal(costo),
        relacion="equivalente",
    )


def _escenario(
    *,
    domicilio_conocido: bool,
    total_confirmado: Decimal | None,
    subtotal: str = "5000",
) -> EscenarioPresupuesto:
    if domicilio_conocido:
        domicilio = CostoAdicional(
            concepto="domicilio", conocido=True, monto=Decimal("4000"), proveedor="jumbo"
        )
        parcial = Decimal(subtotal) + Decimal("4000")
    else:
        domicilio = CostoAdicional(concepto="domicilio", conocido=False, proveedor="jumbo")
        parcial = Decimal(subtotal)
    return EscenarioPresupuesto(
        tipo="jumbo",
        lineas=[_linea_cubierta(subtotal)],
        productos_sin_cotizacion=[],
        subtotal_productos=Decimal(subtotal),
        costos_adicionales=[domicilio],
        total_parcial=parcial,
        total_confirmado=total_confirmado,
    )


def test_solicitud_rechaza_campos_que_no_estan_en_el_esquema() -> None:
    with pytest.raises(ValidationError):
        SolicitudInterpretada.model_validate(
            {"resumen": "Compra de arroz", "items": [], "precio_estimado": 1000}
        )


def test_item_exige_nombre_y_cantidad_positiva() -> None:
    with pytest.raises(ValidationError):
        ItemSolicitado(id_item="item-1", nombre="  ")
    with pytest.raises(ValidationError):
        ItemSolicitado(id_item="item-1", nombre="Arroz", cantidad=0)


def test_cotizacion_solo_acepta_cop_y_rechaza_precio_negativo() -> None:
    oferta = _cotizacion()
    assert oferta.moneda == "COP"
    assert oferta.precio == Decimal("2500")
    assert oferta.estado_verificacion == "consulta_publica"
    with pytest.raises(ValidationError):
        _cotizacion(moneda="USD")
    with pytest.raises(ValidationError):
        _cotizacion(precio=-1)


def test_el_dinero_no_entra_como_float() -> None:
    with pytest.raises(ValidationError, match="float"):
        _cotizacion(precio=2500.5)


def test_costo_desconocido_no_acepta_cero() -> None:
    with pytest.raises(ValidationError, match="cero"):
        CostoAdicional(concepto="domicilio", conocido=False, monto=0)


def test_costo_conocido_exige_monto() -> None:
    with pytest.raises(ValidationError, match="conocido"):
        CostoAdicional(concepto="domicilio", conocido=True)


def test_domicilio_desconocido_deja_el_total_confirmado_vacio() -> None:
    escenario = _escenario(domicilio_conocido=False, total_confirmado=None)
    assert escenario.subtotal_productos == Decimal("5000")
    assert escenario.total_parcial == Decimal("5000")
    assert escenario.total_confirmado is None


def test_no_se_confirma_el_total_usando_el_subtotal_como_si_el_envio_fuera_cero() -> None:
    with pytest.raises(ValidationError, match="desconocido"):
        _escenario(domicilio_conocido=False, total_confirmado=Decimal("5000"))


def test_total_confirmado_cuando_el_domicilio_se_conoce() -> None:
    escenario = _escenario(domicilio_conocido=True, total_confirmado=Decimal("9000"))
    assert escenario.total_confirmado == Decimal("9000")


def test_el_subtotal_tiene_que_cuadrar_con_las_lineas() -> None:
    linea = _linea_cubierta("5000")
    with pytest.raises(ValidationError, match="subtotal"):
        EscenarioPresupuesto(
            tipo="jumbo",
            lineas=[linea],
            productos_sin_cotizacion=[],
            subtotal_productos=Decimal("1"),
            costos_adicionales=[
                CostoAdicional(concepto="domicilio", conocido=False, proveedor="jumbo")
            ],
            total_parcial=Decimal("1"),
            total_confirmado=None,
        )


def test_linea_sin_cobertura_no_lleva_costo() -> None:
    with pytest.raises(ValidationError, match="sin cobertura"):
        LineaPresupuesto(
            id_item="item-2",
            nombre_solicitado="Jabón",
            cubierta=False,
            costo_adquisicion=Decimal("1000"),
        )


def test_resultado_no_mezcla_proveedores() -> None:
    with pytest.raises(ValidationError, match="otro proveedor"):
        ResultadoProveedor(
            proveedor="superboom",
            ofertas=[_cotizacion()],
            errores=[],
        )


def test_error_de_un_proveedor_puede_viajar_junto_a_sus_ofertas() -> None:
    resultado = ResultadoProveedor(
        proveedor="jumbo",
        ofertas=[_cotizacion()],
        errores=[ErrorConsulta(proveedor="jumbo", mensaje="Sin resultados para jabón.", id_item="item-2")],
    )
    assert len(resultado.ofertas) == 1
    assert resultado.errores[0].id_item == "item-2"


def test_medida_kg_es_masa_y_no_volumen() -> None:
    medida = MedidaNormalizada(cantidad=Decimal("0.5"), unidad="kg", dimension="masa")
    assert medida.cantidad == Decimal("0.5")
    with pytest.raises(ValidationError, match="dimensión"):
        MedidaNormalizada(cantidad=Decimal("0.5"), unidad="kg", dimension="volumen")


def test_equivalente_exige_precio_normalizado() -> None:
    with pytest.raises(ValidationError, match="equivalente"):
        OfertaEvaluada(
            id_item="item-1",
            cotizacion=_cotizacion(),
            relacion="equivalente",
            motivo="Misma marca y presentación.",
            cumple_restricciones=True,
            origen="reglas",
        )


def test_clasificacion_rechaza_una_relacion_inventada() -> None:
    with pytest.raises(ValidationError):
        ClasificacionEquivalencias.model_validate(
            {
                "clasificaciones": [
                    {
                        "id_item": "item-1",
                        "id_oferta": "jumbo-arroz-1",
                        "relacion": "identico",
                        "motivo": "Se parece.",
                    }
                ]
            }
        )


def test_informe_incompleto_no_recomienda_escenario() -> None:
    informe = Informe(
        resumen_solicitud="Falta la cantidad de arroz.",
        recomendacion="Se necesita la cantidad para cotizar.",
        fuentes=["solicitud del usuario"],
        solicitud_incompleta=True,
    )
    assert informe.escenario_recomendado is None
    with pytest.raises(ValidationError, match="incompleta"):
        Informe(
            resumen_solicitud="Falta la cantidad de arroz.",
            recomendacion="Se necesita la cantidad para cotizar.",
            escenario_recomendado="jumbo",
            fuentes=["solicitud del usuario"],
            solicitud_incompleta=True,
        )


def test_estados_no_comparten_listas() -> None:
    primero = EstadoCompra()
    segundo = EstadoCompra()
    primero.historial.append("[interpretar] listo")
    assert segundo.historial == []
    assert primero.model_dump()["texto_usuario"] == ""
