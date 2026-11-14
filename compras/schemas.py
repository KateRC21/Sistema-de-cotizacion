"""Modelos Pydantic del asistente de compras.

Hay dos clases de modelos:

- Salida de LLM (`SolicitudInterpretada`, `ClasificacionEquivalencias`):
  `extra="forbid"`, para poder usarlos con structured outputs.
- Resultados calculados en Python (cotizaciones, ofertas evaluadas,
  escenarios e informe). El LLM no rellena precios ni totales.

Los montos se guardan como `Decimal`. Un costo desconocido lleva monto
vacío; no se representa con cero.
"""

import operator
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Proveedor = Literal["jumbo", "superboom"]
Relacion = Literal["equivalente", "sustituto", "no_comparable"]
Disponibilidad = Literal["disponible", "no_disponible", "desconocida"]
EstadoVerificacion = Literal["datos_de_prueba", "consulta_publica", "no_verificado"]
UnidadBase = Literal["kg", "l", "unidad"]
Dimension = Literal["masa", "volumen", "conteo"]
TipoEscenario = Literal["jumbo", "superboom", "combinado"]

_DIMENSION_POR_UNIDAD: dict[str, Dimension] = {
    "kg": "masa",
    "l": "volumen",
    "unidad": "conteo",
}


def a_dinero(valor: object) -> Decimal:
    """Convierte un monto en COP y rechaza float binario, negativos y más de dos decimales."""
    monto = _a_decimal(valor, "monto")
    if monto < 0:
        raise ValueError("El monto no puede ser negativo.")
    exponente = monto.as_tuple().exponent
    if isinstance(exponente, int) and exponente < -2:
        raise ValueError("El monto admite como máximo dos decimales.")
    return monto


def a_cantidad(valor: object) -> Decimal:
    """Convierte una cantidad física positiva. Acepta hasta seis decimales (1 g = 0.001 kg)."""
    cantidad = _a_decimal(valor, "cantidad")
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    exponente = cantidad.as_tuple().exponent
    if isinstance(exponente, int) and exponente < -6:
        raise ValueError("La cantidad admite como máximo seis decimales.")
    return cantidad


def _a_decimal(valor: object, nombre: str) -> Decimal:
    if isinstance(valor, bool) or isinstance(valor, float):
        raise ValueError(
            f"La {nombre} se indica como entero, cadena o Decimal, no como float."
        )
    if isinstance(valor, Decimal):
        decimal = valor
    else:
        try:
            decimal = Decimal(valor)  # type: ignore[arg-type]
        except (InvalidOperation, ValueError, TypeError, ArithmeticError) as exc:
            raise ValueError(f"{nombre.capitalize()} inválida.") from exc
    if not decimal.is_finite():
        raise ValueError(f"{nombre.capitalize()} inválida.")
    return decimal


def _opcional(conversor):
    def envolver(valor: object) -> Decimal | None:
        if valor is None:
            return None
        return conversor(valor)

    return envolver


Dinero = Annotated[Decimal, BeforeValidator(a_dinero)]
DineroOpcional = Annotated[Decimal | None, BeforeValidator(_opcional(a_dinero))]
Cantidad = Annotated[Decimal, BeforeValidator(a_cantidad)]
CantidadOpcional = Annotated[Decimal | None, BeforeValidator(_opcional(a_cantidad))]


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemSolicitado(_Modelo):
    """Un producto pedido por la persona usuaria, tal como lo interpreta el LLM."""

    id_item: str = Field(min_length=1, description="Identificador estable, por ejemplo item-1.")
    nombre: str = Field(min_length=1, description="Producto pedido, en español.")
    cantidad: CantidadOpcional = Field(
        default=None,
        description="Cantidad pedida. Vacía si el texto no la dice.",
    )
    unidad: str | None = Field(
        default=None,
        description="Unidad dicha por la persona: g, kg, ml, l o unidad. Vacía si no aparece.",
    )
    marca: str | None = Field(default=None, description="Marca exigida, o vacía si no se exige.")
    caracteristicas: list[str] = Field(
        default_factory=list,
        description="Restricciones explícitas, como 'sin azúcar' o 'líquido'.",
    )
    acepta_sustitutos: bool = Field(
        default=False,
        description="True solo si el texto acepta otra marca o una presentación distinta.",
    )


