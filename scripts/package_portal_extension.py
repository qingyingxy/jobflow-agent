"""Package only runtime extension files; no credentials or personal observations."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
destination = root / "frontend/public/jobflow-portal-extension.zip"
destination.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
    for name in ("manifest.json", "background.js", "bridge.js", "tongcheng.js", "README.md"):
        archive.write(root / "browser-extension" / name, name)
print(destination)
