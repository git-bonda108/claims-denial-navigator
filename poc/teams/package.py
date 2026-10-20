"""Build the Teams app package:  python teams/package.py https://<your-app>.azurecontainerapps.io"""
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

here = Path(__file__).parent
url = sys.argv[1].rstrip("/")
manifest = (here / "manifest.template.json").read_text().replace("{{APP_URL}}", url).replace("{{APP_HOST}}", urlparse(url).netloc)
json.loads(manifest)
out = here / "denial-navigator-teams.zip"
with zipfile.ZipFile(out, "w") as z:
    z.writestr("manifest.json", manifest)
    z.write(here / "color.png", "color.png")
    z.write(here / "outline.png", "outline.png")
print(f"Wrote {out} - upload it in Teams: Apps > Manage your apps > Upload an app")
