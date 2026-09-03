"""L4 fixture suite (05: TC-042..TC-044) — fixture manifests + file
validity.

Gates STRUCTURE, not content (ADR-004, 08 item 17): the committed
fixtures are provisional stand-ins (synthetic ftyp MP4 probes, a small
curated-shape corpus); real clips/corpus are swapped in at environment
prep. Every manifest must parse, every referenced file must exist and be
non-empty, MP4s carry the ftyp box at offset 4 (pure-Python check — no
ffmpeg), the corpus covers the manual + log + schedule content types beat
3 retrieves over, and the rag-index manifest names collection
demo_corpus with a built_from hash matching the corpus aggregate.

Repo-level suite (the closing gate runs `pytest mock-wo/tests tests`);
YAML parsing uses the pinned dev dependency pyyaml (03 dev table).
"""

import hashlib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tc042_video_manifest_and_clips():
    manifest = yaml.safe_load((FIXTURES / "video/manifest.yaml").read_text())
    clips = manifest["clips"]
    assert clips, "video manifest lists no clips"
    roles = set()
    seen_files = set()
    for clip in clips:
        for key in ("id", "role", "file", "duration_s", "equipment"):
            assert clip.get(key), f"clip entry missing {key!r}: {clip!r}"
        assert clip["role"] in ("normal", "anomaly"), (
            f"clip {clip['id']} has bad role {clip['role']!r}"
        )
        roles.add(clip["role"])
        assert clip["file"] not in seen_files, f"duplicate clip file: {clip['file']}"
        seen_files.add(clip["file"])
        assert clip["file"].endswith(".mp4"), f"clip is not .mp4: {clip['file']}"
        path = FIXTURES / "video" / clip["file"]
        assert path.is_file(), f"clip missing: {clip['file']}"
        data = path.read_bytes()
        assert len(data) > 0, f"clip is empty: {clip['file']}"
        assert data[4:8] == b"ftyp", (
            f"ftyp box not at offset 4 in {clip['file']} (bytes 4:8 = {data[4:8]!r})"
        )
    # the beats need both a normal-state set (beat 1) and an anomaly
    # segment (beat 2) — structure the learner experience depends on.
    assert roles == {"normal", "anomaly"}, (
        f"clips do not cover both beats (want normal + anomaly): {roles}"
    )


def test_tc043_corpus_manifest_and_docs():
    manifest = yaml.safe_load((FIXTURES / "corpus/manifest.yaml").read_text())
    docs = manifest["documents"]
    assert docs, "corpus manifest lists no documents"
    content_types = set()
    seen_files = set()
    for doc in docs:
        for key in ("id", "content_type", "file", "sha256"):
            assert doc.get(key), f"document entry missing {key!r}: {doc!r}"
        assert doc["content_type"] in ("manual", "log", "schedule"), (
            f"document {doc['id']} has bad content_type {doc['content_type']!r}"
        )
        content_types.add(doc["content_type"])
        assert doc["file"] not in seen_files, f"duplicate document file: {doc['file']}"
        seen_files.add(doc["file"])
        path = FIXTURES / "corpus" / doc["file"]
        assert path.is_file(), f"document missing: {doc['file']}"
        assert path.stat().st_size > 0, f"document is empty: {doc['file']}"
        assert _sha256(path) == doc["sha256"], (
            f"sha256 drift for {doc['file']} — recompute and update the manifest"
        )
    # beat 3 retrieves over manuals, logs AND the maintenance schedule —
    # all three content types must be present (sizing reduction row;
    # TC-043).
    assert content_types == {"manual", "log", "schedule"}, (
        f"corpus does not cover all beat-3 content types (want manual + "
        f"log + schedule): {content_types}"
    )


def test_tc044_rag_index_manifest():
    corpus = yaml.safe_load((FIXTURES / "corpus/manifest.yaml").read_text())
    manifest = yaml.safe_load((FIXTURES / "rag-index/manifest.yaml").read_text())
    assert manifest.get("collection_name") == "demo_corpus", (
        "rag-index collection_name must be demo_corpus (= KNOWLEDGE_COLLECTION, 02)"
    )
    # the aggregate rule is declared in the rag-index manifest header:
    # sha256 of the newline-joined per-document sha256 values, in corpus
    # manifest order (TC-044).
    aggregate = hashlib.sha256(
        "\n".join(doc["sha256"] for doc in corpus["documents"]).encode()
    ).hexdigest()
    assert manifest.get("built_from") == aggregate, (
        f"built_from {str(manifest.get('built_from'))[:16]}… does not match the "
        f"corpus aggregate {aggregate[:16]}… (corpus changed without updating "
        "the rag-index manifest)"
    )
    # artifact is an optional fast path (prep-defined — 08): absent or
    # null in the provisional state; if present it must be non-empty.
    artifact = manifest.get("artifact")
    if artifact:
        path = FIXTURES / "rag-index" / artifact
        assert path.is_file() and path.stat().st_size > 0, (
            f"artifact {artifact!r} is present in the manifest but missing or empty"
        )
