from __future__ import annotations
import os
import sys
from pathlib import Path
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import image_processor as ip
from image_processor import CompressionConfig, ImageCompressor

# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #

def _make_jpeg(path: Path, size: tuple[int, int] = (800, 600), color=(255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


# --------------------------------------------------------------------- #
# CompressionConfig.validate
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("quality", [0, -1, 101, 1000])
def test_invalid_quality_rejected(quality: int) -> None:
    with pytest.raises(ValueError):
        CompressionConfig(quality=quality, max_size=1200).validate()


@pytest.mark.parametrize("max_size", [0, -1, -100])
def test_invalid_max_size_rejected(max_size: int) -> None:
    with pytest.raises(ValueError):
        CompressionConfig(quality=90, max_size=max_size).validate()


def test_valid_config_passes() -> None:
    CompressionConfig(quality=90, max_size=1200).validate()  # no debe lanzar


# --------------------------------------------------------------------- #
# Carpeta de origen
# --------------------------------------------------------------------- #

def test_missing_source_folder_raises(tmp_path: Path) -> None:
    missing = tmp_path / "no_existe"
    with pytest.raises(ValueError):
        ImageCompressor(str(missing), CompressionConfig(quality=90, max_size=1200))


def test_source_folder_that_is_a_file_raises(tmp_path: Path) -> None:
    a_file = tmp_path / "no_es_carpeta.txt"
    a_file.write_text("hola")
    with pytest.raises(ValueError):
        ImageCompressor(str(a_file), CompressionConfig(quality=90, max_size=1200))


# --------------------------------------------------------------------- #
# Path traversal / destino seguro
# --------------------------------------------------------------------- #

def test_safe_target_path_stays_within_destination(tmp_path: Path) -> None:
    source = tmp_path / "origen"
    nested = source / "sub" / "carpeta"
    _make_jpeg(nested / "foto.jpg")

    compressor = ImageCompressor(str(source), CompressionConfig(quality=90, max_size=1200))
    img_path = nested / "foto.jpg"
    target = compressor._safe_target_path(img_path)

    assert compressor.destination_path.resolve() in target.resolve().parents
    assert target.name == "foto.jpg"


def test_destination_folder_itself_is_skipped_when_walking(tmp_path: Path) -> None:
    source = tmp_path / "origen"
    _make_jpeg(source / "foto.jpg")

    config = CompressionConfig(quality=90, max_size=1200)
    compressor = ImageCompressor(str(source), config)
    result = compressor.run()
    assert result.processed == 1

    # Una segunda pasada no debe reprocesar las imágenes ya generadas
    # dentro de la carpeta de destino (comp_v0).
    result2 = compressor.run()
    assert result2.processed == 1


# --------------------------------------------------------------------- #
# Enlaces simbólicos
# --------------------------------------------------------------------- #

@pytest.mark.skipif(os.name == "nt", reason="symlinks requieren privilegios especiales en Windows")
def test_symlinked_image_outside_source_is_skipped(tmp_path: Path) -> None:
    outside = tmp_path / "fuera"
    _make_jpeg(outside / "secreta.jpg")

    source = tmp_path / "origen"
    source.mkdir()
    link = source / "enlace.jpg"
    link.symlink_to(outside / "secreta.jpg")

    compressor = ImageCompressor(str(source), CompressionConfig(quality=90, max_size=1200))
    result = compressor.run()

    assert result.processed == 0
    assert not (compressor.destination_path / "enlace.jpg").exists()


# --------------------------------------------------------------------- #
# Compresión end-to-end
# --------------------------------------------------------------------- #

def test_compression_resizes_and_saves(tmp_path: Path) -> None:
    source = tmp_path / "origen"
    _make_jpeg(source / "grande.jpg", size=(2000, 1000))

    config = CompressionConfig(quality=80, max_size=500)
    compressor = ImageCompressor(str(source), config)
    result = compressor.run()

    assert result.processed == 1
    assert result.errors == 0

    output = compressor.destination_path / "grande.jpg"
    assert output.exists()
    with Image.open(output) as img:
        assert max(img.size) <= 500


def test_non_image_file_is_ignored(tmp_path: Path) -> None:
    source = tmp_path / "origen"
    source.mkdir()
    (source / "notas.txt").write_text("esto no es una imagen")

    compressor = ImageCompressor(str(source), CompressionConfig(quality=90, max_size=1200))
    result = compressor.run()
    assert result.processed == 0
    assert result.errors == 0


def test_file_disguised_as_jpg_is_reported_as_error(tmp_path: Path) -> None:
    source = tmp_path / "origen"
    source.mkdir()
    fake = source / "falsa.jpg"
    fake.write_bytes(b"esto no es un jpeg real")

    compressor = ImageCompressor(str(source), CompressionConfig(quality=90, max_size=1200))
    result = compressor.run()
    assert result.processed == 0
    assert result.errors == 1


def test_oversized_file_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "origen"
    _make_jpeg(source / "foto.jpg")

    # Se reduce el límite en vez de crear un archivo real de 200 MB.
    monkeypatch.setattr(ip, "MAX_SOURCE_FILE_BYTES", 10)

    compressor = ImageCompressor(str(source), CompressionConfig(quality=90, max_size=1200))
    result = compressor.run()
    assert result.processed == 0
    assert result.errors == 1


def test_cancel_event_stops_processing(tmp_path: Path) -> None:
    import threading

    source = tmp_path / "origen"
    for i in range(3):
        _make_jpeg(source / f"foto{i}.jpg")

    cancel_event = threading.Event()
    cancel_event.set()  # cancelado antes de empezar

    compressor = ImageCompressor(
        str(source), CompressionConfig(quality=90, max_size=1200), cancel_event=cancel_event
    )
    with pytest.raises(ip.CancelledError):
        compressor.run()
