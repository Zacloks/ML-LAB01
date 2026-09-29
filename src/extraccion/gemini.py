"""Extractor Gemini: texto limpio → JSON del contrato del laboratorio.

Solo se extrae información explícita en la noticia. El código fija
id_noticia, fuente, url y fecha desde los metadatos capturados para que el
modelo no los adivine; el contrato lo verifica src/validacion.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from src.config import (
    DIR_JSON,
    DIR_RAW,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_MODELOS_RESPALDO,
    GEMINI_THINKING_LEVEL,
    RUTA_REGISTRO_EXTRACCION,
)
from src.modelos import (
    CAMPOS_OBLIGATORIOS,
    CATALOGO_DELITOS,
    ROLES_PERMITIDOS,
    TIPOS_OBJETO,
    TIPOS_RELACION,
    NoticiaFuente,
)

CODIGOS_REINTENTABLES = {408, 429, 500, 502, 503, 504}
PATRON_FECHA_URL = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")
PATRON_FECHA_HTML = re.compile(r"(?:published_time|datePublished)\D{0,40}(\d{4}-\d{2}-\d{2})")

PROMPT_BASE = """Analiza la siguiente noticia delictual.
Extrae solamente informacion explicita. No inventes datos.
Devuelve exclusivamente JSON valido, sin explicaciones.
Campos obligatorios:
- id_noticia, titulo, fecha_publicacion, fuente, url, resumen
- delitos, personas (nombre y rol), organizaciones, lugares
- objetos, relaciones (origen, tipo, destino)
Si un dato no aparece, usa null o una lista vacia.
"""

REGLAS = f"""Estructura la siguiente noticia delictual chilena para un grafo de conocimiento.
1. Extrae solo informacion explicita. No inventes datos, entidades, roles ni relaciones.
   Si un dato no aparece, usa null o una lista vacia.
2. Roles permitidos: {", ".join(ROLES_PERMITIDOS)}. No son equivalentes: detenido
   (aprehendido), imputado (formalizado), acusado (con acusacion formal), condenado (con
   sentencia). Una victima tiene rol victima aunque sea policia. Nunca atribuyas
   culpabilidad que la noticia no afirme.
3. delitos: solo los que la noticia afirma que ocurrieron o se investigan, no hipotesis.
   Prefiere este catalogo: {", ".join(CATALOGO_DELITOS)}.
4. personas: solo con nombre propio, no descritas por edad, iniciales o nacionalidad.
5. organizaciones normalizadas: Carabineros, PDI, Fiscalia (con la zona si aparece),
   Gendarmeria.
6. lugares: comunas, ciudades, regiones, paises o sectores, cada uno por separado.
7. objetos: armas, drogas, vehiculos, dinero u otros; cantidad y unidad solo si aparecen.
8. relaciones: solo entre entidades ya listadas y escritas igual. INVESTIGADO_POR y
   VICTIMA_DE van de persona a delito; DETENIDO_EN de persona a lugar; DETENIDO_POR y
   PERTENECE_A de persona a organizacion; OPERA_EN de organizacion a lugar; OCURRIO_EN de
   delito a lugar; INCAUTADO_EN de objeto a lugar; INVESTIGA de organizacion a delito.
9. Nombres de entidades sin tildes (Region Metropolitana, Curacavi). titulo y resumen con
   ortografia normal; el resumen en dos o tres oraciones neutras.
