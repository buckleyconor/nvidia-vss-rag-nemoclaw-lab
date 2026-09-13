"""Pack manifests (§5.1, §11) — loading, validation, path safety, the repo
pack itself."""

import pytest
from pydantic import ValidationError

from app import packs
from conftest import PACK_ID, PACK_YAML, REPO, write_pack


def test_loads_test_pack(packs_dir):
    loaded = packs.load_packs(packs_dir)
    pack = loaded[PACK_ID]
    assert pack.manifest.fleet[0].commissioned == "2019-04"
    assert pack.manifest.fleet[0].service_history[0].date == "2025-07-14"
    assert pack.declared_clips() == ["anomaly.mp4", "normal.mp4"]
    assert pack.asset("M-2").display_name == "Motor M-2"
    assert pack.asset("nope") is None
    assert pack.incident("nope") is None
    assert pack.document("manual-01").content_type == "manual"
    assert pack.document_path("nope") is None


def test_agent_view_drops_ambiguous_and_seed_clips(packs_dir):
    pack = packs.load_packs(packs_dir)[PACK_ID]
    incident = pack.incident("M1-BEARING")
    assert "ambiguous" not in pack.incident_view(incident, for_agent=True)
    assert "archive_seed_clips" not in pack.incident_view(incident, for_agent=True)
    assert pack.incident_view(incident, for_agent=False)["ambiguous"] is True


def test_undeclared_and_escaping_clips_are_refused(packs_dir):
    pack = packs.load_packs(packs_dir)[PACK_ID]
    (packs_dir / PACK_ID / "clips" / "other.mp4").write_bytes(b"x")
    assert pack.clip_path("other.mp4") is None
    assert pack.clip_path("../pack.yaml") is None


@pytest.mark.parametrize("bad,match", [
    (PACK_YAML.replace("asset_id: M-2", "asset_id: M-1"), "duplicate asset_id"),
    (PACK_YAML.replace("asset_id: M-1\n    title: Minor", "asset_id: M-9\n    title: Minor"),
     "unknown asset"),
    (PACK_YAML.replace("vss-ask-video", "rm -rf"), "invalid skill"),
    (PACK_YAML.replace("outcome_class: work_order", "outcome_class: ticket"), "outcome_class"),
    (PACK_YAML + "unexpected_key: 1\n", "unexpected_key"),
])
def test_invalid_manifests_fail_loudly(tmp_path, bad, match):
    root = tmp_path / "p"
    root.mkdir()
    write_pack(root, bad)
    with pytest.raises((ValidationError, ValueError), match=match):
        packs.load_packs(root)


def test_duplicate_incident_ids_rejected(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    write_pack(root, PACK_YAML.replace("incident_id: M1-TREND", "incident_id: M1-BEARING"))
    with pytest.raises(ValidationError, match="duplicate incident_id"):
        packs.load_packs(root)


def test_pack_id_must_match_directory(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    pack = write_pack(root)
    pack.rename(root / "renamed")
    with pytest.raises(ValueError, match="does not match"):
        packs.load_packs(root)


def test_missing_packs_dir_is_empty(tmp_path):
    assert packs.load_packs(tmp_path / "absent") == {}


def test_document_sections():
    text = "# Title\n\n## 4.2 Limits\ntext\n### Replacement procedure\n"
    assert packs.document_sections(text) == [
        {"anchor": "title", "title": "Title", "level": 1, "line": 0},
        {"anchor": "4.2", "title": "4.2 Limits", "level": 2, "line": 2},
        {"anchor": "replacement-procedure", "title": "Replacement procedure",
         "level": 3, "line": 4},
    ]


def test_repo_manufacturing_pack_loads_and_resolves_fixtures():
    """The shipped pack one: valid, and its clips/corpus resolve to fixtures/
    until the M9 move (pack.yaml header)."""
    loaded = packs.load_packs(REPO / "packs")
    pack = loaded["manufacturing-motor-drive"]
    assert 6 <= len(pack.manifest.fleet) <= 12  # §11 authoring checklist
    assert pack.clip_path("clip-anomaly-01.mp4") is not None
    assert {d.id for d in pack.documents} == {"manual-01", "log-01", "schedule-01"}
    assert all(pack.document_path(d.id) for d in pack.documents)
    assert any(p.on_hand_local == 0 for p in pack.manifest.parts)  # checklist
    # O17: only skills that fit the LVS deployment are installed.
    assert set(pack.manifest.skills) == {"vss-generate-video-report-rag",
                                         "vss-ask-video", "vss-manage-video-io-storage"}
