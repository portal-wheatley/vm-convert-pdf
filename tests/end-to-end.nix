# Boots the real VM on a generated PDF and checks the output: right page
# count, visible text, and nothing left of the original fonts or scripts.
{
  runCommand,
  python3,
  mupdf-headless,
  vm-convert-pdf,
}:

runCommand "vm-convert-pdf-end-to-end"
  {
    nativeBuildInputs = [
      vm-convert-pdf
      mupdf-headless
      (python3.withPackages (ps: [ ps.pillow ]))
    ];
    requiredSystemFeatures = [ "kvm" ];
  }
  ''
    python3 ${./make_fixture.py} input.pdf
    vm-convert-pdf --verbose input.pdf

    mutool info input.trusted.pdf | tee info.txt
    grep -q '^Pages: 2$' info.txt

    if mutool info -F input.trusted.pdf | grep -E 'Helvetica|Times'; then
      echo "fonts survived conversion" >&2
      exit 1
    fi
    if grep -a -q -E 'JavaScript|OpenAction' input.trusted.pdf; then
      echo "script survived conversion" >&2
      exit 1
    fi

    for page in 1 2; do
      mutool draw -q -F pnm -c gray -r 72 -o page$page.pgm input.trusted.pdf $page
      python3 - page$page.pgm <<'EOF'
    import sys
    from PIL import Image
    dark = sum(Image.open(sys.argv[1]).histogram()[:128])
    print(f"{sys.argv[1]}: {dark} dark pixels")
    assert dark > 500, "page looks blank; text was not rendered"
    EOF
    done

    head -c 4096 /dev/urandom > garbage.pdf
    if vm-convert-pdf garbage.pdf; then
      echo "garbage input was accepted" >&2
      exit 1
    fi
    test ! -e garbage.trusted.pdf

    if vm-convert-pdf input.pdf; then
      echo "existing output was overwritten without --force" >&2
      exit 1
    fi

    touch $out
  ''
