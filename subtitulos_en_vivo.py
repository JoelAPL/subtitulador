"""Lee subtítulos en inglés de la pantalla y muestra la traducción al español encima.

1. Al abrir, arrastra con el mouse un rectángulo sobre la franja donde salen los subtítulos.
2. Aparece una barra flotante con la traducción. Se puede arrastrar para moverla.
3. Al pasar el mouse por la barra salen los botones: ⟲ marcar zona, A−/A+ letra,
   ◐−/◐+ oscuridad del fondo, ✕ salir, y ◢ (esquina) para cambiar el tamaño.
   Teclas: R = marcar zona, + / - = letra, rueda del mouse = oscuridad, Esc = salir.
   Tamaño, posición, letra y oscuridad se recuerdan para la próxima vez.
"""
import asyncio
import ctypes
import difflib
import json
import os
import queue
import re
import threading
import tkinter as tk
from pathlib import Path

import argostranslate.translate as argos
import mss
from PIL import Image, ImageChops
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

from variantes import AUTO, Variantes

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # coordenadas reales en pantallas con zoom

INTERVALO = 0.15  # segundos entre lecturas (si la imagen no cambió, no se lee de nuevo)
GLOSARIO = Path(__file__).with_name("glosario.txt")
CONFIG = Path(__file__).with_name("config.json")
WDA_EXCLUDEFROMCAPTURE = 0x11


def cargar_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_config(cfg):
    try:
        CONFIG.write_text(json.dumps(cfg), encoding="utf-8")
    except OSError:
        pass


def cargar_glosario():
    """Palabras que el traductor deja en inglés -> su traducción (editable en glosario.txt)."""
    glosario = {}
    try:
        with GLOSARIO.open(encoding="utf-8") as f:
            for linea in f:
                if "=" in linea and not linea.lstrip().startswith("#"):
                    en, es = linea.split("=", 1)
                    glosario[en.strip().lower()] = es.strip()
    except OSError:
        pass
    return glosario


GLOSARIO_PALABRAS = cargar_glosario()


def limpiar(texto):
    """Corrige confusiones típicas del OCR y quita las MAYÚSCULAS, que confunden al traductor."""
    texto = texto.replace("|", "I").replace("’", "'")
    # 'I' mayúscula después de una minúscula es en realidad una 'l' (probabIy, heIlo)
    texto = re.sub(r"(?<=[a-z])I", "l", texto)
    texto = re.sub(r"(?<=[a-zA-Z])0(?=[a-zA-Z])", "o", texto)  # 0 entre letras -> o
    letras = [c for c in texto if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.6:
        texto = re.sub(r"\bi\b", "I", texto.lower().capitalize())
    return texto


def aplicar_glosario(es):
    """Reemplaza palabras que quedaron sin traducir usando el glosario."""
    def cambiar(m):
        palabra = m.group(0)
        nueva = GLOSARIO_PALABRAS.get(palabra.lower())
        if not nueva:
            return palabra
        return nueva.capitalize() if palabra[0].isupper() else nueva
    return re.sub(r"[A-Za-z']+", cambiar, es)


def _deepl(texto):
    clave = os.environ.get("DEEPL_API_KEY")
    if not clave:
        return None
    from deep_translator import DeeplTranslator
    return DeeplTranslator(api_key=clave, source="en", target="es",
                           use_free_api=clave.endswith(":fx")).translate(texto)


def _google(texto):
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="en", target="es").translate(texto)


def _mymemory(texto):
    from deep_translator import MyMemoryTranslator
    return MyMemoryTranslator(source="en-US", target="es-ES").translate(texto)


# nombre -> función. "argos" funciona sin internet; los demás caen a argos si fallan.
TRADUCTORES = {
    "argos": lambda t: argos.translate(t, "en", "es"),
    "mymemory": _mymemory,
    "google": _google,
    "deepl": _deepl,
}


def a_softwarebitmap(img):
    img = img.convert("RGBA")
    w = DataWriter()
    w.write_bytes(img.tobytes("raw", "BGRA"))
    return SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.BGRA8, img.width, img.height)


def preparar(img):
    """Escala a gris, aísla el texto claro (subtítulos blancos) y agranda solo si es pequeño."""
    g = img.convert("L")
    if g.height < 45:  # agrandar cuesta ~5x más OCR; solo vale la pena con letra pequeña
        g = g.resize((g.width * 2, g.height * 2), Image.BILINEAR)
    # texto blanco -> negro sobre blanco, que es lo que mejor lee el OCR
    return g.point(lambda p: 0 if p > 190 else 255)


