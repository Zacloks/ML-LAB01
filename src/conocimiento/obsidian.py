"""Persistencia final: red de notas Markdown para Obsidian.

No se usa SQLite, MongoDB ni Neo4j. Cada noticia y cada entidad debe
tener su propia nota, enlazada con [[wiki-links]].
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.config import DIR_VAULT
from src.conocimiento.utilidades import enlace_obsidian
from src.excepciones import EtapaPendienteAlumno


class EscritorObsidian(ABC):
    """Contrato para generar la bóveda a partir de JSON validado."""

    @abstractmethod
    def escribir_noticia(self, data: dict) -> Path:
        """Crea obsidian_vault/Noticias/{id_noticia}.md con frontmatter y enlaces."""

    @abstractmethod
    def escribir_entidades(self, noticias: list[dict]) -> None:
        """Agrega notas de delitos, personas, organizaciones, lugares y objetos."""

    @abstractmethod
    def escribir_indice(self, noticias: list[dict]) -> Path:
        """Crea obsidian_vault/00_Indice.md."""

    @abstractmethod
    def escribir_vault(self, noticias: list[dict]) -> None:
        """Orquesta noticia + entidades + índice."""


class EscritorVaultObsidian(EscritorObsidian):
    """Implementación objetivo del laboratorio.

    Use src.conocimiento.utilidades.slugify y enlace_obsidian.
    Jerarquía esperada:
        obsidian_vault/
        ├── 00_Indice.md
        ├── Noticias/
        ├── Delitos/
        ├── Personas/
        ├── Organizaciones/
        ├── Lugares/
        ├── Objetos/
        └── Relaciones/
    """

    def __init__(self, vault: Path = DIR_VAULT) -> None:
        self.vault = vault

    SUBCARPETAS = (
        "Noticias",
        "Delitos",
        "Personas",
        "Organizaciones",
        "Lugares",
        "Objetos",
        "Relaciones",
    )

    def escribir_noticia(self, data: dict) -> Path:
        """JSON validado → Noticias/{id}.md con frontmatter y [[enlaces]]."""
        lineas = self._frontmatter(data)
        lineas += [f"# {data.get('titulo') or data['id_noticia']}", ""]

        resumen = (data.get("resumen") or "").strip()
        if resumen:
            lineas += ["## Resumen", resumen, ""]

        lineas += self._seccion("Delitos", data.get("delitos"))
        lineas += self._seccion("Personas", data.get("personas"), self._linea_persona)
        lineas += self._seccion("Organizaciones", data.get("organizaciones"))
        lineas += self._seccion("Lugares", data.get("lugares"))
        lineas += self._seccion("Objetos", data.get("objetos"), self._linea_objeto)
        lineas += self._seccion("Relaciones", data.get("relaciones"), self._linea_relacion)

        destino = self.vault / "Noticias" / f"{data['id_noticia']}.md"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("\n".join(lineas).rstrip() + "\n", encoding="utf-8")
        return destino

    @staticmethod
    def _frontmatter(data: dict) -> list[str]:
        """Bloque YAML con los metadatos de trazabilidad de la noticia."""
        campos = {
            "id": data["id_noticia"],
            "fecha_publicacion": data.get("fecha_publicacion"),
            "fuente": data.get("fuente"),
            "url": data.get("url"),
        }
        lineas = ["---"]
        for clave, valor in campos.items():
            lineas.append(f'{clave}: "{valor}"' if valor else f"{clave}:")
        return lineas + ["---", ""]

    @staticmethod
    def _seccion(titulo: str, valores, formato=None) -> list[str]:
        """Encabezado y lista de una sección; vacía si no hay valores."""
        valores = valores or []
        if not valores:
            return []
        formato = formato or (lambda v: f"- {enlace_obsidian(v)}")
        lineas = [f"## {titulo}"]
        lineas += [linea for linea in (formato(v) for v in valores) if linea]
        return lineas + [""]

    @staticmethod
    def _linea_persona(persona: dict) -> str:
        """'- [[Juan_Perez|Juan Perez]] - imputado'."""
        nombre = (persona.get("nombre") or "").strip()
        if not nombre:
            return ""
        rol = (persona.get("rol") or "").strip()
        return f"- {enlace_obsidian(nombre)}" + (f" - {rol}" if rol else "")

    @staticmethod
    def _linea_objeto(objeto: dict) -> str:
        """'- [[cocaina]] - sustancia, 7 kilos'; omite lo que no aparezca."""
        nombre = (objeto.get("nombre") or "").strip()
        if not nombre:
            return ""
        cantidad, unidad = objeto.get("cantidad"), (objeto.get("unidad") or "").strip()
        detalle = " ".join(str(p) for p in (cantidad, unidad) if p not in (None, ""))
        tipo = (objeto.get("tipo") or "").strip()
        sufijo = ", ".join(p for p in (tipo, detalle) if p)
        return f"- {enlace_obsidian(nombre)}" + (f" - {sufijo}" if sufijo else "")

    @staticmethod
    def _linea_relacion(relacion: dict) -> str:
        """'- [[origen]] -- OPERA_EN --> [[destino]]'."""
        origen = (relacion.get("origen") or "").strip()
        destino = (relacion.get("destino") or "").strip()
        tipo = (relacion.get("tipo") or "").strip()
        if not (origen and destino and tipo):
            return ""
        return f"- {enlace_obsidian(origen)} -- {tipo} --> {enlace_obsidian(destino)}"

    def escribir_entidades(self, noticias: list[dict]) -> None:
        # TODO(alumno): índices con defaultdict(set) agrupando por entidad.
        raise EtapaPendienteAlumno(
            modulo="src.conocimiento.obsidian.EscritorVaultObsidian.escribir_entidades",
            pista="Una nota por delito/persona/lugar con la lista de noticias relacionadas.",
        )

    def escribir_indice(self, noticias: list[dict]) -> Path:
        # TODO(alumno): índice navegable de toda la bóveda.
        raise EtapaPendienteAlumno(
            modulo="src.conocimiento.obsidian.EscritorVaultObsidian.escribir_indice",
            pista="Escriba 00_Indice.md listando noticias y entidades.",
        )

    def escribir_vault(self, noticias: list[dict]) -> None:
        """Crea la jerarquía del vault y escribe una nota por noticia."""
        for carpeta in self.SUBCARPETAS:
            (self.vault / carpeta).mkdir(parents=True, exist_ok=True)
        for data in noticias:
            self.escribir_noticia(data)
        print(f"    Noticias escritas: {len(noticias)}")
