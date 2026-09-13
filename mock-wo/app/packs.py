"""Pack manifests — operator-dashboard-spec §5.1, §11.

A pack is content, not code: ``packs/<pack_id>/pack.yaml`` plus its clips and
corpus. Adding a vertical must not require touching anything outside
``packs/`` (goal 4). The loader validates the manifest once at start-up and
exposes two views of an incident: the operator view (everything) and the
agent view, which never carries ``ambiguous`` — an agent told in advance that
an incident is ambiguous is performing uncertainty, not reaching it (§5.1,
ADR-V03).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _date_text(value: Any) -> Any:
    """YAML turns an unquoted 2025-07-14 into a date; authors should not have
    to quote dates, so accept both and keep ISO text."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


DateText = Annotated[str, BeforeValidator(_date_text)]

SLUG = r"^[a-z0-9][a-z0-9-]{0,62}$"
ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
FILE = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"


class ServiceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: DateText = Field(min_length=4, max_length=20)
    summary: str = Field(min_length=1, max_length=500)
    technician: str = Field(default="", max_length=100)


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(pattern=ID)
    display_name: str = Field(min_length=1, max_length=100)
    make_model: str = Field(default="", max_length=100)
    commissioned: DateText = Field(default="", max_length=20)
    location: str = Field(default="", max_length=100)
    baseline_clips: List[str] = Field(default_factory=list)
    thumbnail: Optional[str] = Field(default=None, pattern=FILE)
    service_history: List[ServiceRecord] = Field(default_factory=list)


class SeedClip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: DateText
    clip: str = Field(pattern=FILE)


class PackIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(pattern=ID)
    asset_id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=200)
    clip: str = Field(pattern=FILE)
    outcome_class: str = Field(pattern=r"^(work_order|monitoring_note)$")
    downtime_cost_per_hour: float = Field(ge=0)
    callout_cost: float = Field(ge=0)
    currency: str = Field(default="EUR", max_length=3)
    ambiguous: bool = False
    expected_analysis_seconds: int = Field(default=240, ge=10, le=3600)
    archive_seed_clips: List[SeedClip] = Field(default_factory=list)


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_number: str = Field(pattern=ID)
    description: str = Field(min_length=1, max_length=200)
    on_hand_local: int = Field(ge=0)
    on_hand_regional: int = Field(ge=0)
    regional_site: str = Field(default="", max_length=100)
    regional_transit_days: int = Field(default=1, ge=0)
    oem_lead_days: int = Field(ge=0)


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ID)
    content_type: str = Field(max_length=40)
    file: str = Field(pattern=FILE)
    sha256: Optional[str] = None


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_id: str = Field(pattern=SLUG)
    display_name: str = Field(min_length=1, max_length=100)
    asset_class: str = Field(default="", max_length=100)
    scenario: str = Field(default="", max_length=300)
    knowledge_collection: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    clips_dir: str = "clips"
    corpus_dir: str = "corpus"
    fleet: List[Asset] = Field(min_length=1)
    incidents: List[PackIncident] = Field(default_factory=list)
    parts: List[Part] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> "PackManifest":
        asset_ids = [a.asset_id for a in self.fleet]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("duplicate asset_id in fleet")
        incident_ids = [i.incident_id for i in self.incidents]
        if len(set(incident_ids)) != len(incident_ids):
            raise ValueError("duplicate incident_id")
        for incident in self.incidents:
            if incident.asset_id not in asset_ids:
                raise ValueError(
                    f"incident {incident.incident_id} names unknown asset"
                    f" {incident.asset_id}")
        for skill in self.skills:
            if not re.match(r"^vss-[a-z0-9-]+$", skill):
                raise ValueError(f"invalid skill name {skill!r}")
        return self


