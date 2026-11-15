import queue
from types import SimpleNamespace
from unittest.mock import MagicMock

from gui import ImageCompressorApp, _Event


def test_poll_handles_event_queued_just_as_worker_finishes():
    events = queue.Queue()
    root = MagicMock()

    def finishing():
        events.put(_Event('done'))
        return False

    view = SimpleNamespace(
        _event_queue=events, root=root,
        _worker_thread=SimpleNamespace(is_alive=finishing),
        _handle_event=MagicMock(), _poll_queue=MagicMock(),
    )
    ImageCompressorApp._poll_queue(view)
    root.after.assert_called_once_with(100, view._poll_queue)


def test_poll_limits_each_batch_to_keep_ui_responsive():
    events = queue.Queue()
    for _ in range(150):
        events.put(_Event('log', 'message'))
    view = SimpleNamespace(
        _event_queue=events, root=MagicMock(), _worker_thread=None,
        _handle_event=MagicMock(), _poll_queue=MagicMock(),
    )
    ImageCompressorApp._poll_queue(view)
    assert view._handle_event.call_count == 100
    assert events.qsize() == 50
    view.root.after.assert_called_once()
