#!@busybox@/bin/sh
# PID 1 of the disposable conversion VM.
#
# Everything in here may be compromised by the PDF being rendered. The host
# treats every byte written to the output port as untrusted and validates it.
#
# Input:  /dev/vda   = 512-byte header (decimal PDF length + "\n"), then the PDF.
# Output: virtio port "out", framed as:
#           PAGES <n>\n
#           n times: PAGE\n <binary PPM (P6, maxval 255)>
#           END\n
#         or ERROR\n at any point.

export PATH=@busybox@/bin:@kmod@/bin:@mupdf@/bin
port=

mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev
mkdir -p /tmp
mount -t tmpfs -o mode=1777 tmp /tmp

# Powering off drops whatever the host has not read from the port yet, so
# once the last frame is written we wait for the host to kill the VM. The
# poweroff is only a fallback in case the host went away.
finish() {
  sleep 60
  poweroff -f
}

die() {
  echo "vm-convert-pdf guest: $*" >&2
  # The serial console transmits asynchronously; give it time to drain so
  # the host captures the reason before it kills or loses the VM.
  sleep 1
  if [ -n "$port" ]; then
    echo ERROR >&3
    finish
  fi
  poweroff -f
}

# The virtio drivers are loadable modules on some kernels (x86_64) and built
# in on others (aarch64), where modprobe fails because the trimmed module
# tree does not list them. So a failed modprobe is not fatal: the device
# checks below catch a driver that is really missing.
mkdir -p /lib
ln -s @modules@/lib/modules /lib/modules
for m in virtio_pci virtio_blk virtio_console; do
  modprobe "$m" 2>/dev/null || true
done

dpi=150
for arg in $(cat /proc/cmdline); do
  case "$arg" in
    vmpdf.dpi=*) dpi="${arg#vmpdf.dpi=}" ;;
  esac
done
case "$dpi" in
  ''|*[!0-9]*) die "bad dpi" ;;
esac

# devtmpfs creates the device nodes; without udev we resolve the port by name.
found=
for _ in $(seq 50); do
  for p in /sys/class/virtio-ports/*; do
    [ -e "$p/name" ] || continue
    [ "$(cat "$p/name")" = out ] && found="/dev/${p##*/}"
  done
  [ -n "$found" ] && [ -e "$found" ] && [ -b /dev/vda ] && break
  found=
  sleep 0.1
done
[ -n "$found" ] || die "output port or input disk not found (virtio drivers missing?)"
port=$found
exec 3>"$port"
len=$(head -c 512 /dev/vda | head -n 1)
case "$len" in
  ''|*[!0-9]*) die "bad input header" ;;
esac
dd if=/dev/vda bs=512 skip=1 2>/dev/null | head -c "$len" > /tmp/in.pdf
[ "$(wc -c < /tmp/in.pdf)" -eq "$len" ] || die "short input"

pages=$(mutool run @countPages@ /tmp/in.pdf) || die "cannot open PDF"
case "$pages" in
  ''|*[!0-9]*) die "bad page count" ;;
esac
echo "PAGES $pages" >&3

i=1
while [ "$i" -le "$pages" ]; do
  # Render to tmpfs first so a renderer crash never leaves a partial frame.
  mutool draw -q -F pnm -c rgb -r "$dpi" -o /tmp/page.ppm /tmp/in.pdf "$i" \
    || die "rendering page $i failed"
  echo PAGE >&3
  cat /tmp/page.ppm >&3
  rm -f /tmp/page.ppm
  i=$((i + 1))
done

echo END >&3
finish
