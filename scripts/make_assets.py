"""Generates build/perch.ico and the Windows version-info files used by PyInstaller."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from perch import APP_NAME, PUBLISHER, __version__, icons  # noqa: E402

BUILD = os.path.join(ROOT, "build")
TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={v4}, prodvers={v4}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{company}'),
      StringStruct('FileDescription', '{desc}'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{product}'),
      StringStruct('ProductVersion', '{v}'),
      StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    os.makedirs(BUILD, exist_ok=True)
    icons.save_ico(os.path.join(BUILD, "perch.ico"))
    parts = [int(p) for p in __version__.split(".")] + [0] * 4
    v4 = tuple(parts[:4])
    for name, desc, fname in (
        ("Perch", APP_NAME, "version_perch.txt"),
        ("perch-agent", f"{APP_NAME} agent", "version_agent.txt"),
    ):
        with open(os.path.join(BUILD, fname), "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(v4=v4, v=__version__, company=PUBLISHER, desc=desc, name=name, product=APP_NAME))
    print("assets ->", BUILD)


if __name__ == "__main__":
    main()
