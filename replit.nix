{ pkgs }: {
  deps = [
    pkgs.python3
    pkgs.playwright-driver.browsers
    pkgs.sqlite
  ];
}
