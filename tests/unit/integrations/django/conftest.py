"""Configure Django once for the django-integration unit tests."""

import importlib
import sys
from pathlib import Path

_test_dir = Path(__file__).resolve().parent
_removed = [entry for entry in sys.path if Path(entry or ".").resolve() == _test_dir]
for entry in _removed:
    sys.path.remove(entry)

django = importlib.import_module("django")
settings = importlib.import_module("django.conf").settings

if not settings.configured:
    settings.configure(
        DEBUG=True,
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=["dblift.integrations.django"],
        DBLIFT_MIGRATIONS_DIR="/tmp/_dblift_placeholder",
        USE_TZ=True,
    )
    django.setup()

for entry in reversed(_removed):
    sys.path.insert(0, entry)