class SolicitudInterpretada(_Modelo):
    """Salida estructurada del nodo de interpretación. No contiene precios."""

    resumen: str = Field(min_length=1, description="Resumen breve de la solicitud, en español.")
    items: list[ItemSolicitado] = Field(
        description="Productos identificados. Lista vacía si no hay ninguno."
    )
    ciudad: str | None = Field(
        default=None,
        description="Ciudad mencionada. Vacía si el texto no la dice.",
    )
    proveedores: list[Proveedor] = Field(
        default_factory=list,
        description="Tiendas pedidas: jumbo, superboom o ambas. Vacía si no se nombran.",
    )
    datos_faltantes: list[str] = Field(
        default_factory=list,
        description="Datos imprescindibles ausentes. No inventes valores para completarlos.",
    )


class ItemLLM(_Modelo):
    """Producto tal como lo devuelve el LLM, antes de asignar identificadores."""

    nombre: str = Field(description="Producto pedido, en español, sin precio.")
    cantidad: float | None = Field(description="Número pedido. null si el texto no lo dice.")
    unidad: str | None = Field(description="Unidad dicha: g, kg, ml, l o unidad. null si no aparece.")
    marca: str | None = Field(description="Marca exigida. null si no se exige una marca.")
    caracteristicas: list[str] = Field(
        description="Restricciones explícitas, como 'sin azúcar'. Lista vacía si no hay."
    )
    acepta_sustitutos: bool = Field(
        description="True solo si el texto acepta otra marca o un producto parecido."
    )


class SolicitudLLM(_Modelo):
    """Salida estructurada del intérprete. No incluye precios ni identificadores."""

    resumen: str = Field(description="Resumen breve, en español y en tercera persona.")
    items: list[ItemLLM] = Field(description="Un elemento por producto. Lista vacía si no hay ninguno.")
    ciudad: str | None = Field(description="Ciudad mencionada. null si el texto no la dice.")
    proveedores: list[str] = Field(
        description="Solo 'jumbo' o 'superboom', y solo si los nombran. Lista vacía si no."
    )
    datos_faltantes: list[str] = Field(
        description="Datos imprescindibles ausentes, como 'cantidad' o 'unidad'. No inventes valores."
    )


