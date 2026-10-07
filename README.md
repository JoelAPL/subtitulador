# Subtitulador

Herramientas para Windows que ponen subtítulos en español a videos que no los tienen:

- **Subtítulos en vivo** (`subtitulos_en_vivo.py`): lee los subtítulos en inglés que aparecen en pantalla (en cualquier reproductor o página web), los traduce al español y los muestra en una barra flotante encima del video. No hace falta descargar nada.
- **Subtitular archivos** (`subtitular.py`): transcribe el audio de un video con Whisper (por defecto en checo, se puede cambiar), lo traduce y genera un `.srt` en español que se abre en VLC.

Todo funciona **sin internet** por defecto (OCR de Windows + Whisper + Argos Translate). Opcionalmente puede usar traductores en línea.

## Instalación

Requisitos: Windows 10/11 y [Python 3.11+](https://www.python.org/downloads/).

```bat
git clone https://github.com/JoelAPL/subtitulador.git
cd subtitulador
instalar.bat
```

`instalar.bat` crea un entorno `venv`, instala los paquetes, descarga los modelos de traducción offline e instala `ffmpeg` y VLC con `winget` si faltan.

## Subtítulos en vivo

1. Abre el video (Chrome, VLC, lo que sea), lo más grande posible.
2. Ejecuta `subtitulos_en_vivo.bat`.
3. Arrastra un rectángulo sobre la franja donde salen los subtítulos en inglés.
4. La traducción aparece en una barra flotante. Pasa el mouse por encima para ver los botones:

| Botón | Tecla | Acción |
|---|---|---|
| ⟲ | `R` | Volver a marcar la zona de subtítulos |
| A− / A+ | `-` / `+` | Tamaño de letra |
| ◐− / ◐+ | rueda del mouse | Fondo más transparente / más oscuro |
| 🌐 | | Cambiar de traductor |
| US·A / GB… | | Variante de inglés (`·A` = detectada automáticamente) |
| ✕ | `Esc` | Salir |
| ◢ (esquina) | | Arrastrar para cambiar el tamaño del cuadro |

La barra se mueve arrastrándola. Posición, tamaño, letra, oscuridad y traductor se recuerdan en `config.json`.

La barra no aparece en las capturas de pantalla, así que puede ponerse encima de los subtítulos originales para taparlos sin que el programa se lea a sí mismo.

### Traductores

| Nombre | Internet | Notas |
|---|---|---|
| `argos` | No | Por defecto y el más rápido (~0.15 s por frase). |
| `mymemory` | Sí | Gratis, límite diario de caracteres. |
| `google` | Sí | Gratis, puede bloquear si se usa mucho. Los traductores en línea añaden de 0.5 a 1 s. |
| `deepl` | Sí | El de mejor calidad. Requiere la variable de entorno `DEEPL_API_KEY` (la clave gratuita termina en `:fx`). |

Si un traductor en línea falla, se usa `argos` automáticamente.

### Variantes de inglés

El programa detecta de qué país es el inglés por las palabras típicas que van saliendo (`mate`, `bloody`, `innit` → Reino Unido; `arvo`, `heaps` → Australia; `aye`, `wee` → Escocia/Irlanda; por defecto EE.UU.) y pasa las expresiones locales a inglés estándar antes de traducir:

| Variante | Ejemplo | Traducción |
|---|---|---|
| Reino Unido | Fancy a cuppa? Brilliant, innit. | ¿Quieres una taza de té? Genial, ¿no? |
| Reino Unido | Your pants are on the floor. | Tu ropa interior está en el suelo. |
| Australia | G'day mate, see you this arvo. | Hola amigo, nos vemos esta tarde. |
| Escocia | Ye dinnae ken what ye want. | No sabes lo que quieres. |
| EE.UU. | Hey buddy, I'm pissed at mom. | Hola amigo, estoy enfadado con mamá. |

Algunas palabras cambian de significado según el país (`pants`, `pissed`, `fanny`, `root`…), por eso solo se cambian cuando se detecta esa variante. Con el botón de variante se puede fijar una a mano.

Todo está en `variantes.json`: se pueden añadir palabras o variantes nuevas (por ejemplo `en-ZA`, `en-IN`) sin tocar código.

### Glosario

`glosario.txt` corrige palabras que el traductor deja en inglés o traduce mal. Una por línea:

```
swap = intercambio
naughty = traviesa
```

Reinicia el programa después de editarlo.

## Subtitular archivos

Arrastra uno o varios videos sobre `subtitular.bat`, o:

```bat
venv\Scripts\python.exe subtitular.py video.mp4 --modelo medium
```

Genera `video.es.srt` y abre el video en VLC con los subtítulos. Modelos: `small` (rápido) o `medium` (más preciso, unas 3 veces más lento). Sin tarjeta gráfica, un video de 30 minutos tarda de 30 a 60 minutos con `small`.

## Cómo funciona

- **OCR**: `Windows.Media.Ocr` (incluido en Windows) vía `winrt`. Antes de leer, la imagen se pasa a blanco y negro aislando el texto claro, que es como suelen venir los subtítulos.
- **Limpieza**: corrige confusiones típicas del OCR (`probabIy` → `probably`, `0` entre letras → `o`) y pasa el texto en MAYÚSCULAS a normal, que el traductor maneja mucho mejor.
- **Captura**: `mss`, cada 0.15 s. Si la imagen del subtítulo no cambió, no se vuelve a leer; la imagen solo se agranda cuando la letra es pequeña (agrandar hace el OCR ~5 veces más lento). Del cambio de subtítulo a la traducción en pantalla pasan unos 0.3 s con `argos`.
- **Variantes**: `variantes.py` puntúa las palabras típicas de cada país en los últimos subtítulos y normaliza el texto con `variantes.json`.
- **Transcripción**: `faster-whisper` en CPU (int8); el audio se extrae con `ffmpeg`.

## Licencia

[MIT](LICENSE)
