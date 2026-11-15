from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from image_processor import CancelledError, CompressionConfig, ImageCompressor


@pytest.mark.parametrize('folder', ['../outside', '.', '', 'nested/output'])
def test_destination_must_be_a_single_subdirectory(tmp_path, folder):
    config = CompressionConfig(90, 100, destination_folder_name=folder)
    with pytest.raises(ValueError):
        ImageCompressor(str(tmp_path), config).run()


def test_absolute_destination_is_rejected(tmp_path):
    config = CompressionConfig(90, 100, destination_folder_name=str(tmp_path.parent))
    with pytest.raises(ValueError):
        ImageCompressor(str(tmp_path), config).run()


def test_failed_image_save_preserves_previous_output(tmp_path, monkeypatch):
    Image.new('RGB', (20, 20)).save(tmp_path / 'photo.jpg')
    destination = tmp_path / 'comp_v0'
    destination.mkdir()
    previous = destination / 'photo.jpg'
    previous.write_bytes(b'previous output')

    def fail(image, target, *args, **kwargs):
        if hasattr(target, 'write'):
            target.write(b'incomplete')
        else:
            Path(target).write_bytes(b'incomplete')
        raise OSError('disk full')

    monkeypatch.setattr(Image.Image, 'save', fail)
    result = ImageCompressor(str(tmp_path), CompressionConfig(90, 100)).run()
    assert result.errors == 1
    assert previous.read_bytes() == b'previous output'
    assert list(destination.iterdir()) == [previous]


def test_cancelled_scan_stops_before_walking(tmp_path, monkeypatch):
    import image_processor as processor

    cancel = Event()
    cancel.set()

    def walk(*args, **kwargs):
        pytest.fail('Cancelled run must not walk the directory')

    monkeypatch.setattr(processor.os, 'walk', walk)
    with pytest.raises(CancelledError):
        ImageCompressor(str(tmp_path), CompressionConfig(90, 100), cancel_event=cancel).run()


def test_output_subtree_is_pruned(tmp_path, monkeypatch):
    import image_processor as processor

    destination = tmp_path / 'comp_v0'
    destination.mkdir()

    def walk(*args, **kwargs):
        dirs = ['comp_v0', 'photos']
        yield str(tmp_path), dirs, []
        assert dirs == ['photos']

    monkeypatch.setattr(processor.os, 'walk', walk)
    ImageCompressor(str(tmp_path), CompressionConfig(90, 100)).run()


def test_linked_destination_outside_source_is_rejected(tmp_path):
    source = tmp_path / 'source'
    outside = tmp_path / 'outside'
    source.mkdir()
    outside.mkdir()
    try:
        (source / 'comp_v0').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink privileges unavailable')
    with pytest.raises(ValueError):
        ImageCompressor(str(source), CompressionConfig(90, 100)).run()
    assert not list(outside.iterdir())
