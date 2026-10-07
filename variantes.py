"""Detecta la variante de inglés (EE.UU., Reino Unido, Australia, Irlanda/Escocia...) y
pasa las expresiones locales a inglés estándar antes de traducir.

Los datos están en variantes.json: se pueden añadir variantes o palabras sin tocar código.
"""
import json
import re
from pathlib import Path

DATOS = Path(__file__).with_name("variantes.json")
AUTO = "auto"
PREDETERMINADA = "en-US"


def _patron(frases):
    """Regex que busca cualquiera de las frases como palabra completa (las largas primero)."""
    frases = sorted(frases, key=len, reverse=True)
    if not frases:
        return None
    return re.compile(r"(?<![\w'])(" + "|".join(map(re.escape, frases)) + r")(?![\w'])",
                      re.IGNORECASE)


def _reemplazar(texto, patron, cambios):
    if not patron:
        return texto

    def cambiar(m):
        original = m.group(0)
        nuevo = cambios[original.lower()]
        return nuevo[:1].upper() + nuevo[1:] if original[:1].isupper() else nuevo
    return patron.sub(cambiar, texto)


class Variantes:
    def __init__(self, ruta=DATOS):
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        self.comun = {k.lower(): v for k, v in datos.get("comun", {}).items()}
        self.p_comun = _patron(self.comun)
        self.info = {}
        for clave, v in datos.get("variantes", {}).items():
            cambios = {k.lower(): c for k, c in v.get("cambios", {}).items()}
            self.info[clave] = {
                "nombre": v.get("nombre", clave),
                "marcadores": _patron(v.get("marcadores", [])),
                "cambios": cambios,
                "p_cambios": _patron(cambios),
            }
        self.puntos = {k: 0.0 for k in self.info}
        self.elegida = AUTO  # o una clave fija de variantes.json

    def opciones(self):
        return [AUTO] + list(self.info)

    def nombre(self, clave):
        return "Automático" if clave == AUTO else self.info[clave]["nombre"]

    def detectada(self):
        """Variante con más indicios en los últimos subtítulos (EE.UU. si no hay pistas)."""
        mejor = max(self.puntos, key=self.puntos.get, default=PREDETERMINADA)
        return mejor if self.puntos.get(mejor, 0) >= 1.5 else PREDETERMINADA

    def actual(self):
        return self.detectada() if self.elegida == AUTO else self.elegida

    def observar(self, texto):
        """Suma indicios de cada variante; los antiguos van perdiendo peso."""
        for clave, v in self.info.items():
            n = len(v["marcadores"].findall(texto)) if v["marcadores"] else 0
            self.puntos[clave] = self.puntos[clave] * 0.95 + n

    def normalizar(self, texto):
        """Inglés local -> inglés estándar que el traductor entiende."""
        self.observar(texto)
        texto = _reemplazar(texto, self.p_comun, self.comun)
        v = self.info.get(self.actual())
        if v:
            texto = _reemplazar(texto, v["p_cambios"], v["cambios"])
        return texto
