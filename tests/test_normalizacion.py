"""Normalización y comparación. La marca llm llama a OpenAI; el resto no."""

from datetime import date
from decimal import Decimal

import pytest
from langchain_core.runnables import RunnableLambda

from compras.nodos.comparacion import crear_nodo_comparar, ordenar_grupo
from compras.nodos.normalizacion import evaluar_ofertas
from compras.prompts import crear_prompt_equivalencias
from compras.schemas import (
    ClasificacionEquivalenciasLLM,
    ClasificacionOfertaLLM,
    Cotizacion,
    EstadoCompra,
    GrupoItem,
    ItemSolicitado,
    MedidaNormalizada,
    OfertaEvaluada,
    SolicitudInterpretada,
)
from tools.calculos import misma_dimension, normalizar_medida, precio_por_unidad_base

_HOY = date(2026, 11, 13)


def _item(**cambios: object) -> ItemSolicitado:
    datos: dict[str, object] = {
        "id_item": "item-1",
        "nombre": "arroz",
        "cantidad": Decimal("1"),
        "unidad": "kg",
        "marca": "Diana",
        "caracteristicas": [],
        "acepta_sustitutos": False,
    }
    datos.update(cambios)
    return ItemSolicitado.model_validate(datos)


def _solicitud(*items: ItemSolicitado) -> SolicitudInterpretada:
    return SolicitudInterpretada(
        resumen="La persona pide productos.",
        items=list(items) or [_item()],
        ciudad=None,
        proveedores=[],
        datos_faltantes=[],
    )


def _cotizacion(**cambios: object) -> Cotizacion:
    datos: dict[str, object] = {
        "id_oferta": "jumbo-arroz",
        "nombre": "Arroz Diana 500 g",
        "marca": "Diana",
        "presentacion": "500 g",
        "cantidad": Decimal("500"),
        "unidad": "g",
        "precio": 2500,
        "moneda": "COP",
        "proveedor": "jumbo",
        "url_fuente": "https://www.jumbocolombia.com/arroz-diana-500-g/p",
        "fecha_consulta": _HOY,
        "disponibilidad": "disponible",
        "estado_verificacion": "consulta_publica",
        "id_item": "item-1",
    }
    datos.update(cambios)
    return Cotizacion.model_validate(datos)


def _equivalente(id_oferta: str = "jumbo-arroz", motivo: str = "Es el mismo arroz.") -> RunnableLambda:
    def responder(_: dict) -> ClasificacionEquivalenciasLLM:
        return ClasificacionEquivalenciasLLM(
            clasificaciones=[
                ClasificacionOfertaLLM(
                    id_item="item-1",
                    id_oferta=id_oferta,
                    relacion="equivalente",
                    motivo=motivo,
                )
            ]
        )

    return RunnableLambda(responder)


def test_convierte_gramos_a_kg_y_mililitros_a_litros() -> None:
    masa = normalizar_medida(Decimal("500"), "g")
    volumen = normalizar_medida(Decimal("900"), "ml")
    assert masa is not None and masa.cantidad == Decimal("0.5") and masa.unidad == "kg"
    assert volumen is not None and volumen.cantidad == Decimal("0.9") and volumen.unidad == "l"
    assert misma_dimension("g", "kg")
    assert not misma_dimension("g", "ml")
    assert normalizar_medida(Decimal("1"), "botella") is None


def test_precio_por_kilo_y_redondeo_a_centavos() -> None:
    medio_kilo = normalizar_medida(Decimal("500"), "g")
    tres_kilos = normalizar_medida(Decimal("3"), "kg")
    assert medio_kilo is not None and tres_kilos is not None
    assert precio_por_unidad_base(Decimal("2500"), medio_kilo) == Decimal("5000")
    assert precio_por_unidad_base(Decimal("1000"), tres_kilos) == Decimal("333.33")


def test_el_llm_no_recibe_precios_y_no_puede_inventarlos() -> None:
    contextos: list[str] = []

    def responder(entrada: dict) -> ClasificacionEquivalenciasLLM:
        contextos.append(entrada["contexto"])
        return ClasificacionEquivalenciasLLM(
            clasificaciones=[
                ClasificacionOfertaLLM(
                    id_item="item-1",
                    id_oferta="jumbo-arroz",
                    relacion="equivalente",
                    motivo="Cuesta 1 COP por kg, pero es el mismo producto.",
                )
            ]
        )

    grupos = evaluar_ofertas(
        _solicitud(_item()),
        [_cotizacion(precio=2599)],
        RunnableLambda(responder),
    )
    oferta = grupos[0].ofertas[0]
    assert "2599" not in contextos[0]
    assert oferta.precio_por_unidad_base == Decimal("5198")
    assert oferta.relacion == "equivalente"
    assert oferta.origen == "llm_validado"


