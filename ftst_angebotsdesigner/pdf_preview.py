"""Bounded, local page images for mobile review of the actual frozen PDF."""
import io
from pathlib import Path
import subprocess
import tempfile
from threading import BoundedSemaphore

from pypdf import PdfReader

_render_slots = BoundedSemaphore(2)


def page_count(pdf):
    count = len(PdfReader(io.BytesIO(pdf)).pages)
    if not 1 <= count <= 100:
        raise ValueError('PDF page limit exceeded')
    return count


def render_page(pdf, number):
    if not 1 <= number <= page_count(pdf):
        raise ValueError('Invalid page')
    if not _render_slots.acquire(timeout=2):
        raise OSError('Preview busy')
    try:
        with tempfile.TemporaryDirectory(prefix='ftst-preview-') as directory:
            source = Path(directory) / 'document.pdf'
            output = Path(directory) / 'page'
            source.write_bytes(pdf)
            subprocess.run(
                ['pdftoppm', '-f', str(number), '-l', str(number), '-singlefile',
                 '-scale-to', '1600', '-png', str(source), str(output)],
                check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return output.with_suffix('.png').read_bytes()
    finally:
        _render_slots.release()
