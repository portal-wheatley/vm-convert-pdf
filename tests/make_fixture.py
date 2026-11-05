"""Write a small two-page PDF used by the end-to-end check.

The text uses the standard Helvetica and Times fonts without embedding them,
like many office exports do, so the check fails if the guest renders without
fonts. The document also carries an OpenAction script that must not survive
conversion.
"""

import sys


def build() -> bytes:
    pages = [
        ("F1", "Hello from page one"),
        ("F2", "Page two, set in Times"),
    ]
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R /OpenAction 3 0 R >>",
        3: b"<< /S /JavaScript /JS (app.alert\\('fixture'\\);) >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
    }
    kids = []
    for i, (font, text) in enumerate(pages):
        page_id, content_id = 6 + 2 * i, 7 + 2 * i
        kids.append(f"{page_id} 0 R")
        stream = f"BT /{font} 36 Tf 72 700 Td ({text}) Tj ET".encode()
        objs[content_id] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        objs[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents %d 0 R >>" % content_id
        )
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (num, objs[num])
    xref = len(out)
    size = max(objs) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for num in range(1, size):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(out)


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        f.write(build())