def test_quinientos_gramos_equivalen_a_un_kilo_del_mismo_arroz() -> None:
    grupos = evaluar_ofertas(_solicitud(_item()), [_cotizacion()], _equivalente())
    oferta = grupos[0].ofertas[0]
    assert oferta.medida is not None and oferta.medida.cantidad == Decimal("0.5")
    assert oferta.precio_por_unidad_base == Decimal("5000")
    assert oferta.relacion == "equivalente"


def test_novecientos_mililitros_se_comparan_por_litro() -> None:
    item = _item(nombre="leche", unidad="l", marca=None)
    oferta = _cotizacion(
        id_oferta="jumbo-leche",
        nombre="Leche 900 ml",
        marca=None,
        presentacion="900 ml",
        cantidad=Decimal("900"),
        unidad="ml",
        precio=4500,
    )
    grupos = evaluar_ofertas(_solicitud(item), [oferta], _equivalente("jumbo-leche"))
    evaluada = grupos[0].ofertas[0]
    assert evaluada.medida is not None and evaluada.medida.unidad == "l"
    assert evaluada.precio_por_unidad_base == Decimal("5000")


def test_otra_marca_sin_sustitutos_no_consulta_al_llm() -> None:
    llamadas: list[str] = []

    def responder(entrada: dict) -> ClasificacionEquivalenciasLLM:
        llamadas.append(entrada["contexto"])
        raise AssertionError("No debía clasificar una marca incompatible.")

    grupos = evaluar_ofertas(
        _solicitud(_item(marca="Diana")),
        [_cotizacion(marca="Roa", nombre="Arroz Roa 500 g")],
        RunnableLambda(responder),
    )
    assert llamadas == []
    assert grupos[0].ofertas[0].relacion == "no_comparable"
    assert grupos[0].ofertas[0].precio_por_unidad_base == Decimal("5000")


def test_otra_marca_aceptada_baja_de_equivalente_a_sustituto() -> None:
    grupos = evaluar_ofertas(
        _solicitud(_item(marca="Diana", acepta_sustitutos=True)),
        [_cotizacion(marca="Roa", nombre="Arroz Roa 500 g")],
        _equivalente(),
    )
    oferta = grupos[0].ofertas[0]
    assert oferta.relacion == "sustituto"
    assert oferta.cumple_restricciones is True
    assert oferta.origen == "llm_validado"


def test_sin_presentacion_queda_no_comparable_y_sin_precio_inventado() -> None:
    grupos = evaluar_ofertas(
        _solicitud(_item()),
        [_cotizacion(nombre="Arroz Casanare Blanco", cantidad=None, unidad=None, presentacion=None)],
        _equivalente(),
    )
    oferta = grupos[0].ofertas[0]
    assert oferta.relacion == "no_comparable"
    assert oferta.medida is None
    assert oferta.precio_por_unidad_base is None


def test_aceite_no_se_compara_con_arroz_aunque_el_llm_lo_llame_equivalente() -> None:
    def responder(_: dict) -> ClasificacionEquivalenciasLLM:
        return ClasificacionEquivalenciasLLM(
            clasificaciones=[
                ClasificacionOfertaLLM(
                    id_item="item-1",
                    id_oferta="jumbo-aceite",
                    relacion="equivalente",
                    motivo="También es un alimento.",
                )
            ]
        )

    grupos = evaluar_ofertas(
        _solicitud(_item()),
        [
            _cotizacion(
                id_oferta="jumbo-aceite",
                nombre="Aceite 900 ml",
                marca="Premier",
                presentacion="900 ml",
                cantidad=Decimal("900"),
                unidad="ml",
                precio=9000,
            )
        ],
        RunnableLambda(responder),
    )
    assert grupos[0].ofertas[0].relacion == "no_comparable"
    assert "unidad" in grupos[0].ofertas[0].motivo


def test_un_identificador_inventado_se_descarta() -> None:
    def responder(_: dict) -> ClasificacionEquivalenciasLLM:
        return ClasificacionEquivalenciasLLM(
            clasificaciones=[
                ClasificacionOfertaLLM(
                    id_item="item-1",
                    id_oferta="oferta-inventada",
                    relacion="equivalente",
                    motivo="Me la inventé.",
                )
            ]
        )

    grupos = evaluar_ofertas(_solicitud(_item()), [_cotizacion()], RunnableLambda(responder))
    oferta = grupos[0].ofertas[0]
    assert oferta.relacion == "no_comparable"
    assert oferta.origen == "reglas"
    assert oferta.precio_por_unidad_base == Decimal("5000")


def test_si_el_clasificador_falla_se_conserva_el_precio_calculado() -> None:
    def responder(_: dict) -> ClasificacionEquivalenciasLLM:
        raise RuntimeError("sin respuesta")

    grupos = evaluar_ofertas(_solicitud(_item()), [_cotizacion()], RunnableLambda(responder))
    oferta = grupos[0].ofertas[0]
    assert oferta.relacion == "no_comparable"
    assert oferta.precio_por_unidad_base == Decimal("5000")


