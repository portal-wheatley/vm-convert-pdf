{
  lib,
  callPackage,
  python3Packages,
  qemu_kvm,
  stdenv,
}:

let
  guest = callPackage ./guest.nix { };
  qemuSystem = "qemu-system-${stdenv.hostPlatform.qemuArch}";
in
python3Packages.buildPythonApplication {
  pname = "vm-convert-pdf";
  version = "0.1.0";
  pyproject = true;

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./pyproject.toml
      ./src
      ./tests/test_protocol.py
    ];
  };

  build-system = [ python3Packages.setuptools ];

  dependencies = with python3Packages; [
    pillow
    img2pdf
  ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  makeWrapperArgs = [
    "--set-default"
    "VMPDF_QEMU"
    "${qemu_kvm}/bin/${qemuSystem}"
    "--set-default"
    "VMPDF_KERNEL"
    guest.kernelImage
    "--set-default"
    "VMPDF_INITRD"
    "${guest.initrd}/initrd"
  ];

  passthru = { inherit guest; };

  meta = {
    description = "Convert untrusted PDFs to safe image-only PDFs by rendering them in a disposable VM";
    license = lib.licenses.mit;
    mainProgram = "vm-convert-pdf";
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
  };
}
