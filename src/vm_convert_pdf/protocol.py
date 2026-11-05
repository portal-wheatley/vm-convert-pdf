"""Parser for the stream the conversion VM sends back.

Everything read here comes from a VM that may be fully compromised. The only
bytes we interpret are short, bounded framing lines and the PPM header; pixel
data is passed through as an opaque buffer of exactly width*height*3 bytes.

Stream format:

    PAGES <n>\\n
    n times:
        PAGE\\n
        P6\\n<width> <height>\\n255\\n<width*height*3 bytes of RGB>
    END\\n

The guest may send ERROR\\n in place of any framing line.
"""

import re
from typing import BinaryIO, Callable

MAX_LINE = 64

_PAGES_RE = re.compile(rb"PAGES ([0-9]{1,6})")
_DIMS_RE = re.compile(rb"([0-9]{1,5}) ([0-9]{1,5})")


class ProtocolError(Exception):
    """The guest sent something that does not follow the protocol."""


class GuestError(Exception):
    """The guest reported that it could not render the document."""


def read_line(f: BinaryIO) -> bytes:
    line = f.readline(MAX_LINE + 1)
    if not line.endswith(b"\n"):
        if len(line) > MAX_LINE:
            raise ProtocolError("framing line too long")
        raise ProtocolError("stream ended unexpectedly")
    return line[:-1]


def read_exact(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise ProtocolError(f"stream ended after {len(data)} of {n} bytes")
    return data


def _expect(f: BinaryIO, expected: bytes) -> None:
    line = read_line(f)
    if line == b"ERROR":
        raise GuestError("guest failed to render the document")
    if line != expected:
        raise ProtocolError(f"expected {expected!r}, got {line[:32]!r}")


def read_ppm_header(f: BinaryIO, max_dim: int) -> tuple[int, int]:
    if read_line(f) != b"P6":
        raise ProtocolError("page is not a binary RGB PPM")
    m = _DIMS_RE.fullmatch(read_line(f))
    if not m:
        raise ProtocolError("bad PPM dimensions")
    width, height = int(m[1]), int(m[2])
    if not (1 <= width <= max_dim and 1 <= height <= max_dim):
        raise ProtocolError(f"page size {width}x{height} out of bounds")
    if read_line(f) != b"255":
        raise ProtocolError("PPM maxval is not 255")
    return width, height


def read_document(
    f: BinaryIO,
    *,
    max_pages: int,
    max_dim: int,
    on_page: Callable[[int, int, int, bytes], None],
) -> int:
    """Read a whole document, calling on_page(index, width, height, rgb).

    Returns the number of pages.
    """
    line = read_line(f)
    if line == b"ERROR":
        raise GuestError("guest failed to open the document")
    m = _PAGES_RE.fullmatch(line)
    if not m:
        raise ProtocolError(f"bad page count line {line[:32]!r}")
    pages = int(m[1])
    if not 1 <= pages <= max_pages:
        raise ProtocolError(f"page count {pages} out of bounds (max {max_pages})")

    for index in range(pages):
        _expect(f, b"PAGE")
        width, height = read_ppm_header(f, max_dim)
        rgb = read_exact(f, width * height * 3)
        on_page(index, width, height, rgb)

    _expect(f, b"END")
    return pages
