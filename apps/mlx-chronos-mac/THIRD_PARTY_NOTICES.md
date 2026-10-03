# Downloaded Python and CLI dependencies

The app contains a small Python adapter and the project's Apache-2.0 license.
It does not redistribute a CLI wheel, Python interpreter, engines or models.

At preparation time it downloads verified artifacts described by the official
[compatibility catalog](https://igurss.github.io/mlx-chronos/app-runtime.json):

- [python-build-standalone](https://github.com/astral-sh/python-build-standalone),
  a CPython distribution with its upstream license files. See its
  [licensing documentation](https://gregoryszorc.com/docs/python-build-standalone/main/licensing.html).
- [mlx-chronos on PyPI](https://pypi.org/project/mlx-chronos/), Apache-2.0.
  The installed wheel retains its license and distribution metadata.
- CLI dependencies including mandatory Foundation thermal support
  (`pyobjc-framework-Cocoa`). Each installed distribution retains its upstream
  metadata and licenses.

Python archives and CLI wheels are checked against the catalog's SHA-256
before use. The catalog and package services use HTTPS. App and CLI versions,
app interface compatibility and benchmark protocol are separate identifiers.
