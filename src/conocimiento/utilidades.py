"""Nombres de archivo estables para enlaces de Obsidian."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """'Tráfico de drogas' → 'Trafico_de_drogas'. Nunca vacío."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    text = text.strip("_")
    return text or "sin_nombre"


def enlace_obsidian(nombre: str) -> str:
    """'Tráfico de drogas' → '[[Trafico_de_drogas|Tráfico de drogas]]'."""
    texto = (nombre or "").strip()
    destino = slugify(texto)
    return f"[[{destino}]]" if destino == texto else f"[[{destino}|{texto}]]"
