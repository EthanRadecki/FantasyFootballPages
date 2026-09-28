import importlib.util
import re
from pathlib import Path

from engine.identity import member_key

REPO = Path(__file__).resolve().parents[2]


def test_member_key_format_and_normalization():
    k = member_key("{90167A92-7531-494A-BC30-FF8699CCF401}")
    assert re.fullmatch(r"m_[0-9a-f]{12}", k)
    assert k == member_key("90167a92-7531-494a-bc30-ff8699ccf401")


def test_tool_copy_matches_engine():
    spec = importlib.util.spec_from_file_location("espn_members", REPO / "tools" / "espn_members.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sample = "{B9E01B37-7763-45B4-8D1A-02191411E488}"
    assert mod.member_key(sample) == member_key(sample)
