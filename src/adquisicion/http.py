"""Cliente HTTP compartido: User-Agent, timeout y pausa entre peticiones."""

from __future__ import annotations

import time

import requests
from requests.utils import get_encoding_from_headers

from src.config import PAUSA_ENTRE_REQUESTS, TIMEOUT_HTTP, USER_AGENT


class ClienteHTTP:
    """Sesión HTTP educada para no sobrecargar servidores de prensa."""

    def __init__(
        self,
        timeout: int = TIMEOUT_HTTP,
        pausa: float = PAUSA_ENTRE_REQUESTS,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.pausa = pausa
        self.sesion = requests.Session()
        self.sesion.headers.update({"User-Agent": user_agent})

    def obtener(self, url: str, permitir_redirects: bool = True) -> requests.Response:
        """GET con pausa previa. Lanza HTTPError si el status no es 2xx."""
        time.sleep(self.pausa)
        respuesta = self.sesion.get(
            url,
            timeout=self.timeout,
            allow_redirects=permitir_redirects,
        )
        respuesta.raise_for_status()
        respuesta.encoding = self._codificacion(respuesta)
        return respuesta

    @staticmethod
    def _codificacion(respuesta: requests.Response) -> str:
        declarada = get_encoding_from_headers(respuesta.headers)
        if declarada and declarada.lower() not in ("iso-8859-1", "latin-1"):
            return declarada
        try:
            respuesta.content.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            return respuesta.apparent_encoding or declarada or "utf-8"

    def texto(self, url: str) -> str:
        """Cuerpo de la respuesta como texto."""
        return self.obtener(url).text

    def url_final(self, url: str) -> str:
        """Sigue redirecciones y devuelve la URL canónica del medio."""
        respuesta = self.obtener(url, permitir_redirects=True)
        return respuesta.url or url
