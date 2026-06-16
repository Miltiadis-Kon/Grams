{ pkgs }: {
  deps = [
    pkgs.python3
    pkgs.sqlite
    pkgs.nss
    pkgs.nspr
    pkgs.atk
    pkgs.at-spi2-atk
    pkgs.cups
    pkgs.libdrm
    pkgs.expat
    pkgs.libxcb
    pkgs.libxkbcommon
    pkgs.xorg.libXcomposite
    pkgs.xorg.libXdamage
    pkgs.xorg.libXfixes
    pkgs.xorg.libXrandr
    pkgs.xorg.libXext
    pkgs.xorg.libX11
    pkgs.libgbm
    pkgs.pango
    pkgs.cairo
    pkgs.alsa-lib
    pkgs.dbus
    pkgs.glib
    pkgs.gtk3
  ];
}
