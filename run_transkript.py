"""PyInstaller giris betigi.

Ayri bir dosya olarak duruyor cunku PyInstaller paket icindeki bir modulu degil
bir betigi giris noktasi olarak istiyor.
"""

from transkript.main import main

if __name__ == "__main__":
    raise SystemExit(main())
