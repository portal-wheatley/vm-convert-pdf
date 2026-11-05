# vm-convert-pdf

Turn an untrusted PDF into a safe one, in the spirit of Qubes'
`qvm-convert-pdf`.

The PDF is opened inside a throwaway QEMU virtual machine. The VM renders
each page to a plain RGB bitmap and sends the pixels back. The host then
builds a brand new PDF out of those pictures. Scripts, fonts, links, forms,
attachments and metadata from the original never reach your desktop's PDF
viewer, and an exploit in the renderer only ever runs inside the VM.

```console
$ vm-convert-pdf invoice.pdf
invoice.pdf -> invoice.trusted.pdf (3 pages)
```

## Install on NixOS

Run it without installing:

```console
$ nix run github:portal-wheatley/vm-convert-pdf -- some.pdf
```

Or add it to your system flake:

```nix
{
  inputs.vm-convert-pdf.url = "github:portal-wheatley/vm-convert-pdf";

  outputs = { nixpkgs, vm-convert-pdf, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      modules = [
        ({ pkgs, ... }: {
          environment.systemPackages = [
            vm-convert-pdf.packages.${pkgs.stdenv.hostPlatform.system}.default
          ];
          # Fast VMs need /dev/kvm; without it the tool falls back to
          # (much slower) emulation.
          users.users.yourname.extraGroups = [ "kvm" ];
        })
      ];
    };
  };
}
```

An overlay is also exported as `overlays.default`, providing
`pkgs.vm-convert-pdf`.

While the repository is private, Nix needs a GitHub token to fetch it: add
`access-tokens = github.com=<token>` to `nix.conf`, or use a
`git+ssh://git@github.com/portal-wheatley/vm-convert-pdf` URL with an SSH
key that has access.

Tested on x86_64-linux. The flake also builds for aarch64-linux, but the VM
has not been booted there yet.

## Usage

```
vm-convert-pdf [options] PDF [PDF ...]

  -o, --output FILE   output file (single input only; default NAME.trusted.pdf)
  -f, --force         overwrite existing output files
  --dpi N             render resolution (default 150)
  --memory MIB        VM memory (default 1024)
  --timeout SECONDS   time allowed per document (default 600)
  --max-pages N       reject documents with more pages (default 5000)
  --max-dim PIXELS    reject pages larger than this (default 10000)
  --accel auto|kvm|tcg
  -v, --verbose       show the guest console (control characters removed)
```

The original file is never modified. With KVM, a 16-page document takes
about 4 seconds at 150 dpi.

## How it works

```
 host                                    disposable VM (no network, no shared fs)
 ────                                    ─────────────────────────────────────────
 copy PDF to a read-only raw disk  ───▶  /dev/vda
                                         mutool draw, one page at a time
 strict parser  ◀── virtio serial ─────  PAGES n / PAGE + PPM … / END
 pixels → PNG → img2pdf
 NAME.trusted.pdf
```

* **The VM** is a stock NixOS kernel plus an initrd that holds only busybox,
  kmod and mupdf. It is created fresh for every document and has no disk
  other than the read-only input, no network card and no shared folders.
  QEMU runs with `-nodefaults`, `-nic none` and its seccomp sandbox
  (`-sandbox on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny`),
  and is killed when the conversion ends, when it times out, or if the CLI
  itself dies.
* **The host** treats everything coming out of the VM as hostile. It reads
  short framing lines with a hard length limit, accepts only a binary PPM
  header of the exact form `P6\n<w> <h>\n255\n` with bounded dimensions, then
  reads exactly `w*h*3` bytes of pixels. Anything else aborts the conversion
  and kills the VM. The pixel buffer is handed to Pillow as raw RGB (no
  image-format parsing), saved as PNG, and img2pdf assembles the output
  losslessly at the original page size.

## Differences from qvm-convert-pdf

* The isolation boundary is QEMU/KVM on your normal Linux host, not Xen and a
  separate disposable qube. A bug in QEMU or KVM could let a compromised
  guest escape, so this is weaker than Qubes, though much stronger than
  opening the file directly.
* The output is pictures of the pages. Text cannot be selected or searched,
  and the file is bigger than the original (roughly 230 KB per page at
  150 dpi).
* Password-protected PDFs are not supported.

## Development

```console
$ nix build            # builds the CLI and runs the parser unit tests
$ nix flake check      # also boots the VM on a test PDF (needs a kvm-capable builder)
$ nix build .#guest-initrd .#guest-kernel
```

`tests/end-to-end.nix` builds a PDF that uses non-embedded Helvetica and
Times plus an OpenAction script, converts it, and checks that the text is
visible and that no fonts or scripts survive.
