"""Construcción del LLM y de la cadena de interpretación."""

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from compras.config import cargar_config
from compras.prompts import crear_prompt, crear_prompt_aclaracion, crear_prompt_equivalencias
from compras.schemas import AclaracionLLM, ClasificacionEquivalenciasLLM, SolicitudLLM


def crear_modelo() -> ChatOpenAI:
    config = cargar_config()
    return ChatOpenAI(
        model=config.modelo,
        temperature=config.temperatura,
        api_key=config.exigir_api_key(),
        base_url=config.base_url,
        timeout=60,
        max_retries=2,
    )


def construir_interpretador(llm: Optional[BaseChatModel] = None) -> Runnable:
    """prompt | LLM con salida SolicitudLLM.

    method="json_schema" y strict=True usan Structured Outputs de OpenAI.
    La cadena no calcula precios: el schema no tiene campos de dinero.
    """
    modelo = llm or crear_modelo()
    estructurado = modelo.with_structured_output(
        SolicitudLLM, method="json_schema", strict=True
    )
    return crear_prompt() | estructurado


def construir_clasificador_equivalencias(llm: Optional[BaseChatModel] = None) -> Runnable:
    """prompt | LLM con salida ClasificacionEquivalenciasLLM.

    El schema no tiene precios. Python convierte unidades y calcula después.
    """
    modelo = llm or crear_modelo()
    estructurado = modelo.with_structured_output(
        ClasificacionEquivalenciasLLM, method="json_schema", strict=True
    )
    return crear_prompt_equivalencias() | estructurado


def construir_facilitador_aclaraciones(llm: Optional[BaseChatModel] = None) -> Runnable:
    """prompt | LLM con salida AclaracionLLM.

    Propone la corrección para que la persona la confirme. No consulta tiendas
    ni calcula precios: el schema no tiene campos de dinero.
    """
    modelo = llm or crear_modelo()
    estructurado = modelo.with_structured_output(
        AclaracionLLM, method="json_schema", strict=True
    )
    return crear_prompt_aclaracion() | estructurado