class DatoAclaradoLLM(BaseModel):
    """Un producto tal como queda si se acepta la respuesta de la persona."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(description="Nombre del producto, copiado de la solicitud.")
    cantidad: float | None = Field(description="Cantidad dicha en la respuesta. null si no la dice.")
    unidad: str | None = Field(description="kg, g, l, ml o unidad. null si la respuesta no la dice.")


class AclaracionLLM(BaseModel):
    """Corrección propuesta para que la persona la confirme. No incluye precios."""

    model_config = ConfigDict(extra="forbid")

    texto_confirmado: str = Field(
        description="Frase en español con el dato aportado. Vacía si la respuesta no lo trae."
    )
    productos: list[DatoAclaradoLLM] = Field(
        description="Un elemento por producto de la solicitud, con la cantidad y la unidad entendidas."
    )
    resumen: str = Field(description="Frase corta para mostrar a la persona. Empieza por 'Entendí:'.")
    suficiente: bool = Field(
        description="True solo si la respuesta cubre el dato que faltaba."
    )


class ProductoAclarado(_Modelo):
    """Cantidad y unidad ya normalizadas, listas para mostrar."""

    nombre: str = Field(min_length=1)
    cantidad: CantidadOpcional = None
    unidad: str | None = None


class PropuestaAclaracion(_Modelo):
    """Lo que la pantalla enseña antes de reanudar el grafo."""

    texto_confirmado: str = ""
    productos: list[ProductoAclarado] = Field(default_factory=list)
    resumen: str = Field(min_length=1)
    suficiente: bool


class Suposicion(_Modelo):
    """Decisión tomada porque el texto no traía el dato, registrada de forma explícita."""

    campo: str = Field(min_length=1)
    valor: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class Cotizacion(_Modelo):
    """Oferta homogénea de Jumbo o Superboom. Las dos tiendas usan este mismo modelo."""

    id_oferta: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    marca: str | None = None
    presentacion: str | None = None
    cantidad: CantidadOpcional = None
    unidad: str | None = None
    precio: Dinero
    moneda: Literal["COP"]
    proveedor: Proveedor
    url_fuente: str = Field(min_length=1, description="URL o identificador de la fila de origen.")
    fecha_consulta: date
    disponibilidad: Disponibilidad
    estado_verificacion: EstadoVerificacion
    id_item: str | None = Field(
        default=None,
        description="Producto solicitado al que responde esta oferta.",
    )
    url_imagen: str | None = Field(default=None, description="Foto pública del producto.")
    id_sku: str | None = Field(default=None, description="SKU de la tienda, para armar el carrito.")
    id_vendedor: str | None = Field(default=None, description="Vendedor del SKU en la tienda.")


class ErrorConsulta(_Modelo):
    """Fallo de un proveedor. No borra las ofertas que sí respondieron."""

    proveedor: Proveedor
    mensaje: str = Field(min_length=1)
    id_item: str | None = None


class ResultadoProveedor(_Modelo):
    proveedor: Proveedor
    ofertas: list[Cotizacion] = Field(default_factory=list)
    errores: list[ErrorConsulta] = Field(default_factory=list)

    @model_validator(mode="after")
    def mismo_proveedor(self) -> "ResultadoProveedor":
        for oferta in self.ofertas:
            if oferta.proveedor != self.proveedor:
                raise ValueError("La oferta pertenece a otro proveedor.")
        for error in self.errores:
            if error.proveedor != self.proveedor:
                raise ValueError("El error pertenece a otro proveedor.")
        return self


class MedidaNormalizada(_Modelo):
    """Cantidad ya convertida a kg, litro o unidad."""

    cantidad: Cantidad
    unidad: UnidadBase
    dimension: Dimension

    @model_validator(mode="after")
    def dimension_coherente(self) -> "MedidaNormalizada":
        if self.dimension != _DIMENSION_POR_UNIDAD[self.unidad]:
            raise ValueError("La dimensión no corresponde a la unidad normalizada.")
        return self


class ClasificacionOferta(_Modelo):
    """Una relación propuesta por el LLM. Solo puede citar identificadores ya existentes."""

    id_item: str = Field(min_length=1)
    id_oferta: str = Field(min_length=1)
    relacion: Relacion
    motivo: str = Field(min_length=1, description="Por qué esa relación, sin calcular precios.")


class ClasificacionEquivalencias(_Modelo):
    """Salida estructurada del paso semántico. Python vuelve a validar cada par."""

    clasificaciones: list[ClasificacionOferta]


class ClasificacionOfertaLLM(BaseModel):
    """Clasificación que pide el LLM. Sin precios y sin mínimos que rompan el schema estricto."""

    model_config = ConfigDict(extra="forbid")

    id_item: str = Field(description="Identificador del producto solicitado, copiado de la lista.")
    id_oferta: str = Field(description="Identificador de la oferta, copiado de la lista.")
    relacion: Relacion = Field(description="equivalente, sustituto o no_comparable.")
    motivo: str = Field(description="Razón semántica, sin precios ni cálculos.")


class ClasificacionEquivalenciasLLM(BaseModel):
    """Salida estricta del clasificador de equivalencias."""

    model_config = ConfigDict(extra="forbid")

    clasificaciones: list[ClasificacionOfertaLLM] = Field(
        description="Solo pares cuyos identificadores aparecen en la lista recibida."
    )


class OfertaEvaluada(_Modelo):
    """Oferta después de las reglas de Python: unidades, restricciones y precio normalizado."""

    id_item: str = Field(min_length=1)
    cotizacion: Cotizacion
    medida: MedidaNormalizada | None = None
    precio_por_unidad_base: DineroOpcional = None
    relacion: Relacion
    motivo: str = Field(min_length=1)
    cumple_restricciones: bool
    origen: Literal["reglas", "llm_validado"]

    @model_validator(mode="after")
    def coherencia(self) -> "OfertaEvaluada":
        tiene_medida = self.medida is not None
        tiene_precio = self.precio_por_unidad_base is not None
        if tiene_medida != tiene_precio:
            raise ValueError("La medida normalizada y su precio van juntos.")
        if self.relacion == "equivalente" and (
            not tiene_medida or not self.cumple_restricciones
        ):
            raise ValueError(
                "Un equivalente exige medida normalizada, precio calculado y restricciones cumplidas."
            )
        if self.cotizacion.id_item not in (None, self.id_item):
            raise ValueError("La oferta evaluada no corresponde al ítem de la cotización.")
        return self


class GrupoItem(_Modelo):
    """Ofertas ya evaluadas de un mismo producto solicitado."""

    id_item: str = Field(min_length=1)
    ofertas: list[OfertaEvaluada] = Field(default_factory=list)

    @model_validator(mode="after")
    def mismo_item(self) -> "GrupoItem":
        for oferta in self.ofertas:
            if oferta.id_item != self.id_item:
                raise ValueError("El grupo mezcla productos distintos.")
        return self


class LineaPresupuesto(_Modelo):
    """Una fila de compra. Si no hay cobertura, el costo queda vacío y no suma."""

    id_item: str = Field(min_length=1)
    nombre_solicitado: str = Field(min_length=1)
    cubierta: bool
    id_oferta: str | None = None
    proveedor: Proveedor | None = None
    nombre_oferta: str | None = None
    presentacion: str | None = None
    precio_presentacion: DineroOpcional = None
    precio_normalizado: DineroOpcional = None
    unidad_normalizada: UnidadBase | None = None
    cantidad_requerida: CantidadOpcional = None
    unidades_a_comprar: int | None = Field(default=None, ge=1)
    costo_adquisicion: DineroOpcional = None
    relacion: Relacion | None = None

    @model_validator(mode="after")
    def cobertura(self) -> "LineaPresupuesto":
        if self.cubierta:
            faltan = [
                nombre
                for nombre, valor in (
                    ("id_oferta", self.id_oferta),
                    ("proveedor", self.proveedor),
                    ("precio_presentacion", self.precio_presentacion),
                    ("costo_adquisicion", self.costo_adquisicion),
                    ("relacion", self.relacion),
                    ("unidades_a_comprar", self.unidades_a_comprar),
                )
                if valor is None
            ]
            if faltan:
                raise ValueError(
                    "La línea cubierta está incompleta: " + ", ".join(faltan) + "."
                )
            if self.relacion == "no_comparable":
                raise ValueError("Una línea cubierta no puede ser no comparable.")
        elif self.costo_adquisicion is not None:
            raise ValueError("Una línea sin cobertura no lleva costo de adquisición.")
        return self


class CostoAdicional(_Modelo):
    """Costo distinto del precio del producto, por ejemplo el domicilio."""

    concepto: str = Field(min_length=1)
    conocido: bool
    monto: DineroOpcional = None
    proveedor: Proveedor | None = None

    @model_validator(mode="after")
    def monto_solo_si_se_conoce(self) -> "CostoAdicional":
        if self.conocido and self.monto is None:
            raise ValueError("Un costo conocido requiere monto.")
        if not self.conocido and self.monto is not None:
            raise ValueError(
                "Un costo desconocido no lleva monto. No se registra como cero."
            )
        return self


class EscenarioPresupuesto(_Modelo):
    """Compra completa en una tienda, o la combinación más económica por producto.

    `total_parcial` suma el subtotal y los costos adicionales conocidos.
    `total_confirmado` solo existe cuando todos los costos adicionales se conocen.
    """

    tipo: TipoEscenario
    lineas: list[LineaPresupuesto]
    productos_sin_cotizacion: list[str]
    subtotal_productos: Dinero
    costos_adicionales: list[CostoAdicional]
    total_parcial: Dinero
    total_confirmado: DineroOpcional = None

    @model_validator(mode="after")
    def cuadrar(self) -> "EscenarioPresupuesto":
        if not any(costo.concepto == "domicilio" for costo in self.costos_adicionales):
            raise ValueError(
                "Todo escenario declara el domicilio. Si se desconoce, el monto va vacío."
            )

        identificadores = [linea.id_item for linea in self.lineas]
        if len(identificadores) != len(set(identificadores)):
            raise ValueError("Cada producto aparece una vez en el escenario.")

        sin_cobertura = {linea.id_item for linea in self.lineas if not linea.cubierta}
        if set(self.productos_sin_cotizacion) != sin_cobertura:
            raise ValueError(
                "productos_sin_cotizacion debe listar exactamente las líneas no cubiertas."
            )

        subtotal = sum(
            (linea.costo_adquisicion for linea in self.lineas if linea.cubierta),
            Decimal("0"),
        )
        if self.subtotal_productos != subtotal:
            raise ValueError("El subtotal no coincide con el costo de las líneas cubiertas.")

        conocidos = Decimal("0")
        hay_desconocido = False
        for costo in self.costos_adicionales:
            if costo.conocido:
                conocidos += costo.monto or Decimal("0")
            else:
                hay_desconocido = True

        esperado = self.subtotal_productos + conocidos
        if self.total_parcial != esperado:
            raise ValueError(
                "El total parcial debe ser el subtotal más los costos adicionales conocidos."
            )
        if hay_desconocido:
            if self.total_confirmado is not None:
                raise ValueError(
                    "Hay costos desconocidos: el total confirmado queda vacío. "
                    "Un costo desconocido no es cero."
                )
        elif self.total_confirmado != esperado:
            raise ValueError(
                "El total confirmado debe igualar el subtotal más los costos conocidos."
            )
        return self


class Informe(_Modelo):
    """Informe determinista. Las cifras ya vienen calculadas en los escenarios."""

    resumen_solicitud: str = Field(min_length=1)
    suposiciones: list[Suposicion] = Field(default_factory=list)
    escenarios: list[EscenarioPresupuesto] = Field(default_factory=list)
    recomendacion: str = Field(min_length=1)
    escenario_recomendado: TipoEscenario | None = None
    fuentes: list[str] = Field(min_length=1)
    solicitud_incompleta: bool = False

    @model_validator(mode="after")
    def coherencia(self) -> "Informe":
        if self.solicitud_incompleta:
            if self.escenario_recomendado is not None:
                raise ValueError("Una solicitud incompleta no tiene escenario recomendado.")
            return self

        tipos = {escenario.tipo for escenario in self.escenarios}
        if tipos != {"jumbo", "superboom", "combinado"} or len(self.escenarios) != 3:
            raise ValueError(
                "El informe completo incluye un escenario de Jumbo, uno de Superboom y uno combinado."
            )
        if (
            self.escenario_recomendado is not None
            and self.escenario_recomendado not in tipos
        ):
            raise ValueError("El escenario recomendado no está en el informe.")
        return self


class EstadoCompra(BaseModel):
    """Estado que viaja por el grafo.

    Cada nodo recibe este modelo y devuelve un diccionario solo con los campos
    que actualiza. `historial`, `suposiciones`, `mensajes_aclaracion` y
    `resultados_proveedor` usan un reducer: acumulan sin borrar lo anterior.
    """

    texto_usuario: str = ""
    mensajes_aclaracion: Annotated[list[str], operator.add] = Field(default_factory=list)
    rondas_aclaracion: int = 0
    solicitud: SolicitudInterpretada | None = None
    suposiciones: Annotated[list[Suposicion], operator.add] = Field(default_factory=list)
    resultados_proveedor: Annotated[list[ResultadoProveedor], operator.add] = Field(
        default_factory=list
    )
    ofertas: list[Cotizacion] = Field(default_factory=list)
    errores_consulta: list[ErrorConsulta] = Field(default_factory=list)
    grupos: list[GrupoItem] = Field(default_factory=list)
    escenarios: list[EscenarioPresupuesto] = Field(default_factory=list)
    informe: Informe | None = None
    historial: Annotated[list[str], operator.add] = Field(default_factory=list)
