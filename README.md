# Compresor de Imágenes JPEG

Aplicación de escritorio (Tkinter) que comprime y redimensiona en lote
todas las imágenes `.jpg` / `.jpeg` de una carpeta, conservando la
estructura de subcarpetas dentro de un directorio de salida.

## Características

- Compresión JPEG con calidad configurable (1–100).
- Redimensionado opcional al ancho/alto máximo indicado, respetando
  la relación de aspecto.
- Corrección automática de orientación según metadatos EXIF.
- Procesamiento en un hilo aparte: la interfaz no se congela y el
  proceso se puede cancelar en cualquier momento.
- Protección contra "bombas de descompresión" y archivos de imagen
  corruptos o disfrazados.
- Registro (log) de la actividad en `compresor_app.log`, con rotación
  automática para que no crezca sin límite.

## Requisitos

- Python 3.10 o superior (requerido por Pillow 12).
- Tkinter (incluido en la instalación estándar de Python en Windows y
  macOS; en Linux puede requerir instalar el paquete `python3-tk` con
  el gestor de paquetes de tu distribución).

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Para desarrollo (incluye `pytest` y `ruff`):

```bash
pip install -r requirements-dev.txt
```

## Uso

```bash
python main.py
```

1. Selecciona la carpeta de origen con las imágenes.
2. Ajusta la calidad y el tamaño máximo.
3. Pulsa "Comprimir Imágenes". El resultado se guarda en una
   subcarpeta `comp_v0/` dentro de la carpeta de origen, manteniendo
   la misma estructura de subdirectorios.

## Estructura del proyecto

```
Compressor_v2/
├── main.py                 # Punto de entrada
├── gui.py                  # Interfaz Tkinter
├── image_processor.py      # Lógica de compresión (sin dependencias de UI)
├── tests/
│   └── test_image_processor.py
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── LICENSE
```

## Seguridad

Esta aplicación es **100% local**: no levanta un servidor, no expone
endpoints HTTP, no se conecta a ninguna base de datos y no realiza
peticiones de red. Tampoco maneja credenciales ni variables de entorno: no
hay secretos que extraer del código porque no existen.

Lo que sí es relevante para un programa que procesa carpetas locales
potencialmente con contenido inesperado, y que ya está cubierto en el
código:

- **Validación de la carpeta de origen**: se rechaza si no existe o
  no es un directorio.
- **Límite de tamaño por archivo** (200 MB) y **límite de
  megapíxeles** (`Image.MAX_IMAGE_PIXELS`) para mitigar "bombas de
  descompresión".
- **Enlaces simbólicos no seguidos**: si una carpeta contiene un
  symlink a un archivo fuera de la carpeta de origen, se omite en
  vez de procesarlo, para no leer ni copiar contenido fuera de lo
  que el usuario seleccionó explícitamente.
- **Rutas de destino verificadas**: cada archivo de salida se
  comprueba para que quede dentro de la carpeta de destino antes de
  escribirse (protección contra path traversal).
- **Escritura mediante archivo temporal**: una imagen solo reemplaza el
  resultado anterior después de guardarse por completo. Un error durante
  el guardado conserva la salida previa. Las ejecuciones posteriores
  reemplazan las imágenes de salida que tengan el mismo nombre.
- **Búsqueda cancelable**: se comprueba la cancelación al recorrer carpetas
  y se excluye el árbol de salida antes de descender a él.
- **Manejo explícito de imágenes corruptas o falsificadas** (un
  archivo `.jpg` que en realidad no es una imagen válida se reporta
  como error y se omite, no interrumpe el resto del lote).

Recomendación de mantenimiento: mantén `Pillow` actualizado (ver
`requirements.txt`), ya que es la dependencia que interpreta los
archivos de imagen y donde aparecen ocasionalmente parches de
seguridad.

Si en el futuro esta app llega a incorporar un backend, una base de
datos o llamadas a APIs externas, esos serían el momento adecuado
para añadir CORS, sanitización de inputs hacia la base de datos,
rate limiting y una CSP — vale la pena revisarlo de nuevo en ese
punto.

## Tests

```bash
pytest -v
```

La suite cubre validación de configuración, rechazo de carpetas
inexistentes, protección de rutas de destino, omisión de enlaces
simbólicos externos, archivos falsificados/corruptos, límite de
tamaño de archivo y cancelación del proceso.

## Licencia

MIT — ver [`LICENSE`](LICENSE).
