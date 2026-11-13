"""Pruebas de configuración. No leen .env ni llaman a la red."""

import pytest

from compras.config import cargar_config


def _aislar_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_TEMPERATURE",
        "OPENAI_BASE_URL",
        "FUENTE_JUMBO",
        "FUENTE_SUPERBOOM",
        "CIUDAD_DEFECTO",
        "MAX_ACLARACIONES",
        "CATALOGO_USER_AGENT",
        "CATALOGO_TIMEOUT",
        "CATALOGO_PAUSA",
        "CATALOGO_MAX_RESULTADOS",
    ):
        monkeypatch.delenv(nombre, raising=False)


def test_valores_por_defecto_sin_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    _aislar_entorno(monkeypatch)
    config = cargar_config(cargar_env=False)
    assert config.api_key is None
    assert config.modelo == "gpt-4o-mini"
    assert config.temperatura == 0
    assert config.base_url is None
    assert config.fuente_jumbo == "web"
    assert config.fuente_superboom == "web"
    assert config.ciudad_defecto == "Medellín"
    assert config.max_aclaraciones == 3
    assert config.catalogo_timeout == 25
    assert config.catalogo_pausa == 2
    assert config.catalogo_max_resultados == 8


def test_la_clave_de_ejemplo_no_cuenta_como_configurada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _aislar_entorno(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-...")
    config = cargar_config(cargar_env=False)
    assert config.api_key is None
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        config.exigir_api_key()


def test_exigir_api_key_devuelve_la_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    _aislar_entorno(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    config = cargar_config(cargar_env=False)
    assert config.exigir_api_key() == "sk-test-123"


@pytest.mark.parametrize("variable", ["FUENTE_JUMBO", "FUENTE_SUPERBOOM"])
@pytest.mark.parametrize("valor", ["csv", "api", "playwright"])
def test_solo_acepta_consulta_web(
    monkeypatch: pytest.MonkeyPatch, variable: str, valor: str
) -> None:
    _aislar_entorno(monkeypatch)
    monkeypatch.setenv(variable, valor)
    with pytest.raises(RuntimeError, match="web"):
        cargar_config(cargar_env=False)


def test_max_aclaraciones_menor_que_uno_se_rechaza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _aislar_entorno(monkeypatch)
    monkeypatch.setenv("MAX_ACLARACIONES", "0")
    with pytest.raises(RuntimeError, match="MAX_ACLARACIONES"):
        cargar_config(cargar_env=False)


def test_max_resultados_fuera_de_rango_se_rechaza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _aislar_entorno(monkeypatch)
    monkeypatch.setenv("CATALOGO_MAX_RESULTADOS", "50")
    with pytest.raises(RuntimeError, match="CATALOGO_MAX_RESULTADOS"):
        cargar_config(cargar_env=False)
