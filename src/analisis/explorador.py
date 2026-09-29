"""Data Understanding sobre data/json/N*.json."""

from __future__ import annotations

import json
import random
from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from src.config import DIR_FIGURAS, DIR_JSON, DIR_RESULTADOS, RUTA_URLS  # noqa: E402
from src.modelos import CAMPOS_OBLIGATORIOS  # noqa: E402
from src.validacion.validador import ValidadorJSON  # noqa: E402

AZUL = "#2a78d6"
NARANJO = "#eb6834"


class ExploradorDatos:
    """Estadísticas y gráficos del corpus estructurado."""

    def __init__(self, dir_json: Path = DIR_JSON, ruta_urls: Path = RUTA_URLS,
                 dir_resultados: Path = DIR_RESULTADOS, dir_figuras: Path = DIR_FIGURAS) -> None:
        self.dir_json = Path(dir_json)
        self.ruta_urls = Path(ruta_urls)
        self.dir_resultados = Path(dir_resultados)
        self.dir_figuras = Path(dir_figuras)
        self.validador = ValidadorJSON()
        self.metricas: dict = {}
        self.noticias: list[dict] = []
        self.invalidos: list[str] = []

    def cargar(self) -> None:
        self.urls = pd.read_csv(self.ruta_urls, dtype=str).fillna("")
        self.noticias, self.invalidos = self.validador.validar_directorio(self.dir_json)

    def _conteo(self, campo: str) -> pd.Series:
        nombres = []
        for d in self.noticias:
            valores = d.get(campo) or []
            if campo in ("personas", "objetos"):
                valores = [v["nombre"] for v in valores]
            nombres += set(valores)
        return pd.Series(nombres, dtype=str).value_counts()

    def _guardar(self, fig, nombre: str, titulo: str) -> None:
        ax = fig.axes[0]
        ax.set_title(titulo, loc="left", fontsize=10, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        self.dir_figuras.mkdir(parents=True, exist_ok=True)
        fig.savefig(self.dir_figuras / f"{nombre}.png", dpi=200)
        plt.close(fig)
        print(f"    resultados/figuras/{nombre}.png")

    def _barras(self, serie: pd.Series, nombre: str, titulo: str, eje: str) -> None:
        serie = serie.sort_values()
        fig, ax = plt.subplots(figsize=(6.4, max(2.2, 0.3 * len(serie) + 1)))
        ax.bar_label(ax.barh(serie.index, serie.values, color=AZUL), padding=3, fontsize=7)
        ax.set_xlabel(eje)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.tick_params(labelsize=8)
        self._guardar(fig, nombre, titulo)

    def noticias_por_fuente(self) -> None:
        tabla = pd.DataFrame({
            "URLs": self.urls["fuente"].value_counts(),
            "JSON válidos": pd.Series(Counter(d["fuente"] for d in self.noticias)),
        }).fillna(0).astype(int)
        ax = tabla.plot.barh(color=[AZUL, NARANJO], figsize=(6.4, 2.6))
        for barras in ax.containers:
            ax.bar_label(barras, padding=3, fontsize=7)
        ax.set_xlabel("Noticias")
        self._guardar(ax.figure, "01_noticias_por_fuente", "Noticias por fuente")
        self.metricas["noticias_por_fuente"] = tabla.to_dict(orient="index")

    def delitos_frecuentes(self) -> None:
        conteo = self._conteo("delitos").head(10)
        self._barras(conteo, "02_delitos_frecuentes", "Delitos más frecuentes", "Noticias")
        self.metricas["delitos_frecuentes"] = conteo.to_dict()

    def lugares_frecuentes(self) -> None:
        conteo = self._conteo("lugares").head(15)
        self._barras(conteo, "03_lugares_frecuentes", "Lugares más mencionados", "Noticias")
        self.metricas["lugares_frecuentes"] = conteo.to_dict()

    def delitos_por_lugar(self) -> None:
        pares = pd.DataFrame(
            [(de, lu) for d in self.noticias for de in set(d["delitos"]) for lu in set(d["lugares"])],
            columns=["delito", "lugar"],
        )
        tabla = pd.crosstab(pares["delito"], pares["lugar"])
        tabla = tabla.loc[self._conteo("delitos").index[:6], self._conteo("lugares").index[:10]]
        fig, ax = plt.subplots(figsize=(7.2, 0.45 * len(tabla) + 2))
        ax.imshow(tabla.values, cmap="Blues", aspect="auto")
        ax.set_xticks(range(tabla.shape[1]), tabla.columns, rotation=40, ha="right", fontsize=7)
        ax.set_yticks(range(tabla.shape[0]), tabla.index, fontsize=7)
        for i in range(tabla.shape[0]):
            for j in range(tabla.shape[1]):
                valor = tabla.values[i, j]
                if valor:
                    ax.text(j, i, valor, ha="center", va="center", fontsize=7,
                            color="white" if valor > tabla.values.max() / 2 else "black")
        self._guardar(fig, "04_delitos_por_lugar", "Delitos por lugar (noticias en común)")

    def entidades_por_noticia(self) -> None:
        df = pd.DataFrame({
            "Personas": [len(d["personas"]) for d in self.noticias],
            "Organizaciones": [len(d["organizaciones"]) for d in self.noticias],
        })
        tabla = df.apply(lambda c: c.value_counts()).fillna(0).astype(int).sort_index()
        ax = tabla.plot.bar(color=[AZUL, NARANJO], rot=0, figsize=(6.4, 3))
        ax.set_xlabel("Entidades extraídas en la noticia")
        ax.set_ylabel("Noticias")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        self._guardar(ax.figure, "05_entidades_por_noticia", "Personas y organizaciones por noticia")
        self.metricas["promedio_por_noticia"] = df.mean().round(2).to_dict()
        self.metricas["noticias_sin_personas"] = int((df["Personas"] == 0).sum())

    def campos_faltantes(self) -> None:
        vacios = pd.Series({
            campo: 100 * sum(d.get(campo) in (None, "", []) for d in self.noticias) / len(self.noticias)
            for campo in CAMPOS_OBLIGATORIOS
        }).round(1)
        self._barras(vacios, "06_campos_faltantes", "Campos vacíos o nulos", "% de noticias")
        self.metricas["porcentaje_campos_vacios"] = vacios.to_dict()

    def evolucion_temporal(self) -> None:
        fechas = pd.to_datetime(pd.Series([d["fecha_publicacion"] for d in self.noticias]),
                                errors="coerce").dropna()
        por_dia = fechas.dt.date.value_counts().sort_index()
        fig, ax = plt.subplots(figsize=(6.4, 2.8))
        ax.bar(por_dia.index, por_dia.values, color=AZUL)
        ax.set_ylabel("Noticias")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        fig.autofmt_xdate()
        self._guardar(fig, "07_evolucion_temporal", "Noticias por fecha de publicación")
        self.metricas["noticias_sin_fecha"] = len(self.noticias) - len(fechas)

    def calidad(self) -> None:
        duplicadas = [
            (a["id_noticia"], b["id_noticia"])
            for a, b in combinations(self.noticias, 2)
            if a["url"] == b["url"]
            or SequenceMatcher(None, a["titulo"] or "", b["titulo"] or "").ratio() > 0.85
        ]
        avisos = Counter(a["tipo"] for a in self.validador.advertencias)
        ids = {d["id_noticia"] for d in self.noticias}
        self.metricas.update({
            "urls": len(self.urls),
            "json_validos": len(self.noticias),
            "json_invalidos": self.invalidos,
            "sin_json": sorted(set(self.urls["id_noticia"]) - ids - set(self.invalidos)),
            "duplicadas": duplicadas,
            "relaciones": sum(len(d["relaciones"]) for d in self.noticias),
            "relaciones_sin_respaldo": avisos["relacion_sin_respaldo"],
            "delitos_fuera_catalogo": avisos["delito_fuera_catalogo"],
            "roles": dict(Counter(p["rol"] for d in self.noticias for p in d["personas"])),
        })

    def muestra_auditoria(self, n: int = 10) -> None:
        ruta = self.dir_resultados / "auditoria.csv"
        if ruta.exists():
            return
        muestra = sorted(random.Random(42).sample(self.noticias, min(n, len(self.noticias))),
                         key=lambda d: d["id_noticia"])
        columnas = ["inventa_entidades", "confunde_roles", "nombres_mal", "relacion_dudosa",
                    "observaciones"]
        filas = [{"id_noticia": d["id_noticia"], "url": d["url"], **dict.fromkeys(columnas, "")}
                 for d in muestra]
        pd.DataFrame(filas).to_csv(ruta, index=False)

    def ejecutar(self) -> None:
        self.cargar()
        if not self.noticias:
            print("  No hay JSON válidos. Ejecute primero: python main.py extraer")
            return
        self.dir_resultados.mkdir(parents=True, exist_ok=True)
        self.noticias_por_fuente()
        self.delitos_frecuentes()
        self.lugares_frecuentes()
        self.delitos_por_lugar()
        self.entidades_por_noticia()
        self.campos_faltantes()
        self.evolucion_temporal()
        self.calidad()
        self.muestra_auditoria()
        (self.dir_resultados / "metricas.json").write_text(
            json.dumps(self.metricas, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        m = self.metricas
        print(f"  URLs: {m['urls']} | JSON válidos: {m['json_validos']} | "
              f"inválidos: {len(m['json_invalidos'])} | sin JSON: {len(m['sin_json'])}")
        print(f"  Duplicadas: {len(m['duplicadas'])} | "
              f"relaciones sin respaldo: {m['relaciones_sin_respaldo']}/{m['relaciones']}")
