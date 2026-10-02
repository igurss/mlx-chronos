# Bundled CLI and runtime dependencies

The app includes the unmodified published
`mlx_chronos-0.5.0-py3-none-any.whl` package from PyPI:

- Project/source: https://github.com/igurss/mlx-chronos
- Published package: https://pypi.org/project/mlx-chronos/0.5.0/
- License: Apache License 2.0. The full license is included inside the wheel at
  `mlx_chronos-0.5.0.dist-info/licenses/LICENSE`, and is retained when installed.
- The exact wheel SHA-256 is recorded in
  `MLXChronos/Resources/runtime_manifest.json` and checked before preparation.

The wheel is not a Python interpreter. Preparation downloads and installs the
CLI's declared dependencies, including its mandatory thermal extra
(`pyobjc-framework-Cocoa` and its dependencies), in the dedicated environment.
Those dependencies retain their upstream package metadata and licenses. No
engine application, model weights or Python interpreter is redistributed by
this app build.

The Swift/Python adapter configures and invokes the package; it does not modify
the bundled CLI code. App and CLI versions are separately recorded.
