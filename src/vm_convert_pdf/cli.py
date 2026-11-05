"""Render an untrusted PDF inside a disposable VM and rebuild it from pixels.

The VM has no network and no shared filesystem. It gets the PDF on a
read-only virtual disk and sends back one raw RGB bitmap per page over a
virtio serial port. The host only accepts width, height and pixel bytes,
then builds a new PDF out of those images. Nothing from the original file
(scripts, fonts, links, metadata, forms) survives.
"""

import argparse
import ctypes
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import img2pdf
from PIL import Image

from . import protocol

SECTOR = 512
CONNECT_TIMEOUT = 30
PR_SET_PDEATHSIG = 1


class ConversionError(Exception):
    pass


def env_path(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConversionError(f"{name} is not set; run vm-convert-pdf through its Nix wrapper")
    return value


def default_output(path: Path) -> Path:
    stem = path.name[:-4] if path.name.lower().endswith(".pdf") else path.name
    return path.with_name(stem + ".trusted.pdf")


def kvm_usable() -> bool:
    try:
        fd = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return False
    os.close(fd)
    return True


def write_disk(src: Path, dst: Path) -> None:
    size = src.stat().st_size
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(f"{size}\n".encode().ljust(SECTOR, b"\0"))
        shutil.copyfileobj(fin, fout)
        pad = -fout.tell() % SECTOR
        fout.write(b"\0" * pad)


def qemu_command(args, disk: Path, sock: Path, accel: str) -> list[str]:
    machine = platform.machine()
    if machine == "x86_64":
        machine_type, console = "q35", "ttyS0"
    elif machine == "aarch64":
        machine_type, console = "virt", "ttyAMA0"
    else:
        raise ConversionError(f"unsupported host architecture {machine}")

    cmdline = [f"console={console}", "panic=-1", f"vmpdf.dpi={args.dpi}"]
    if not args.verbose:
        cmdline.append("quiet")

    return [
        env_path("VMPDF_QEMU"),
        "-nodefaults",
        "-no-user-config",
        "-display", "none",
        "-monitor", "none",
        "-nic", "none",
        "-no-reboot",
        "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny",
        "-machine", machine_type,
        "-accel", accel,
        "-cpu", "host" if accel == "kvm" else "max",
        "-smp", "1",
        "-m", str(args.memory),
        "-kernel", env_path("VMPDF_KERNEL"),
        "-initrd", env_path("VMPDF_INITRD"),
        "-append", " ".join(cmdline),
        "-drive", f"file={disk},format=raw,if=none,id=in,readonly=on",
        "-device", "virtio-blk-pci,drive=in",
        "-device", "virtio-serial-pci",
        "-chardev", f"socket,id=out,path={sock}",
        "-device", "virtserialport,chardev=out,name=out",
        "-serial", "stdio" if args.verbose else "null",
    ]


def die_with_parent() -> None:
    """Make sure the VM never outlives this process."""
    ctypes.CDLL(None).prctl(PR_SET_PDEATHSIG, signal.SIGKILL)


def relay_console(stream) -> None:
    """Copy guest console output to stderr, dropping control characters."""
    for line in iter(stream.readline, b""):
        clean = bytes(c if 0x20 <= c < 0x7F or c == 0x09 else 0x3F for c in line.rstrip(b"\r\n"))
        sys.stderr.write("guest: " + clean.decode("ascii") + "\n")


def accept(server: socket.socket, qemu: subprocess.Popen) -> socket.socket:
    deadline = time.monotonic() + CONNECT_TIMEOUT
    server.settimeout(0.2)
    while time.monotonic() < deadline:
        if qemu.poll() is not None:
            raise ConversionError(f"qemu exited with status {qemu.returncode} before starting")
        try:
            conn, _ = server.accept()
        except TimeoutError:
            continue
        conn.settimeout(None)
        return conn
    raise ConversionError("qemu did not connect to the output socket")


def convert(src: Path, dst: Path, args) -> int:
    accel = args.accel
    if accel == "auto":
        accel = "kvm" if kvm_usable() else "tcg"
        if accel == "tcg":
            print("vm-convert-pdf: /dev/kvm not usable, falling back to slow emulation", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="vm-convert-pdf.") as tmpdir:
        tmp = Path(tmpdir)
        disk = tmp / "input.img"
        sock = tmp / "out.sock"
        write_disk(src, disk)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock))
        server.listen(1)

        qemu = subprocess.Popen(
            qemu_command(args, disk, sock, accel),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if args.verbose else subprocess.DEVNULL,
            preexec_fn=die_with_parent,
        )
        if args.verbose:
            threading.Thread(target=relay_console, args=(qemu.stdout,), daemon=True).start()

        timed_out = threading.Event()

        def on_timeout():
            timed_out.set()
            qemu.kill()

        watchdog = threading.Timer(args.timeout, on_timeout)
        watchdog.start()
        pages: list[Path] = []

        def on_page(index: int, width: int, height: int, rgb: bytes) -> None:
            path = tmp / f"page-{index:06d}.png"
            Image.frombytes("RGB", (width, height), rgb).save(path, dpi=(args.dpi, args.dpi))
            pages.append(path)
            if args.verbose:
                print(f"vm-convert-pdf: page {index + 1} {width}x{height}", file=sys.stderr)

        try:
            conn = accept(server, qemu)
            with conn, conn.makefile("rb") as stream:
                protocol.read_document(
                    stream,
                    max_pages=args.max_pages,
                    max_dim=args.max_dim,
                    on_page=on_page,
                )
        except protocol.ProtocolError as e:
            if timed_out.is_set():
                raise ConversionError(f"timed out after {args.timeout:g}s") from None
            raise ConversionError(f"rejected output from VM: {e}") from None
        except protocol.GuestError as e:
            raise ConversionError(str(e)) from None
        finally:
            watchdog.cancel()
            qemu.kill()
            qemu.wait()
            server.close()

        partial = dst.with_name(f".{dst.name}.partial")
        try:
            with open(partial, "wb") as f:
                img2pdf.convert([str(p) for p in pages], outputstream=f)
            os.replace(partial, dst)
        finally:
            partial.unlink(missing_ok=True)
        return len(pages)


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="vm-convert-pdf",
        description="Convert untrusted PDFs to safe image-only PDFs by rendering them in a disposable VM.",
    )
    ap.add_argument("inputs", nargs="+", type=Path, metavar="PDF")
    ap.add_argument("-o", "--output", type=Path, help="output file (only with a single input; default: NAME.trusted.pdf)")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing output files")
    ap.add_argument("--dpi", type=int, default=150, help="render resolution (default: 150)")
    ap.add_argument("--memory", type=int, default=1024, help="VM memory in MiB (default: 1024)")
    ap.add_argument("--timeout", type=float, default=600, help="seconds allowed per document (default: 600)")
    ap.add_argument("--max-pages", type=int, default=5000, help="reject documents with more pages (default: 5000)")
    ap.add_argument("--max-dim", type=int, default=10000, help="reject pages wider or taller than this many pixels (default: 10000)")
    ap.add_argument("--accel", choices=["auto", "kvm", "tcg"], default="auto", help="QEMU accelerator (default: auto)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the (sanitized) guest console")
    args = ap.parse_args(argv)
    if args.output and len(args.inputs) > 1:
        ap.error("--output can only be used with a single input")
    if not 10 <= args.dpi <= 1200:
        ap.error("--dpi must be between 10 and 1200")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    failed = 0
    for src in args.inputs:
        dst = args.output or default_output(src)
        try:
            if not src.is_file():
                raise ConversionError("not a regular file")
            if dst.exists() and not args.force:
                raise ConversionError(f"{dst} already exists (use --force to overwrite)")
            pages = convert(src, dst, args)
        except (ConversionError, OSError) as e:
            print(f"vm-convert-pdf: {src}: {e}", file=sys.stderr)
            failed += 1
            continue
        print(f"{src} -> {dst} ({pages} page{'s' if pages != 1 else ''})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
