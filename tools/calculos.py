"""Conversiones y precios por unidad base.

El dinero entra y sale como Decimal. Una unidad desconocida no se convierte
y no produce un precio estimado.
"""

from decimal import Decimal, ROUND_HALF_UP

from compras.schemas import Dimension, MedidaNormalizada, UnidadBase

_FACTOR: dict[str, tuple[Decimal, UnidadBase, Dimension]] = {
    "g": (Decimal("0.001"), "kg", "masa"),
    "gr": (Decimal("0.001"), "kg", "masa"),
    "grs": (Decimal("0.001"), "kg", "masa"),
    "gramo": (Decimal("0.001"), "kg", "masa"),
    "gramos": (Decimal("0.001"), "kg", "masa"),
    "kg": (Decimal("1"), "kg", "masa"),
    "kilo": (Decimal("1"), "kg", "masa"),
    "kilos": (Decimal("1"), "kg", "masa"),
    "ml": (Decimal("0.001"), "l", "volumen"),
    "cc": (Decimal("0.001"), "l", "volumen"),
    "mililitro": (Decimal("0.001"), "l", "volumen"),
    "mililitros": (Decimal("0.001"), "l", "volumen"),
    "l": (Decimal("1"), "l", "volumen"),
    "lt": (Decimal("1"), "l", "volumen"),
    "litro": (Decimal("1"), "l", "volumen"),
    "litros": (Decimal("1"), "l", "volumen"),
    "unidad": (Decimal("1"), "unidad", "conteo"),
    "unidades": (Decimal("1"), "unidad", "conteo"),
    "und": (Decimal("1"), "unidad", "conteo"),
    "un": (Decimal("1"), "unidad", "conteo"),
}


def normalizar_medida(cantidad: Decimal, unidad: str) -> MedidaNormalizada | None:
    """Convierte a kg, litro o unidad. Devuelve None si la unidad no se reconoce."""
    destino = _FACTOR.get(unidad.strip().lower())
    if destino is None or cantidad <= 0:
        return None
    factor, unidad_base, dimension = destino
    return MedidaNormalizada(
        cantidad=cantidad * factor,
        unidad=unidad_base,
        dimension=dimension,
    )


def misma_dimension(unidad_a: str | None, unidad_b: str | None) -> bool:
    """True solo cuando ambas unidades existen y miden lo mismo."""
    if not unidad_a or not unidad_b:
        return False
    primera = _FACTOR.get(unidad_a.strip().lower())
    segunda = _FACTOR.get(unidad_b.strip().lower())
    return primera is not None and segunda is not None and primera[2] == segunda[2]


def precio_por_unidad_base(precio: Decimal, medida: MedidaNormalizada) -> Decimal:
    """Precio de un kilogramo, un litro o una unidad, en COP con dos decimales."""
    if medida.cantidad <= 0:
        raise ValueError("La medida normalizada debe ser mayor que cero.")
    return (precio / medida.cantidad).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
