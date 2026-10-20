import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from denialnav import datafactory  # noqa: E402
from denialnav.agent import Agent  # noqa: E402
from denialnav.knowledge import Library  # noqa: E402
from denialnav import refdata  # noqa: E402
from denialnav.service import Service  # noqa: E402

AS_OF = date(2026, 10, 20)


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    datafactory.generate(out, AS_OF, n_patients=150, n_claims=500, seed=5)
    return out


@pytest.fixture()
def svc(dataset):
    s = Service(dataset, ":memory:", agent=Agent(Library(refdata.load()), client=False or None))
    s.agent.client, s.agent.mode = None, "offline"
    s.bootstrap()
    return s
