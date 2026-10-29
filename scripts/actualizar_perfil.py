#!/usr/bin/env python3
"""Mantiene al día el README del perfil.

Reescribe únicamente dos bloques delimitados por marcadores:

- CIFRAS:INICIO / CIFRAS:FIN: repositorios públicos, paquetes en PyPI y sitios desplegados.
- ACTIVIDAD:INICIO / ACTIVIDAD:FIN: últimos eventos públicos de GitHub.

Si una fuente falla, se conserva lo que ya estaba publicado en el README.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USUARIO = "jeironpro"
PAQUETES_PYPI = ("diagram-db", "pulsar-psr")
CATALOGO_WEBS = "https://raw.githubusercontent.com/jeironpro/webs/main/assets/projects.json"
README = Path(__file__).resolve().parent.parent / "README.md"

INICIO_ACTIVIDAD = "<!-- ACTIVIDAD:INICIO -->"
FIN_ACTIVIDAD = "<!-- ACTIVIDAD:FIN -->"
INICIO_CIFRAS = "<!-- CIFRAS:INICIO -->"
FIN_CIFRAS = "<!-- CIFRAS:FIN -->"

MAX_ENTRADAS = 5
TIEMPO_ESPERA = 20

MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

ACCIONES = {
    "opened": "abierto",
    "closed": "cerrado",
    "reopened": "reabierto",
    "merged": "fusionado",
    "created": "creado",
    "published": "publicado",
}


def consultar(url: str) -> Any:
    """Devuelve el JSON de la URL. Usa GH_TOKEN si está disponible."""
    cabeceras = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "jeironpro-readme-actualizacion",
    }
    token = os.environ.get("GH_TOKEN")
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"

    peticion = urllib.request.Request(url, headers=cabeceras)
    with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA) as respuesta:
        return json.load(respuesta)


def fecha_corta(iso: str) -> str:
    try:
        fecha = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    return f"{fecha.day} {MESES[fecha.month - 1]}"


# --- Actividad reciente ----------------------------------------------------


def describir(evento: dict) -> str | None:
    """Devuelve una descripción breve del evento o None si no aporta nada."""
    tipo = evento.get("type")
    datos = evento.get("payload") or {}

    if tipo == "PushEvent":
        rama = str(datos.get("ref", "")).split("/")[-1] or "main"
        cuantos = len(datos.get("commits") or [])
        if cuantos == 0:
            return f"push en `{rama}`"
        plural = "" if cuantos == 1 else "s"
        return f"{cuantos} commit{plural} en `{rama}`"

    if tipo == "CreateEvent":
        clase = datos.get("ref_type")
        if clase == "repository":
            return "repositorio nuevo"
        if clase == "tag":
            return f"etiqueta `{datos.get('ref', '')}`"
        return f"rama `{datos.get('ref', '')}`"

    if tipo == "ReleaseEvent":
        etiqueta = (datos.get("release") or {}).get("tag_name", "")
        return f"release `{etiqueta}`" if etiqueta else "nueva release"

    if tipo in {"PullRequestEvent", "IssuesEvent"}:
        numero = datos.get("number")
        accion = ACCIONES.get(str(datos.get("action")), datos.get("action"))
        etiqueta = "pull request" if tipo == "PullRequestEvent" else "issue"
        return f"{etiqueta} #{numero} {accion}"

    if tipo == "ForkEvent":
        return "nuevo fork"

    return None


def construir_filas(eventos: list[dict]) -> list[str]:
    vistos: set[tuple[str, str]] = set()
    filas: list[str] = []

    for evento in eventos:
        repositorio = (evento.get("repo") or {}).get("name") or ""
        if not repositorio:
            continue

        descripcion = describir(evento)
        if not descripcion:
            continue

        clave = (repositorio, str(evento.get("type")))
        if clave in vistos:
            continue
        vistos.add(clave)

        nombre = repositorio.split("/")[-1]
        fecha = fecha_corta(evento.get("created_at", ""))
        fila = f"- [{nombre}](https://github.com/{repositorio}) · {descripcion}"
        if fecha:
            fila = f"{fila} · {fecha}"
        filas.append(fila)

        if len(filas) == MAX_ENTRADAS:
            break

    return filas


def completar_con_repositorios(filas: list[str], repositorios: list[dict]) -> list[str]:
    """Rellena los huecos con los repositorios actualizados más recientemente."""
    ya_listados = {nombre for fila in filas for nombre in re.findall(r"github\.com/[^/]+/([^)]+)\)", fila)}

    for repositorio in repositorios:
        if len(filas) >= MAX_ENTRADAS:
            break
        nombre = repositorio.get("name") or ""
        if not nombre or nombre in ya_listados:
            continue
        fecha = fecha_corta(repositorio.get("pushed_at", ""))
        fila = f"- [{nombre}]({repositorio.get('html_url')}) · repositorio actualizado"
        if fecha:
            fila = f"{fila} · {fecha}"
        filas.append(fila)

    return filas


def actualizar_actividad(contenido: str) -> str:
    try:
        eventos = consultar(f"https://api.github.com/users/{USUARIO}/events/public?per_page=100")
    except Exception as error:  # noqa: BLE001 - se prefiere conservar el README
        print(f"aviso: no se pudieron leer los eventos ({error})", file=sys.stderr)
        return contenido

    filas = construir_filas(eventos)
    if len(filas) < MAX_ENTRADAS:
        try:
            repositorios = consultar(
                f"https://api.github.com/users/{USUARIO}/repos?sort=pushed&direction=desc&per_page=10&type=owner"
            )
            filas = completar_con_repositorios(filas, repositorios)
        except Exception as error:  # noqa: BLE001 - la lista de eventos ya es útil
            print(f"aviso: no se pudieron listar repositorios ({error})", file=sys.stderr)

    if not filas:
        filas = ["- Sin actividad pública en los últimos días."]

    bloque = "\n".join([INICIO_ACTIVIDAD, *filas, FIN_ACTIVIDAD])
    actualizado, reemplazos = re.subn(
        re.escape(INICIO_ACTIVIDAD) + r".*?" + re.escape(FIN_ACTIVIDAD),
        lambda _: bloque,
        contenido,
        count=1,
        flags=re.DOTALL,
    )
    if reemplazos == 0:
        print("aviso: faltan los marcadores de actividad", file=sys.stderr)
        return contenido
    return actualizado


# --- Cifras del encabezado -------------------------------------------------


def contar_repositorios() -> int | None:
    try:
        return int(consultar(f"https://api.github.com/users/{USUARIO}")["public_repos"])
    except Exception as error:  # noqa: BLE001
        print(f"aviso: no se pudo contar repositorios ({error})", file=sys.stderr)
        return None


def contar_paquetes() -> int | None:
    """Cuenta los paquetes listados que siguen publicados en PyPI."""
    publicados = 0
    for paquete in PAQUETES_PYPI:
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{paquete}/json", timeout=TIEMPO_ESPERA):
                publicados += 1
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            print(f"aviso: PyPI respondió {error.code} para {paquete}", file=sys.stderr)
            return None
        except Exception as error:  # noqa: BLE001
            print(f"aviso: no se pudo consultar {paquete} en PyPI ({error})", file=sys.stderr)
            return None
    return publicados


def contar_sitios() -> int | None:
    try:
        datos = consultar(CATALOGO_WEBS)
        webs = datos.get("webs") or []
        if webs:
            return len([w for w in webs if str(w.get("estado", "")).lower() == "live"])
        total = datos.get("total")
        return int(total) if total is not None else None
    except Exception as error:  # noqa: BLE001
        print(f"aviso: no se pudo leer el catálogo de webs ({error})", file=sys.stderr)
        return None


def cifra_previa(bloque: str, etiqueta: str) -> int | None:
    encontrada = re.search(r"<strong>(\d+)</strong> " + etiqueta, bloque)
    return int(encontrada.group(1)) if encontrada else None


def actualizar_cifras(contenido: str) -> str:
    patron = re.compile(re.escape(INICIO_CIFRAS) + r"(.*?)" + re.escape(FIN_CIFRAS), re.DOTALL)
    encontrado = patron.search(contenido)
    if not encontrado:
        print("aviso: faltan los marcadores de cifras", file=sys.stderr)
        return contenido

    bloque = encontrado.group(1)
    repositorios = contar_repositorios()
    paquetes = contar_paquetes()
    sitios = contar_sitios()

    valores = (
        repositorios if repositorios is not None else cifra_previa(bloque, "repositorios"),
        paquetes if paquetes is not None else cifra_previa(bloque, "paquetes"),
        sitios if sitios is not None else cifra_previa(bloque, "sitios"),
    )
    if any(valor is None for valor in valores):
        print("aviso: faltan cifras y no hay valor previo; se conserva el bloque", file=sys.stderr)
        return contenido

    nuevo = (
        "\n  <p>"
        f"<strong>{valores[0]}</strong> repositorios públicos &nbsp;·&nbsp; "
        f"<strong>{valores[1]}</strong> paquetes en PyPI &nbsp;·&nbsp; "
        f"<strong>{valores[2]}</strong> sitios desplegados"
        "</p>\n  "
    )
    return contenido[: encontrado.start(1)] + nuevo + contenido[encontrado.end(1) :]


def main() -> int:
    contenido = README.read_text(encoding="utf-8")
    original = contenido

    contenido = actualizar_cifras(contenido)
    contenido = actualizar_actividad(contenido)

    if contenido == original:
        print("sin cambios")
        return 0

    README.write_text(contenido, encoding="utf-8")
    print("README actualizado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
