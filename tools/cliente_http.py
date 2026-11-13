"""Descarga identificable de catálogos públicos.

El cliente envía un User-Agent del proyecto, espera entre peticiones al mismo
dominio y no cambia de identidad ni de IP. Las pruebas inyectan otro fetcher.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from compras.config import cargar_config

_ZONA = ZoneInfo("America/Bogota")
Fetcher = Callable[..., "RespuestaHttp"]


@dataclass(frozen=True)
class RespuestaHttp:
    status: int
    cuerpo: str
    url_final: str


def hoy_bogota() -> date:
    return datetime.now(_ZONA).date()


def descargar_urllib(url: str, *, user_agent: str, timeout: float) -> RespuestaHttp:
    """GET simple. 206 cuenta como respuesta válida: VTEX lo usa en búsquedas paginadas."""
    peticion = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.9",
        },
    )
    try:
        with urlopen(peticion, timeout=timeout) as respuesta:
            cuerpo = respuesta.read().decode("utf-8", errors="replace")
            return RespuestaHttp(respuesta.status, cuerpo, respuesta.geturl())
    except HTTPError as exc:
        cuerpo = exc.read().decode("utf-8", errors="replace")
        return RespuestaHttp(exc.code, cuerpo, url)
    except URLError as exc:
        raise ConnectionError(f"Sin respuesta de {urlparse(url).netloc}: {exc.reason}") from exc


class ClienteCatalogo:
    """Una consulta a la vez por dominio, con la pausa configurada."""

    def __init__(
        self,
        *,
        user_agent: str = "AsistenteComprasAcademico/0.1 (proyecto universitario UPB)",
        timeout: float = 25,
        pausa: float = 2,
        max_resultados: int = 8,
        fetcher: Fetcher | None = None,
        hoy: Callable[[], date] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.pausa = pausa
        self.max_resultados = max_resultados
        self._fetcher = fetcher or descargar_urllib
        self._hoy = hoy or hoy_bogota
        self._ultimo: dict[str, float] = {}
        self._lock = threading.Lock()

    @classmethod
    def desde_config(cls) -> "ClienteCatalogo":
        config = cargar_config()
        return cls(
            user_agent=config.catalogo_user_agent,
            timeout=config.catalogo_timeout,
            pausa=config.catalogo_pausa,
            max_resultados=config.catalogo_max_resultados,
        )

    def hoy(self) -> date:
        return self._hoy()

    def obtener(self, url: str) -> RespuestaHttp:
        host = urlparse(url).netloc
        with self._lock:
            anterior = self._ultimo.get(host, 0.0)
            espera = self.pausa - (time.monotonic() - anterior)
            self._ultimo[host] = time.monotonic() + max(espera, 0)
        if espera > 0:
            time.sleep(espera)
        return self._fetcher(url, user_agent=self.user_agent, timeout=self.timeout)
