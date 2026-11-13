"""Carga de configuración desde variables de entorno (.env)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

_USER_AGENT = (
    "AsistenteComprasAcademico/0.1 "
    "(proyecto universitario UPB; consulta de catalogo publico)"
)


@dataclass(frozen=True)
class Config:
    """Parámetros de ejecución. La clave de OpenAI puede faltar hasta usar el LLM."""

    api_key: str | None
    modelo: str
    temperatura: float
    base_url: str | None
    fuente_jumbo: str
    fuente_superboom: str
    ciudad_defecto: str
    max_aclaraciones: int
    catalogo_user_agent: str
    catalogo_timeout: float
    catalogo_pausa: float
    catalogo_max_resultados: int

    def exigir_api_key(self) -> str:
        """Devuelve la clave o explica cómo configurarla."""
        if not self.api_key:
            raise RuntimeError(
                "Falta OPENAI_API_KEY. Copia .env.example a .env y completa tu clave."
            )
        return self.api_key


def cargar_config(*, cargar_env: bool = True) -> Config:
    """Lee el entorno y aplica los valores por defecto del proyecto.

    `cargar_env=False` se usa en pruebas para no depender de un archivo .env.
    """
    if cargar_env:
        load_dotenv()

    temperatura = _leer_float("OPENAI_TEMPERATURE", "0")
    if not 0 <= temperatura <= 2:
        raise RuntimeError("OPENAI_TEMPERATURE debe estar entre 0 y 2.")

    max_aclaraciones = _leer_entero("MAX_ACLARACIONES", "3")
    if max_aclaraciones < 1:
        raise RuntimeError("MAX_ACLARACIONES debe ser al menos 1.")

    timeout = _leer_float("CATALOGO_TIMEOUT", "25")
    if timeout <= 0:
        raise RuntimeError("CATALOGO_TIMEOUT debe ser mayor que cero.")

    pausa = _leer_float("CATALOGO_PAUSA", "2")
    if pausa < 0:
        raise RuntimeError("CATALOGO_PAUSA no puede ser negativa.")

    max_resultados = _leer_entero("CATALOGO_MAX_RESULTADOS", "8")
    if not 1 <= max_resultados <= 20:
        raise RuntimeError("CATALOGO_MAX_RESULTADOS debe estar entre 1 y 20.")

    ciudad = os.getenv("CIUDAD_DEFECTO", "Medellín").strip() or "Medellín"
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-..."):
        api_key = None
    user_agent = os.getenv("CATALOGO_USER_AGENT", _USER_AGENT).strip() or _USER_AGENT

    return Config(
        api_key=api_key,
        modelo=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        temperatura=temperatura,
        base_url=base_url,
        fuente_jumbo=_leer_fuente("FUENTE_JUMBO"),
        fuente_superboom=_leer_fuente("FUENTE_SUPERBOOM"),
        ciudad_defecto=ciudad,
        max_aclaraciones=max_aclaraciones,
        catalogo_user_agent=user_agent,
        catalogo_timeout=timeout,
        catalogo_pausa=pausa,
        catalogo_max_resultados=max_resultados,
    )


def _leer_fuente(nombre: str) -> str:
    valor = os.getenv(nombre, "web").strip().lower()
    if valor != "web":
        raise RuntimeError(
            f"{nombre}={valor!r} no está habilitado. "
            "La fuente disponible es 'web': el catálogo público de la tienda."
        )
    return "web"


def _leer_float(nombre: str, defecto: str) -> float:
    texto = os.getenv(nombre, defecto).strip()
    try:
        return float(texto)
    except ValueError as exc:
        raise RuntimeError(f"{nombre} debe ser un número.") from exc


def _leer_entero(nombre: str, defecto: str) -> int:
    texto = os.getenv(nombre, defecto).strip()
    try:
        return int(texto)
    except ValueError as exc:
        raise RuntimeError(f"{nombre} debe ser un entero.") from exc