"""


def esquema_respuesta() -> dict:
    """Esquema que obliga a Gemini a responder con la forma del contrato."""
    texto = {"type": "STRING"}
    nulo = {"type": "STRING", "nullable": True}

    def objeto(**campos):
        return {"type": "OBJECT", "properties": campos, "required": list(campos)}

    def lista(item):
        return {"type": "ARRAY", "items": item}

    return objeto(
        id_noticia=texto, titulo=nulo, fecha_publicacion=nulo, fuente=nulo, url=nulo, resumen=nulo,
        delitos=lista(texto),
        personas=lista(objeto(nombre=texto, rol={**nulo, "enum": list(ROLES_PERMITIDOS)})),
        organizaciones=lista(texto),
        lugares=lista(texto),
        objetos=lista(objeto(
            tipo={**texto, "enum": list(TIPOS_OBJETO)}, nombre=texto,
            cantidad={"type": "NUMBER", "nullable": True}, unidad=nulo,
        )),
        relaciones=lista(objeto(
            origen=texto, tipo={**texto, "enum": list(TIPOS_RELACION)}, destino=texto,
        )),
    )


class ExtractorLLM(ABC):
    """Interfaz de cualquier extractor basado en modelo generativo."""

    @abstractmethod
    def construir_prompt(self, noticia: NoticiaFuente) -> str:
        """Arma el prompt con el esquema JSON y el texto de la noticia."""

    @abstractmethod
    def extraer(self, noticia: NoticiaFuente) -> dict:
        """Devuelve un diccionario que cumple el contrato JSON del laboratorio."""


class ExtractorGemini(ExtractorLLM):
    """Extractor oficial del laboratorio (Gemini).

    modo="esquema" usa las reglas y el esquema de respuesta (lo que corre el
    pipeline). modo="libre" usa solo el prompt base de la guía, para comparar
    cuántos JSON válidos produce cada enfoque.
    Ante 429 o errores 5xx reintenta con espera creciente; si un modelo agota
    su cuota diaria, sigue con los de GEMINI_MODELOS_RESPALDO.
    """

    MAX_CARACTERES = 15000
    REINTENTOS = 4
    PAUSA_ENTRE_LLAMADAS = 6

    def __init__(
        self,
        dir_json: Path = DIR_JSON,
        modo: str = "esquema",
        modelo: str = GEMINI_MODEL,
        ruta_registro: Path = RUTA_REGISTRO_EXTRACCION,
    ) -> None:
        self.dir_json = dir_json
        self.dir_json.mkdir(parents=True, exist_ok=True)
        self.modo = modo
        self.modelo = modelo
        self.respaldo = [m for m in GEMINI_MODELOS_RESPALDO if m != modelo]
        self.ruta_registro = ruta_registro
        self.registro: list[dict] = []
        self._cliente = None

    def construir_prompt(self, noticia: NoticiaFuente) -> str:
        texto = (noticia.texto_limpio or "").strip()[: self.MAX_CARACTERES]
        datos = f"id_noticia: {noticia.id_noticia}\nfuente: {noticia.fuente}\nurl: {noticia.url}\n"
        if self.modo == "libre":
            return f"{PROMPT_BASE}{datos}NOTICIA:\n{texto}\n"
        fecha = self._fecha(noticia) or "desconocida, usa la del texto si aparece"
        return f"{REGLAS}\n{datos}fecha_publicacion: {fecha}\n\nNOTICIA:\n{texto}\n"

    def extraer(self, noticia: NoticiaFuente) -> dict:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "Falta GEMINI_API_KEY. Copie .env.example a .env y complete la clave. "
                "Nunca suba .env a GitHub."
            )
        entrada = {
            "id_noticia": noticia.id_noticia,
            "modo": self.modo,
            "estado": "error",
            "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        }
        self.registro.append(entrada)
        try:
            data = self._completar(self._pedir_json(self.construir_prompt(noticia), entrada), noticia)
            ruta = self.dir_json / f"{noticia.id_noticia}.json"
            ruta.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            entrada["estado"] = "ok"
            return data
        except Exception as exc:
            entrada["detalle"] = str(exc)[:300]
            raise
        finally:
            time.sleep(self.PAUSA_ENTRE_LLAMADAS)

    def _pedir_json(self, prompt: str, entrada: dict) -> dict:
        """Llama al modelo hasta obtener un objeto JSON o agotar los reintentos."""
        for intento in range(1, self.REINTENTOS + 1):
            entrada.update(modelo=self.modelo, intentos=intento)
            try:
                return self._parsear(self._generar(prompt))
            except Exception as exc:
                codigo = getattr(exc, "code", None)
                if codigo == 429 and "PerDay" in str(exc):
                    if not self.respaldo:
                        raise RuntimeError("cuota diaria agotada en todos los modelos") from exc
                    self.modelo = self.respaldo.pop(0)
                    print(f"    Cuota diaria agotada; se continúa con {self.modelo}")
                    continue
                reintentable = isinstance(exc, ValueError) or codigo in CODIGOS_REINTENTABLES
                if intento == self.REINTENTOS or not reintentable:
                    raise
                espera = 10 * 2 ** (intento - 1)
                print(f"    Intento {intento} falló ({str(exc)[:100]}); reintento en {espera}s")
                time.sleep(espera)
        raise RuntimeError("sin respuesta válida del modelo")

    def _generar(self, prompt: str) -> str:
        from google import genai
        from google.genai import types

        if self._cliente is None:
            self._cliente = genai.Client(api_key=GEMINI_API_KEY)
        config = types.GenerateContentConfig(
            temperature=0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            # Las noticias policiales describen violencia; con el umbral por
            # defecto algunas respuestas se bloquean.
            safety_settings=[
                types.SafetySetting(category=f"HARM_CATEGORY_{c}", threshold="BLOCK_ONLY_HIGH")
                for c in ("DANGEROUS_CONTENT", "HARASSMENT", "HATE_SPEECH", "SEXUALLY_EXPLICIT")
            ],
            thinking_config=(
                types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL)
                if GEMINI_THINKING_LEVEL else None
            ),
            response_mime_type="application/json" if self.modo == "esquema" else None,
            response_schema=esquema_respuesta() if self.modo == "esquema" else None,
        )
        respuesta = self._cliente.models.generate_content(
            model=self.modelo, contents=prompt, config=config
        )
        return (respuesta.text or "").strip()

    @staticmethod
    def _parsear(bruto: str) -> dict:
        """Quita los fences ```json si el modelo los agrega y exige un objeto JSON."""
        texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto.strip())
        try:
            data = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ValueError(f"el modelo no devolvió JSON válido: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("el modelo no devolvió un objeto JSON")
        return data

    def _completar(self, data: dict, noticia: NoticiaFuente) -> dict:
        """Fija los metadatos que el modelo no debe adivinar y ordena las claves."""
        if self.modo == "esquema":
            data = {campo: data.get(campo) for campo in CAMPOS_OBLIGATORIOS}
        fecha = self._fecha(noticia) or str(data.get("fecha_publicacion") or "")[:10]
        data.update(
            id_noticia=noticia.id_noticia,
            fuente=noticia.fuente,
            url=noticia.url,
            fecha_publicacion=fecha or None,
        )
        return data

    @staticmethod
    def _fecha(noticia: NoticiaFuente) -> str | None:
        """Fecha AAAA-MM-DD desde los metadatos del HTML crudo o desde la URL."""
        html = DIR_RAW / f"{noticia.id_noticia}.html"
        if html.exists():
            encontrada = PATRON_FECHA_HTML.search(html.read_text(encoding="utf-8"))
            if encontrada:
                return encontrada.group(1)
        encontrada = PATRON_FECHA_URL.search(noticia.url or "")
        return "-".join(encontrada.groups()) if encontrada else None

    def guardar_registro(self) -> Path:
        """Guarda el último intento de cada noticia, conservando corridas anteriores."""
        previos = []
        if self.ruta_registro.exists():
            previos = json.loads(self.ruta_registro.read_text(encoding="utf-8"))
        filas = {fila["id_noticia"]: fila for fila in previos + self.registro}
        ordenadas = [filas[clave] for clave in sorted(filas)]
        self.ruta_registro.write_text(
            json.dumps(ordenadas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.ruta_registro
