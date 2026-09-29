"""Persistencia final: red de notas Markdown para Obsidian.

No se usa SQLite, MongoDB ni Neo4j. Cada noticia y cada entidad debe
tener su propia nota, enlazada con [[wiki-links]].
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.config import DIR_VAULT
from src.conocimiento.utilidades import enlace_obsidian, slugify
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

    CATEGORIAS = {
        "delitos": ("Delitos", "Delito", "Delitos asociados"),
        "personas": ("Personas", "Persona", "Personas relacionadas"),
        "organizaciones": ("Organizaciones", "Organización", "Organizaciones relacionadas"),
        "lugares": ("Lugares", "Lugar", "Lugares"),
        "objetos": ("Objetos", "Objeto", "Objetos"),
    }

    @staticmethod
    def _nombres(data: dict, campo: str) -> list[str]:
        """Nombres de una categoría; personas y objetos vienen como objetos."""
        valores = data.get(campo) or []
        if campo in ("personas", "objetos"):
            valores = [v.get("nombre") for v in valores if isinstance(v, dict)]
        return [v.strip() for v in valores if isinstance(v, str) and v.strip()]

    def _indices(self, noticias: list[dict]) -> dict:
        """Invierte el corpus: por categoría, slug → nombre y noticias donde aparece."""
        indices = {campo: {} for campo in self.CATEGORIAS}
        for data in noticias:
            for campo in self.CATEGORIAS:
                for nombre in self._nombres(data, campo):
                    entrada = indices[campo].setdefault(
                        slugify(nombre), {"nombre": nombre, "noticias": set()}
                    )
                    entrada["noticias"].add(data["id_noticia"])
        return indices

    @staticmethod
    def _roles(noticias: list[dict]) -> dict:
        """slug de persona → roles que el corpus le atribuye."""
        roles: dict[str, set] = {}
        for data in noticias:
            for persona in data.get("personas") or []:
                nombre = (persona.get("nombre") or "").strip()
                rol = (persona.get("rol") or "").strip()
                if nombre and rol:
                    roles.setdefault(slugify(nombre), set()).add(rol)
        return roles

    def _relacionadas(self, campo: str, ids: set, por_id: dict, propio: str) -> list[str]:
        """Entidades de otra categoría que comparten noticia con esta."""
        nombres = {
            nombre
            for nid in ids
            for nombre in self._nombres(por_id.get(nid, {}), campo)
            if slugify(nombre) != propio
        }
        return sorted(nombres)

    def escribir_entidades(self, noticias: list[dict]) -> None:
        """Una nota por delito, persona, organización, lugar y objeto."""
        indices = self._indices(noticias)
        roles = self._roles(noticias)
        por_id = {d["id_noticia"]: d for d in noticias}
        total = 0
        for campo, (carpeta, etiqueta, _) in self.CATEGORIAS.items():
            destino = self.vault / carpeta
            destino.mkdir(parents=True, exist_ok=True)
            for clave, entrada in indices[campo].items():
                lineas = [f"# {entrada['nombre']}", "", f"Tipo: {etiqueta}", ""]
                lineas += self._seccion(
                    "Noticias relacionadas", sorted(entrada["noticias"])
                )
                if campo == "personas" and roles.get(clave):
                    lineas += self._seccion("Rol observado", sorted(roles[clave]), lambda r: f"- {r}")
                for otro, (_, _, titulo) in self.CATEGORIAS.items():
                    if otro == campo:
                        continue
                    lineas += self._seccion(
                        titulo, self._relacionadas(otro, entrada["noticias"], por_id, clave)
                    )
                (destino / f"{clave}.md").write_text(
                    "\n".join(lineas).rstrip() + "\n", encoding="utf-8"
                )
                total += 1
        print(f"    Entidades escritas: {total}")

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
        self.escribir_entidades(noticias)