def test_la_caracteristica_no_confirmada_impide_la_comparacion() -> None:
    grupos = evaluar_ofertas(
        _solicitud(_item(nombre="leche", marca=None, unidad="l", caracteristicas=["deslactosada"])),
        [
            _cotizacion(
                nombre="Leche entera 900 ml",
                marca=None,
                presentacion="900 ml",
                cantidad=Decimal("900"),
                unidad="ml",
                precio=4500,
            )
        ],
        _equivalente(),
    )
    assert grupos[0].ofertas[0].relacion == "no_comparable"
    assert "deslactosada" in grupos[0].ofertas[0].motivo


def test_un_sustituto_mas_barato_no_adelanta_al_equivalente() -> None:
    def oferta(id_oferta: str, relacion: str, precio: str) -> OfertaEvaluada:
        return OfertaEvaluada(
            id_item="item-1",
            cotizacion=_cotizacion(id_oferta=id_oferta, precio=Decimal(precio), cantidad=Decimal("1"), unidad="kg"),
            medida=MedidaNormalizada(cantidad=Decimal("1"), unidad="kg", dimension="masa"),
            precio_por_unidad_base=Decimal(precio),
            relacion=relacion,  # type: ignore[arg-type]
            motivo="Prueba de orden.",
            cumple_restricciones=relacion != "no_comparable",
            origen="reglas",
        )

    grupo = GrupoItem(
        id_item="item-1",
        ofertas=[
            oferta("sustituto-barato", "sustituto", "1000"),
            oferta("equivalente-caro", "equivalente", "8000"),
            oferta("no-comparable", "no_comparable", "100"),
            oferta("equivalente-barato", "equivalente", "5000"),
        ],
    )
    orden = [item.cotizacion.id_oferta for item in ordenar_grupo(grupo).ofertas]
    assert orden == [
        "equivalente-barato",
        "equivalente-caro",
        "sustituto-barato",
        "no-comparable",
    ]


def test_la_clasificacion_rechaza_un_precio() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClasificacionOfertaLLM.model_validate(
            {
                "id_item": "item-1",
                "id_oferta": "jumbo-arroz",
                "relacion": "equivalente",
                "motivo": "Mismo producto.",
                "precio": 1,
            }
        )


def test_el_contexto_no_viaja_dentro_de_las_reglas() -> None:
    mensajes = crear_prompt_equivalencias().invoke({"contexto": "id_oferta=secreto-99"})
    assert "secreto-99" not in mensajes.messages[0].content
    assert "secreto-99" in mensajes.messages[1].content


def test_los_nodos_dejan_primero_la_oferta_equivalente_mas_barata() -> None:
    from compras.nodos.normalizacion import crear_nodo_normalizar

    barata = _cotizacion(id_oferta="jumbo-500", precio=2500, cantidad=Decimal("500"), unidad="g")
    cara = _cotizacion(
        id_oferta="superboom-1000",
        proveedor="superboom",
        precio=8000,
        cantidad=Decimal("1"),
        unidad="kg",
        url_fuente="https://web.superboom.net/shop/arroz-1kg",
    )

    def responder(_: dict) -> ClasificacionEquivalenciasLLM:
        return ClasificacionEquivalenciasLLM(
            clasificaciones=[
                ClasificacionOfertaLLM(
                    id_item="item-1", id_oferta=oferta.id_oferta, relacion="equivalente", motivo="Mismo arroz."
                )
                for oferta in (barata, cara)
            ]
        )

    normalizado = crear_nodo_normalizar(RunnableLambda(responder))(
        EstadoCompra(solicitud=_solicitud(_item()), ofertas=[cara, barata])
    )
    comparado = crear_nodo_comparar()(EstadoCompra(grupos=normalizado["grupos"]))
    assert comparado["grupos"][0].ofertas[0].cotizacion.id_oferta == "jumbo-500"
    assert "5000" in comparado["historial"][0]


@pytest.mark.llm
def test_el_modelo_clasifica_el_arroz_y_python_rechaza_el_aceite() -> None:
    from compras.config import cargar_config

    try:
        cargar_config().exigir_api_key()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    from compras.llm import construir_clasificador_equivalencias

    grupos = evaluar_ofertas(
        _solicitud(_item()),
        [
            _cotizacion(),
            _cotizacion(
                id_oferta="jumbo-aceite",
                nombre="Aceite Girasol 900 ml",
                marca="Premier",
                presentacion="900 ml",
                cantidad=Decimal("900"),
                unidad="ml",
                precio=9000,
                url_fuente="https://www.jumbocolombia.com/aceite/p",
            ),
        ],
        construir_clasificador_equivalencias(),
    )
    por_id = {oferta.cotizacion.id_oferta: oferta for oferta in grupos[0].ofertas}
    assert por_id["jumbo-aceite"].relacion == "no_comparable"
    assert por_id["jumbo-arroz"].precio_por_unidad_base == Decimal("5000")
    assert por_id["jumbo-arroz"].origen == "llm_validado"
    assert por_id["jumbo-arroz"].relacion in {"equivalente", "sustituto"}
