"""Validación del JSON producido por el LLM.

El LLM no es la fuente de verdad: el código debe verificar el esquema.
Los archivos que rompen el contrato quedan en `fallos`; los que lo cumplen
pero traen datos dudosos quedan en `advertencias` para la auditoría.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.config import DIR_JSON, RUTA_REGISTRO_VALIDACION
from src.conocimiento.utilidades import slugify
from src.modelos import CAMPOS_OBLIGATORIOS, CATALOGO_DELITOS, ROLES_PERMITIDOS, TIPOS_RELACION

PATRON_ID = re.compile(r"^N\d{3,}$")
PATRON_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CLAVES_ELEMENTO = {
    "personas": ("nombre", "rol"),
    "objetos": ("tipo", "nombre", "cantidad", "unidad"),
    "relaciones": ("origen", "tipo", "destino"),
}
CLAVES_TEXTO = ("nombre", "tipo", "origen", "destino")


class ValidadorJSON:
    """Comprueba que cada archivo JSON cumpla el contrato de datos."""

    CAMPOS_OBLIGATORIOS = list(CAMPOS_OBLIGATORIOS)
    CAMPOS_TEXTO = ["titulo", "fecha_publicacion", "fuente", "url", "resumen"]
    CAMPOS_LISTA = ["delitos", "personas", "organizaciones", "lugares", "objetos", "relaciones"]

    def __init__(self, ruta_registro: Path = RUTA_REGISTRO_VALIDACION) -> None:
        self.ruta_registro = ruta_registro
        self.fallos: list[dict] = []
        self.advertencias: list[dict] = []

    def reiniciar(self) -> None:
        self.fallos.clear()
        self.advertencias.clear()

    def validar(self, ruta: str | Path) -> dict:
        """Lee, parsea y valida un JSON. Lanza ValueError si el contrato no se cumple."""
        archivo = Path(ruta)
        try:
            data = json.loads(archivo.read_text(encoding="utf-8"))
            tipo, errores = "contrato", self.errores(data)
        except json.JSONDecodeError as exc:
            tipo, errores = "json_invalido", [str(exc)]
        if errores:
            self.fallos.append({"id_noticia": archivo.stem, "tipo": tipo, "errores": errores})
            raise ValueError(f"{archivo.name}: " + "; ".join(errores))
        for tipo, detalle in self.dudas(data):
            self.advertencias.append({"id_noticia": archivo.stem, "tipo": tipo, "detalle": detalle})
        return data

    def validar_directorio(self, dir_json: Path = DIR_JSON) -> tuple[list[dict], list[str]]:
        """Valida los N###.json de la carpeta. Devuelve (válidos, ids inválidos)."""
        validos, invalidos = [], []
        for archivo in sorted(Path(dir_json).glob("N*.json")):
            try:
                validos.append(self.validar(archivo))
            except ValueError:
                invalidos.append(archivo.stem)
        return validos, invalidos

    def errores(self, data) -> list[str]:
        """Incumplimientos del contrato; lista vacía si el JSON es válido."""
        if not isinstance(data, dict):
            return ["no es un objeto JSON"]
        errores = [f"falta el campo '{c}'" for c in self.CAMPOS_OBLIGATORIOS if c not in data]
        if not PATRON_ID.match(str(data.get("id_noticia"))):
            errores.append("id_noticia debe tener la forma N001")
        for campo in self.CAMPOS_TEXTO:
            if data.get(campo) is not None and not isinstance(data[campo], str):
                errores.append(f"'{campo}' debe ser texto o null")
        fecha = data.get("fecha_publicacion")
        if isinstance(fecha, str) and not PATRON_FECHA.match(fecha):
            errores.append("fecha_publicacion debe ser AAAA-MM-DD")
        for campo in self.CAMPOS_LISTA:
            valores = data.get(campo, [])
            if not isinstance(valores, list):
                errores.append(f"'{campo}' debe ser una lista")
                continue
            claves = CLAVES_ELEMENTO.get(campo)
            for i, valor in enumerate(valores):
                if not self._elemento_valido(valor, claves):
                    forma = f"objeto con {', '.join(claves)}" if claves else "texto no vacío"
                    errores.append(f"{campo}[{i}] debe ser {forma}")
        return errores

    @staticmethod
    def _elemento_valido(valor, claves) -> bool:
        if claves is None:
            return isinstance(valor, str) and bool(valor.strip())
        if not isinstance(valor, dict) or any(k not in valor for k in claves):
            return False
        textos = all(
            isinstance(valor[k], str) and valor[k].strip() for k in claves if k in CLAVES_TEXTO
        )
        cantidad = valor.get("cantidad")
        return textos and (cantidad is None or isinstance(cantidad, (int, float)))

    def dudas(self, data: dict) -> list[tuple[str, str]]:
        """Datos que cumplen el contrato pero conviene revisar a mano."""
        avisos = [("delito_fuera_catalogo", d) for d in data["delitos"] if d not in CATALOGO_DELITOS]
        avisos += [
            ("rol_desconocido", f"{p['nombre']} ({p['rol']})")
            for p in data["personas"]
            if p["rol"] is not None and p["rol"] not in ROLES_PERMITIDOS
        ]
        entidades = {self._clave(v) for c in ("delitos", "organizaciones", "lugares") for v in data[c]}
        entidades |= {self._clave(e["nombre"]) for c in ("personas", "objetos") for e in data[c]}
        for r in data["relaciones"]:
            texto = f"{r['origen']} -- {r['tipo']} --> {r['destino']}"
            if r["tipo"] not in TIPOS_RELACION:
                avisos.append(("tipo_relacion_desconocido", texto))
            if not {self._clave(r["origen"]), self._clave(r["destino"])} <= entidades:
                avisos.append(("relacion_sin_respaldo", texto))
        return avisos

    @staticmethod
    def _clave(valor) -> str:
        """Compara nombres sin importar mayúsculas, tildes ni espacios."""
        return slugify(str(valor)).lower()

    def guardar_registro(self) -> Path:
        contenido = {"fallos": self.fallos, "advertencias": self.advertencias}
        self.ruta_registro.write_text(
            json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.ruta_registro
