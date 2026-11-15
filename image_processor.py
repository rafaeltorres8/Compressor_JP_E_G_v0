from __future__ import annotations
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 300_000_000  # ~300 megapíxeles
MAX_SOURCE_FILE_BYTES = 200 * 1024 * 1024  # 200 MB
VALID_EXTENSIONS = (".jpg", ".jpeg")
logger = logging.getLogger("image_compressor")
@dataclass(frozen=True)
class CompressionConfig:
    """Parámetros de compresión validados antes de ejecutar el proceso."""

    quality: int
    max_size: int
    destination_folder_name: str = "comp_v0"

    def validate(self) -> None:
        if not (1 <= self.quality <= 100):
            raise ValueError("La calidad debe ser un entero entre 1 y 100.")
        if self.max_size <= 0:
            raise ValueError("El ancho/alto máximo debe ser un entero positivo.")
        name = self.destination_folder_name
        if (not isinstance(name, str) or name in ("", ".", "..")
                or Path(name).name != name or "/" in name or "\\" in name
                or Path(name).is_absolute()):
            raise ValueError("El destino debe ser el nombre de una subcarpeta del origen.")

@dataclass(frozen=True)
class ProcessResult:
    processed: int
    skipped: int
    errors: int

class CancelledError(Exception):
    pass

class ImageCompressor:
    
    def __init__(
        self,
        source_folder: str,
        config: CompressionConfig,
        on_log: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.source_folder = Path(source_folder).resolve()
        self.config = config
        self.on_log = on_log or (lambda msg: None)
        self.on_progress = on_progress or (lambda done, total: None)
        self.cancel_event = cancel_event or Event()

        if not self.source_folder.is_dir():
            raise ValueError(
                f"La carpeta de origen no existe o no es un directorio: {self.source_folder}"
            )

        self.destination_path = self.source_folder / self.config.destination_folder_name

    def _log(self, message: str) -> None:
        logger.info(message)
        self.on_log(message)

    def _is_within_destination(self, directory: Path) -> bool:
        try:
            directory.relative_to(self.destination_path)
            return True
        except ValueError:
            return directory == self.destination_path

    def _iter_source_images(self) -> list[Path]:
        images: list[Path] = []
        self._check_cancelled()
        # followlinks=False (por defecto) evita que os.walk entre en
        # subcarpetas simbólicas que apunten fuera de source_folder.
        for current_root, _dirs, files in os.walk(self.source_folder):
            self._check_cancelled()
            current_path = Path(current_root)
            # Prune before os.walk descends, rather than visiting every output directory.
            _dirs[:] = [name for name in _dirs
                        if not self._is_within_destination(current_path / name)
                        and not (current_path / name).is_symlink()
                        and not getattr(current_path / name, "is_junction", lambda: False)()]
            if self._is_within_destination(current_path):
                continue
            for filename in files:
                self._check_cancelled()
                if not filename.lower().endswith(VALID_EXTENSIONS):
                    continue
                candidate = current_path / filename
                if candidate.is_symlink():
                    # Un symlink podría apuntar a un archivo fuera de
                    # source_folder; lo omitimos para no procesar ni
                    # copiar contenido de rutas no seleccionadas por
                    # el usuario.
                    self._log(f"OMITIDO (enlace simbólico no seguido): {candidate.name}")
                    continue
                images.append(candidate)
        return images

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise CancelledError()

    def _safe_target_path(self, source_image_path: Path) -> Path:
        relative = source_image_path.parent.relative_to(self.source_folder)
        target_dir = (self.destination_path / relative).resolve()
        destination_resolved = self.destination_path.resolve()
        if target_dir != destination_resolved and destination_resolved not in target_dir.parents:
            raise ValueError(f"Ruta de destino fuera de lo esperado: {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source_image_path.name
        if target.is_symlink():
            raise ValueError("El archivo de destino no puede ser un enlace simbólico.")
        return target

    def _compress_one(self, source_image_path: Path) -> None:
        file_size = source_image_path.stat().st_size
        if file_size > MAX_SOURCE_FILE_BYTES:
            raise ValueError(
                f"Archivo demasiado grande ({file_size / 1024 / 1024:.1f} MB), "
                f"se omite por seguridad/rendimiento."
            )

        destination_image_path = self._safe_target_path(source_image_path)

        with Image.open(source_image_path) as img:
            # Corrige la orientación según EXIF (evita fotos "giradas")
            img = ImageOps.exif_transpose(img)

            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            width, height = img.size
            new_size = (width, height)
            if width > self.config.max_size or height > self.config.max_size:
                ratio = self.config.max_size / max(width, height)
                new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))

            if new_size != (width, height):
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                self._log(f" - Redimensionada a: {new_size[0]}x{new_size[1]}")

            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=destination_image_path.parent, suffix=".tmp", delete=False
                ) as output:
                    temporary_path = Path(output.name)
                    img.save(output, "JPEG", quality=self.config.quality, optimize=True)
                os.replace(temporary_path, destination_image_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    def run(self) -> ProcessResult:
        self.config.validate()
        self._check_cancelled()
        if self.destination_path.resolve().parent != self.source_folder:
            raise ValueError("La carpeta de destino debe permanecer dentro del origen.")
        self.destination_path.mkdir(parents=True, exist_ok=True)
        self._log(f"Carpeta de destino: {self.destination_path}")

        images = self._iter_source_images()
        total = len(images)
        self._log(f"Se encontraron {total} imágenes candidatas.")

        processed = skipped = errors = 0

        for index, source_image_path in enumerate(images, start=1):
            if self.cancel_event.is_set():
                self._log("Proceso cancelado por el usuario.")
                raise CancelledError()

            self._log(f"Procesando ({index}/{total}): {source_image_path.name}")
            try:
                self._compress_one(source_image_path)
                processed += 1
            except Image.DecompressionBombError:
                errors += 1
                self._log(
                    f"OMITIDA (posible bomba de descompresión): {source_image_path.name}"
                )
            except UnidentifiedImageError:
                errors += 1
                self._log(f"OMITIDA (archivo no es una imagen válida): {source_image_path.name}")
            except (OSError, ValueError) as exc:
                errors += 1
                self._log(f"ERROR en {source_image_path.name}: {exc}")
            finally:
                self.on_progress(index, total)

        self._log(f"Completado. Procesadas={processed}, Errores={errors}")
        return ProcessResult(processed=processed, skipped=skipped, errors=errors)
