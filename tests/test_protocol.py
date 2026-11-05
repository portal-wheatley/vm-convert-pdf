import io

import pytest

from vm_convert_pdf.protocol import GuestError, ProtocolError, read_document


def page(width, height, fill=b"\x00"):
    return b"PAGE\n" + f"P6\n{width} {height}\n255\n".encode() + fill * (width * height * 3)


def run(data, max_pages=10, max_dim=100):
    got = []
    n = read_document(
        io.BytesIO(data),
        max_pages=max_pages,
        max_dim=max_dim,
        on_page=lambda i, w, h, rgb: got.append((i, w, h, len(rgb))),
    )
    return n, got


def test_valid_document():
    data = b"PAGES 2\n" + page(3, 2) + page(1, 1, b"\xff") + b"END\n"
    assert run(data) == (2, [(0, 3, 2, 18), (1, 1, 1, 3)])


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"PAGES 1\n",
        b"PAGES 0\nEND\n",
        b"PAGES 11\n",
        b"PAGES -1\n",
        b"PAGES 1 \n",
        b"PAGES 1\n" + page(3, 2)[:-1],
        b"PAGES 1\n" + page(3, 2),
        b"PAGES 1\n" + page(3, 2) + b"END",
        b"PAGES 1\n" + page(3, 2) + b"EXTRA\n",
        b"PAGES 1\nPAGE\nP5\n1 1\n255\n\x00",
        b"PAGES 1\nPAGE\nP6\n1 1\n65535\n" + b"\x00" * 6,
        b"PAGES 1\nPAGE\nP6\n0 1\n255\n",
        b"PAGES 1\nPAGE\nP6\n101 1\n255\n",
        b"PAGES 1\nPAGE\nP6\n1 1 1\n255\n",
        b"PAGES 1\nPAGE\nP6\n# comment\n1 1\n255\n",
        b"PAGES 1\nPAGE\nP6 1 1 255\n",
        b"PAGES 1\nPAGE\nP6\n\xd9\xa1 1\n255\n",
        b"P" * 1000 + b"\n",
    ],
)
def test_rejects_malformed(data):
    with pytest.raises(ProtocolError):
        run(data)


@pytest.mark.parametrize(
    "data",
    [b"ERROR\n", b"PAGES 2\n" + page(1, 1) + b"ERROR\n", b"PAGES 1\n" + page(1, 1) + b"ERROR\n"],
)
def test_guest_error(data):
    with pytest.raises(GuestError):
        run(data)
