# Kernel and initrd for the disposable conversion VM. The initrd is the whole
# guest: a busybox init script plus mupdf, with no network stack configured
# and no persistent storage.
{
  lib,
  linuxPackages,
  makeModulesClosure,
  makeInitrd,
  replaceVarsWith,
  busybox,
  kmod,
  mupdf-headless,
}:

let
  kernel = linuxPackages.kernel;

  modules = makeModulesClosure {
    kernel = lib.getOutput "modules" kernel;
    firmware = lib.getOutput "modules" kernel;
    rootModules = [
      "virtio_pci"
      "virtio_blk"
      "virtio_console"
    ];
  };

  init = replaceVarsWith {
    src = ./guest/init.sh;
    isExecutable = true;
    replacements = {
      inherit busybox kmod modules;
      mupdf = mupdf-headless;
      countPages = ./guest/count-pages.js;
    };
  };
in
{
  inherit kernel modules init;

  kernelImage = "${kernel}/${kernel.target}";

  initrd = makeInitrd {
    name = "vm-convert-pdf-initrd";
    contents = [
      {
        object = init;
        symlink = "/init";
      }
    ];
  };
}