class Pack:
    """A loaded pack: manifest plus resolved directories and documents."""

    def __init__(self, root: Path, manifest: PackManifest,
                 documents: List[Document]):
        self.root = root
        self.manifest = manifest
        self.documents = documents
        self.clips_dir = (root / manifest.clips_dir).resolve()
        self.corpus_dir = (root / manifest.corpus_dir).resolve()

    @property
    def pack_id(self) -> str:
        return self.manifest.pack_id

    def asset(self, asset_id: str) -> Optional[Asset]:
        return next((a for a in self.manifest.fleet
                     if a.asset_id == asset_id), None)

    def incident(self, incident_id: str) -> Optional[PackIncident]:
        return next((i for i in self.manifest.incidents
                     if i.incident_id == incident_id), None)

    def declared_clips(self) -> List[str]:
        """Every clip the manifest names — the only files served (§8.1)."""
        names: List[str] = []
        for asset in self.manifest.fleet:
            names.extend(asset.baseline_clips)
            if asset.thumbnail:
                names.append(asset.thumbnail)
        for incident in self.manifest.incidents:
            names.append(incident.clip)
            names.extend(s.clip for s in incident.archive_seed_clips)
        return sorted(set(names))

    def clip_path(self, name: str) -> Optional[Path]:
        if name not in self.declared_clips():
            return None
        path = (self.clips_dir / name).resolve()
        if path.parent != self.clips_dir or not path.is_file():
            return None
        return path

    def document(self, doc_id: str) -> Optional[Document]:
        return next((d for d in self.documents if d.id == doc_id), None)

    def document_path(self, doc_id: str) -> Optional[Path]:
        doc = self.document(doc_id)
        if doc is None:
            return None
        path = (self.corpus_dir / doc.file).resolve()
        if path.parent != self.corpus_dir or not path.is_file():
            return None
        return path

    # -- views --------------------------------------------------------------

    def summary(self) -> Dict:
        m = self.manifest
        return {
            "pack_id": m.pack_id,
            "display_name": m.display_name,
            "asset_class": m.asset_class,
            "scenario": m.scenario,
            "knowledge_collection": m.knowledge_collection,
            "asset_count": len(m.fleet),
            "incident_count": len(m.incidents),
            "skills": list(m.skills),
        }

    def incident_view(self, incident: PackIncident, *,
                      for_agent: bool) -> Dict:
        data = incident.model_dump(mode="json")
        if for_agent:
            data.pop("ambiguous", None)
            data.pop("archive_seed_clips", None)
        return data


def load_pack(root: Path) -> Pack:
    manifest_path = root / "pack.yaml"
    with manifest_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    manifest = PackManifest.model_validate(raw)
    documents: List[Document] = []
    corpus_manifest = (root / manifest.corpus_dir / "manifest.yaml").resolve()
    if corpus_manifest.is_file():
        with corpus_manifest.open("r", encoding="utf-8") as fh:
            corpus = yaml.safe_load(fh) or {}
        documents = [Document.model_validate(d)
                     for d in corpus.get("documents", [])]
    return Pack(root.resolve(), manifest, documents)


def load_packs(packs_dir: Path) -> Dict[str, Pack]:
    """Every ``packs/*/pack.yaml``. A malformed manifest fails start-up
    loudly rather than silently dropping a vertical."""
    packs: Dict[str, Pack] = {}
    if not packs_dir.is_dir():
        return packs
    for manifest in sorted(packs_dir.glob("*/pack.yaml")):
        pack = load_pack(manifest.parent)
        if pack.pack_id != manifest.parent.name:
            raise ValueError(
                f"pack_id {pack.pack_id!r} does not match its directory"
                f" {manifest.parent.name!r}")
        packs[pack.pack_id] = pack
    return packs


SECTION_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def document_sections(text: str) -> List[Dict]:
    """Markdown headings as anchors for the document viewer (§8.2).

    The anchor is the heading's leading section number when there is one
    (``4.2 Bearing temperature limits`` -> ``4.2``), else a slug of the
    heading text. Agents cite ``manual-01#4.2``-style anchors.
    """
    sections: List[Dict] = []
    for index, line in enumerate(text.splitlines()):
        m = SECTION_RE.match(line)
        if not m:
            continue
        title = m.group(2)
        number = re.match(r"^(\d+(?:\.\d+)*)\b", title)
        anchor = (number.group(1) if number else
                  re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"))
        sections.append({"anchor": anchor, "title": title,
                         "level": len(m.group(1)), "line": index})
    return sections