class Lector(threading.Thread):
    def __init__(self, salida):
        super().__init__(daemon=True)
        self.salida = salida
        self.zona = None
        self.activo = True
        self.motor = OcrEngine.try_create_from_language(Language("en-US"))
        self.cache = {}
        self.motor_traduccion = "argos"
        self.variantes = Variantes()
        argos.translate("hello", "en", "es")  # precarga: la primera traducción tarda ~5 s

    def traducir(self, texto):
        texto = self.variantes.normalizar(limpiar(texto))
        clave = (self.motor_traduccion, texto)
        if clave not in self.cache:
            try:
                es = TRADUCTORES[self.motor_traduccion](texto)
            except Exception:  # sin internet, límite diario, etc. -> offline
                es = None
            self.cache[clave] = aplicar_glosario(es or argos.translate(texto, "en", "es"))
        return self.cache[clave]

    async def ocr(self, img):
        res = await self.motor.recognize_async(a_softwarebitmap(img))
        return " ".join(l.text for l in res.lines).strip()

    def run(self):
        asyncio.run(self.bucle())

    async def bucle(self):
        anterior = ""
        huella_anterior = None
        with mss.MSS() as sct:
            while self.activo:
                if self.zona:
                    x, y, w, h = self.zona
                    shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    lista = preparar(img)
                    # huella: miniatura del texto aislado; si no cambió, el subtítulo es el mismo
                    huella = lista.resize((80, max(4, 80 * lista.height // lista.width)))
                    if huella_anterior is not None and huella.size == huella_anterior.size and                             ImageChops.difference(huella, huella_anterior).getbbox() is None:
                        await asyncio.sleep(INTERVALO)
                        continue
                    huella_anterior = huella
                    texto = await self.ocr(lista)
                    if not texto:
                        texto = await self.ocr(img)  # por si el subtítulo no es blanco
                    parecido = difflib.SequenceMatcher(None, texto, anterior).ratio()
                    if not texto:
                        if anterior:
                            self.salida.put("")
                        anterior = ""
                    elif parecido < 0.85 and len(texto) > 1:
                        anterior = texto
                        self.salida.put(self.traducir(texto))
                await asyncio.sleep(INTERVALO)


class SelectorZona(tk.Toplevel):
    """Pantalla semitransparente para marcar la franja de subtítulos."""

    def __init__(self, raiz, al_elegir, al_cancelar):
        super().__init__(raiz)
        self.al_elegir = al_elegir
        self.al_cancelar = al_cancelar
        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.3)
        self.attributes("-topmost", True)
        self.lienzo = tk.Canvas(self, cursor="cross", bg="black", highlightthickness=0)
        self.lienzo.pack(fill="both", expand=True)
        self.lienzo.create_text(
            self.winfo_screenwidth() // 2, 60, fill="white", font=("Segoe UI", 22, "bold"),
            text="Arrastra un rectángulo sobre la zona de los subtítulos en inglés  (Esc = cancelar)")
        self.lienzo.bind("<ButtonPress-1>", self.inicio)
        self.lienzo.bind("<B1-Motion>", self.mover)
        self.lienzo.bind("<ButtonRelease-1>", self.fin)
        self.bind("<Escape>", lambda e: (self.destroy(), self.al_cancelar()))
        self.rect = None
        self.focus_force()

    def inicio(self, e):
        self.x0, self.y0 = e.x_root, e.y_root
        self.rect = self.lienzo.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)

    def mover(self, e):
        self.lienzo.coords(self.rect, self.x0 - self.winfo_rootx(), self.y0 - self.winfo_rooty(),
                           e.x, e.y)

    def fin(self, e):
        x, y = min(self.x0, e.x_root), min(self.y0, e.y_root)
        w, h = abs(e.x_root - self.x0), abs(e.y_root - self.y0)
        self.destroy()
        if w > 20 and h > 10:
            self.al_elegir((x, y, w, h))
        else:
            self.al_cancelar()


class Barra:
    FONDO = "black"
    BOTON = {"bg": "#333333", "fg": "white", "font": ("Segoe UI", 11, "bold"),
             "padx": 7, "pady": 1, "cursor": "hand2"}

    def __init__(self):
        cfg = cargar_config()
        self.tam = cfg.get("letra", 26)
        self.alpha = cfg.get("opacidad", 0.85)
        self.geom_guardada = cfg.get("geometria")

        self.raiz = tk.Tk()
        self.raiz.overrideredirect(True)
        self.raiz.attributes("-topmost", True)
        self.raiz.configure(bg=self.FONDO)
        self.raiz.attributes("-alpha", self.alpha)
        self.texto = tk.Label(self.raiz, text="Marca la zona de subtítulos...", fg="#FFE14D",
                              bg=self.FONDO, font=("Segoe UI", self.tam, "bold"),
                              wraplength=1200, justify="center", padx=16, pady=8)
        self.texto.pack(fill="both", expand=True)
        self.raiz.bind("<ButtonPress-1>", self.agarrar)
        self.raiz.bind("<B1-Motion>", self.arrastrar)
        self.raiz.bind("<Configure>", self.ajustar_ancho)
        self.raiz.bind("<Escape>", lambda e: self.salir())
        self.raiz.bind("r", lambda e: self.marcar())
        self.raiz.bind("<plus>", lambda e: self.letra(2))
        self.raiz.bind("<minus>", lambda e: self.letra(-2))
        self.raiz.bind("<MouseWheel>", lambda e: self.opacidad(0.05 if e.delta > 0 else -0.05))

        # botones: aparecen al pasar el mouse por encima de la barra
        self.botones = []  # (widget, opciones de place)
        self.ayuda = tk.Label(self.raiz, bg="#333333", fg="white", font=("Segoe UI", 9))
        izq = [("⟲", self.marcar, "Volver a marcar la zona (R)"),
               ("A−", lambda: self.letra(-2), "Letra más pequeña (-)"),
               ("A+", lambda: self.letra(2), "Letra más grande (+)"),
               ("◐−", lambda: self.opacidad(-0.1), "Fondo más transparente"),
               ("◐+", lambda: self.opacidad(0.1), "Fondo más oscuro"),
               ("🌐", self.cambiar_traductor, "Cambiar traductor")]
        x = 4
        for txt, accion, ayuda in izq:
            b = self.boton(txt, accion, ayuda, {"x": x, "y": 4})
            x += b.winfo_reqwidth() + 4
        self.btn_variante = self.boton("EN·A", self.cambiar_variante,
                                       "Variante de inglés (A = automática)", {"x": x, "y": 4})
        self.boton("✕", self.salir, "Salir (Esc)", {"relx": 1.0, "x": -4, "y": 4, "anchor": "ne"},
                   bg="#B3261E")
        # esquina para cambiar el tamaño del cuadro
        grip = tk.Label(self.raiz, text="◢", fg="#AAAAAA", bg=self.FONDO,
                        font=("Segoe UI", 14), cursor="size_nw_se")
        grip.bind("<ButtonPress-1>", self.agarrar_esquina)
        grip.bind("<B1-Motion>", self.redimensionar)
        self.botones.append((grip, {"relx": 1.0, "rely": 1.0, "anchor": "se"}))
        self.raiz.bind("<Enter>", lambda e: self.mostrar_botones())
        self.raiz.bind("<Leave>", self.al_salir_mouse)

        self.raiz.update_idletasks()
        # que la barra no salga en las capturas, así no se lee a sí misma
        hwnd = ctypes.windll.user32.GetParent(self.raiz.winfo_id())
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)

        self.cola = queue.Queue()
        self.lector = Lector(self.cola)
        if cfg.get("variante") in self.lector.variantes.opciones():
            self.lector.variantes.elegida = cfg["variante"]
        if cfg.get("traductor") in TRADUCTORES:
            self.lector.motor_traduccion = cfg["traductor"]
        self.lector.start()
        self.raiz.after(300, self.marcar)
        self.raiz.after(100, self.revisar)

    # --- botones -------------------------------------------------------
    def boton(self, txt, accion, ayuda, lugar, **estilo):
        b = tk.Label(self.raiz, text=txt, **{**self.BOTON, **estilo})
        b.bind("<ButtonPress-1>", lambda e: (accion(), "break")[1])
        b.bind("<Enter>", lambda e: (self.ayuda.configure(text=ayuda),
                                     self.ayuda.place(x=4, rely=1.0, y=-4, anchor="sw")))
        b.bind("<Leave>", lambda e: self.ayuda.place_forget())
        self.botones.append((b, lugar))
        return b

    def mostrar_botones(self):
        for b, lugar in self.botones:
            b.place(**lugar)
            b.lift()

    def ocultar_botones(self):
        for b, _ in self.botones:
            b.place_forget()
        self.ayuda.place_forget()

    def al_salir_mouse(self, e):
        x, y = self.raiz.winfo_pointerxy()
        rx, ry = self.raiz.winfo_rootx(), self.raiz.winfo_rooty()
        if not (rx <= x < rx + self.raiz.winfo_width() and ry <= y < ry + self.raiz.winfo_height()):
            self.ocultar_botones()

    # --- mover / tamaño / aspecto ---------------------------------------
    def agarrar(self, e):
        self.dx, self.dy = e.x_root - self.raiz.winfo_x(), e.y_root - self.raiz.winfo_y()

    def arrastrar(self, e):
        self.raiz.geometry(f"+{e.x_root - self.dx}+{e.y_root - self.dy}")

    def agarrar_esquina(self, e):
        self.base = (e.x_root, e.y_root, self.raiz.winfo_width(), self.raiz.winfo_height())
        return "break"

    def redimensionar(self, e):
        x0, y0, w0, h0 = self.base
        w, h = max(250, w0 + e.x_root - x0), max(50, h0 + e.y_root - y0)
        self.raiz.geometry(f"{w}x{h}")
        return "break"

    def ajustar_ancho(self, e):
        if e.widget is self.raiz:
            self.texto.configure(wraplength=max(200, e.width - 40))

    def letra(self, d):
        self.tam = max(10, min(72, self.tam + d))
        self.texto.configure(font=("Segoe UI", self.tam, "bold"))

    def opacidad(self, d):
        self.alpha = round(max(0.2, min(1.0, self.alpha + d)), 2)
        self.raiz.attributes("-alpha", self.alpha)

    def cambiar_traductor(self):
        nombres = list(TRADUCTORES)
        actual = nombres.index(self.lector.motor_traduccion)
        nuevo = nombres[(actual + 1) % len(nombres)]
        if nuevo == "deepl" and not os.environ.get("DEEPL_API_KEY"):
            nuevo = nombres[0]  # DeepL solo si hay clave configurada
        self.lector.motor_traduccion = nuevo
        self.texto.configure(text=f"Traductor: {nuevo}")

    def cambiar_variante(self):
        v = self.lector.variantes
        ops = v.opciones()
        v.elegida = ops[(ops.index(v.elegida) + 1) % len(ops)]
        self.texto.configure(text=f"Inglés: {v.nombre(v.elegida)}")
        self.rotular_variante()

    def rotular_variante(self):
        v = self.lector.variantes
        codigo = v.actual().split("-", 1)[1].split("-")[0]  # en-GB -> GB
        self.btn_variante.configure(text=f"{codigo}·A" if v.elegida == AUTO else codigo)

    # --- zona y textos -------------------------------------------------
    def marcar(self):
        self.ocultar_botones()
        self.raiz.withdraw()
        SelectorZona(self.raiz, self.zona_elegida, self.cancelado)

    def cancelado(self):
        if self.lector.zona:
            self.raiz.deiconify()
        else:
            self.salir()

    def zona_elegida(self, zona):
        x, y, w, h = zona
        self.lector.zona = zona
        self.texto.configure(text="(esperando subtítulos...)")
        self.raiz.deiconify()
        self.raiz.update_idletasks()
        if self.geom_guardada:  # primera vez: donde la dejaste la última vez
            self.raiz.geometry(self.geom_guardada)
            self.geom_guardada = None
        else:  # por defecto justo encima de la zona marcada
            alto = max(self.raiz.winfo_reqheight(), h, 90)
            self.raiz.geometry(f"{w}x{alto}+{x}+{max(0, y - alto - 5)}")
        self.raiz.focus_force()

    def revisar(self):
        try:
            while True:
                t = self.cola.get_nowait()
                self.texto.configure(text=t or " ")
        except queue.Empty:
            pass
        self.rotular_variante()
        self.raiz.after(100, self.revisar)

    def salir(self):
        self.lector.activo = False
        if self.raiz.state() != "withdrawn":
            geom = self.raiz.geometry()
        else:
            geom = cargar_config().get("geometria")
        guardar_config({"letra": self.tam, "opacidad": self.alpha, "geometria": geom,
                       "traductor": self.lector.motor_traduccion,
                       "variante": self.lector.variantes.elegida})
        self.raiz.destroy()


if __name__ == "__main__":
    Barra().raiz.mainloop()
