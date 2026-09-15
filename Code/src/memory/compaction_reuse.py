"""Body-free reusable compaction artifact admission helpers.

This module deliberately does not read artifact bodies or create prompt
candidates.  It converts explicit, body-free compaction artifact references into
``ContextCompactionReuseAdmission`` shadow evidence for ``MemoryContextBuilder``.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from memory.compaction_summary import source_candidate_binding_hash
from memory.context_assembly.assembler import ContextAssembler
from metadata import (
    ContextAssemblyPolicy,
    ContextAssemblyStatus,
    ContextCandidate,
    ContextCandidateFreshness,
    ContextCandidateKind,
    ContextCandidateRetention,
    ContextCandidateTrust,
    ContextCandidateTruncation,
    ContextCompactionBinding,
    ContextCompactionReuseAdmission,
    ContextCompactionReuseAdmissionStatus,
    ContextCompactionReuseRejectionReason,
    RuntimePromptContextSnapshot,
)


_ZERO_HASH = "sha256:" + "0" * 64
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMPACTION_ALGORITHMS = frozenset(
    {
        "deterministic_dialog_extract_v1",
        "deterministic_observation_mask_v1",
        "llm_rolling_summary_v1",
    }
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_candidate_ids_key(candidate_ids: Sequence[str]) -> str:
    """Canonical body-free key shared by builder and admission payloads."""

    return json.dumps(list(candidate_ids), ensure_ascii=False, separators=(",", ":"))


class ReusableCompactionArtifactCandidate(BaseModel):
    """Runtime-only, body-free view of a reusable compaction artifact."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    candidate_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_kind: str = Field(min_length=1)
    artifact_integrity_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_artifact_integrity_checksum: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    record_compaction_id: str = Field(min_length=1)
    record_algorithm: str = Field(min_length=1)
    source_candidate_ids: list[str] = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_binding_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    required_candidate_ids: list[str] = Field(default_factory=list)
    recent_suffix_ids: list[str] = Field(default_factory=list)
    session_constraints_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    generated_summary_fingerprint: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @classmethod
    def from_binding(
        cls,
        binding: ContextCompactionBinding,
        *,
        source_binding_hash: str | None = None,
        candidate_id: str | None = None,
        required_candidate_ids: Sequence[str] = (),
        recent_suffix_ids: Sequence[str] = (),
        session_constraints_hash: str | None = None,
        expected_artifact_integrity_checksum: str | None = None,
    ) -> "ReusableCompactionArtifactCandidate":
        """Create a body-free candidate from an existing compaction binding."""

        effective_source_binding_hash = source_binding_hash or binding.source_binding_hash
        if not effective_source_binding_hash:
            raise ValueError("source binding hash is required for reusable compaction")
        return cls(
            candidate_id=candidate_id or f"reuse:{binding.artifact.artifact_id}",
            artifact_id=binding.artifact.artifact_id,
            artifact_kind=binding.artifact.kind,
            artifact_integrity_checksum=binding.artifact.integrity_checksum,
            expected_artifact_integrity_checksum=expected_artifact_integrity_checksum,
            record_compaction_id=binding.record.compaction_id,
            record_algorithm=binding.record.algorithm,
            source_candidate_ids=list(binding.record.source_candidate_ids),
            source_fingerprint=binding.record.source_fingerprint,
            source_binding_hash=effective_source_binding_hash,
            required_candidate_ids=list(required_candidate_ids),
            recent_suffix_ids=list(recent_suffix_ids),
            session_constraints_hash=session_constraints_hash,
            generated_summary_fingerprint=_sha256_text(binding.record.summary),
        )

    @model_validator(mode="after")
    def _candidate_is_unique(self) -> "ReusableCompactionArtifactCandidate":
        if self.record_algorithm not in _COMPACTION_ALGORITHMS:
            raise ValueError("reusable compaction record algorithm is not supported")
        for label, values in (
            ("source candidate IDs", self.source_candidate_ids),
            ("required candidate IDs", self.required_candidate_ids),
            ("recent suffix IDs", self.recent_suffix_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"reusable compaction {label} must be unique")
        return self


class ReusableCompactionSemanticFact(BaseModel):
    """One deterministic semantic fact required before reusable prompt use."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    fact_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_candidate_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _fact_is_bounded(self) -> "ReusableCompactionSemanticFact":
        if not " ".join(self.text.split()):
            raise ValueError("semantic fact text cannot be empty")
        if len(self.evidence_candidate_ids) != len(set(self.evidence_candidate_ids)):
            raise ValueError("semantic fact evidence IDs must be unique")
        return self


class ReusableCompactionPromptUsePreflightStatus(str, Enum):
    """Dry-run status for a reusable compaction prompt-use transition."""

    PASSED = "passed"
    REJECTED = "rejected"


class ReusableCompactionPromptUseRejectionReason(str, Enum):
    """Typed fail-closed reasons for reusable prompt-use preflight."""

    ADMISSION_NOT_ADMITTED = "admission_not_admitted"
    ADMISSION_BINDING_MISMATCH = "admission_binding_mismatch"
    ARTIFACT_KIND_MISMATCH = "artifact_kind_mismatch"
    ARTIFACT_INTEGRITY_MISMATCH = "artifact_integrity_mismatch"
    SOURCE_BINDING_HASH_MISSING = "source_binding_hash_missing"
    SOURCE_CANDIDATE_IDS_MISMATCH = "source_candidate_ids_mismatch"
    SOURCE_BINDING_HASH_MISMATCH = "source_binding_hash_mismatch"
    REQUIRED_CANDIDATE_OMITTED = "required_candidate_omitted"
    RECENT_SUFFIX_OMITTED = "recent_suffix_omitted"
    SEMANTIC_FACTS_MISSING = "semantic_facts_missing"
    SEMANTIC_EVIDENCE_MISMATCH = "semantic_evidence_mismatch"
    SEMANTIC_FACT_MISSING = "semantic_fact_missing"
    TRIAL_ASSEMBLY_NOT_READY = "trial_assembly_not_ready"
    TRIAL_SUMMARY_NOT_SELECTED = "trial_summary_not_selected"
    TRIAL_SOURCE_NOT_GOVERNED = "trial_source_not_governed"
    TRIAL_REQUIRED_CANDIDATE_OMITTED = "trial_required_candidate_omitted"
    TRIAL_RECENT_SUFFIX_OMITTED = "trial_recent_suffix_omitted"


class ReusableCompactionPromptUsePreflight(BaseModel):
    """Body-free dry-run evidence before any reusable summary enters a prompt."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True, validate_assignment=True)

    preflight_id: str = Field(min_length=1)
    status: ReusableCompactionPromptUsePreflightStatus
    rejection_reasons: list[ReusableCompactionPromptUseRejectionReason] = Field(
        default_factory=list
    )
    source_candidate_ids: list[str] = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_binding_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    required_candidate_ids: list[str] = Field(default_factory=list)
    recent_suffix_ids: list[str] = Field(default_factory=list)
    semantic_fact_ids: list[str] = Field(default_factory=list)
    semantic_evidence_candidate_ids: list[str] = Field(default_factory=list)
    semantic_facts_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    session_constraints_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    artifact_id: str = Field(min_length=1)
    artifact_kind: str = Field(min_length=1)
    artifact_integrity_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    generated_summary_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trial_summary_candidate_id: str = Field(min_length=1)
    trial_assembly_status: str | None = None
    trial_selected_candidate_ids: list[str] = Field(default_factory=list)
    trial_replaced_source_candidate_ids: list[str] = Field(default_factory=list)
    trial_prompt_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    trial_final_prompt_chars: int | None = Field(default=None, ge=0)
    used_in_prompt: bool = False

    @model_validator(mode="after")
    def _preflight_is_consistent(self) -> "ReusableCompactionPromptUsePreflight":
        if len(self.rejection_reasons) != len(set(self.rejection_reasons)):
            raise ValueError("preflight rejection reasons must be unique")
        if len(self.source_candidate_ids) != len(set(self.source_candidate_ids)):
            raise ValueError("preflight source candidate IDs must be unique")
        if len(self.required_candidate_ids) != len(set(self.required_candidate_ids)):
            raise ValueError("preflight required candidate IDs must be unique")
        if len(self.recent_suffix_ids) != len(set(self.recent_suffix_ids)):
            raise ValueError("preflight recent suffix IDs must be unique")
        if len(self.semantic_fact_ids) != len(set(self.semantic_fact_ids)):
            raise ValueError("preflight semantic fact IDs must be unique")
        if len(self.semantic_evidence_candidate_ids) != len(
            set(self.semantic_evidence_candidate_ids)
        ):
            raise ValueError("preflight semantic evidence IDs must be unique")
        if self.status == ReusableCompactionPromptUsePreflightStatus.PASSED:
            if self.rejection_reasons:
                raise ValueError("passed preflight cannot carry rejection reasons")
            if not self.semantic_fact_ids or not self.semantic_evidence_candidate_ids:
                raise ValueError("passed preflight requires semantic evidence")
            if not set(self.semantic_evidence_candidate_ids).issubset(
                set(self.source_candidate_ids)
            ):
                raise ValueError("passed preflight semantic evidence must reference sources")
            if set(self.trial_replaced_source_candidate_ids) != set(self.source_candidate_ids):
                raise ValueError("passed preflight must replace every source candidate")
        elif not self.rejection_reasons:
            raise ValueError("rejected preflight requires a rejection reason")
        if self.used_in_prompt:
            raise ValueError("preflight is dry-run only and cannot enter the prompt")
        return self


class ReusableCompactionPromptUseSimulationStatus(str, Enum):
    """Default-off simulation status for a reusable compaction prompt projection."""

    PASSED = "passed"
    REJECTED = "rejected"


class ReusableCompactionPromptUseSimulationRejectionReason(str, Enum):
    """Typed fail-closed reasons for reusable prompt-use simulation."""

    PREFLIGHT_NOT_PASSED = "preflight_not_passed"
    PREFLIGHT_BINDING_MISMATCH = "preflight_binding_mismatch"
    PREFLIGHT_SEMANTIC_EVIDENCE_MISSING = "preflight_semantic_evidence_missing"
    PREFLIGHT_SEMANTIC_EVIDENCE_MISMATCH = "preflight_semantic_evidence_mismatch"
    SOURCE_CANDIDATE_IDS_MISMATCH = "source_candidate_ids_mismatch"
    SOURCE_BINDING_HASH_MISSING = "source_binding_hash_missing"
    SOURCE_BINDING_HASH_MISMATCH = "source_binding_hash_mismatch"
    RAW_ASSEMBLY_NOT_READY = "raw_assembly_not_ready"
    RAW_SOURCE_NOT_SELECTED = "raw_source_not_selected"
    REUSABLE_ASSEMBLY_NOT_READY = "reusable_assembly_not_ready"
    SUMMARY_NOT_SELECTED = "summary_not_selected"
    SOURCE_REPLACEMENT_MISMATCH = "source_replacement_mismatch"
    REQUIRED_CANDIDATE_OMITTED = "required_candidate_omitted"
    RECENT_SUFFIX_OMITTED = "recent_suffix_omitted"
    NO_PROMPT_REDUCTION = "no_prompt_reduction"
    TOKEN_ACCOUNTING_UNAVAILABLE = "token_accounting_unavailable"
    NO_TOKEN_REDUCTION = "no_token_reduction"


class ReusableCompactionPromptUseSimulation(BaseModel):
    """Body-free result comparing raw assembly with reusable compaction assembly."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True, validate_assignment=True)

    simulation_id: str = Field(min_length=1)
    status: ReusableCompactionPromptUseSimulationStatus
    rejection_reasons: list[ReusableCompactionPromptUseSimulationRejectionReason] = Field(
        default_factory=list
    )
    preflight_id: str = Field(min_length=1)
    source_candidate_ids: list[str] = Field(min_length=1)
    source_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_binding_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    required_candidate_ids: list[str] = Field(default_factory=list)
    recent_suffix_ids: list[str] = Field(default_factory=list)
    semantic_fact_ids: list[str] = Field(default_factory=list)
    semantic_evidence_candidate_ids: list[str] = Field(default_factory=list)
    semantic_facts_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    session_constraints_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    artifact_id: str = Field(min_length=1)
    artifact_kind: str = Field(min_length=1)
    artifact_integrity_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    generated_summary_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    summary_candidate_id: str = Field(min_length=1)
    raw_assembly_status: str | None = None
    reusable_assembly_status: str | None = None
    raw_prompt_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    reusable_prompt_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    raw_final_prompt_chars: int | None = Field(default=None, ge=0)
    reusable_final_prompt_chars: int | None = Field(default=None, ge=0)
    prompt_char_delta: int | None = None
    raw_final_prompt_tokens: int | None = Field(default=None, ge=0)
    reusable_final_prompt_tokens: int | None = Field(default=None, ge=0)
    prompt_token_delta: int | None = None
    token_count_method: str | None = None
    tokenizer_id: str | None = None
    token_model: str | None = None
    raw_selected_candidate_ids: list[str] = Field(default_factory=list)
    reusable_selected_candidate_ids: list[str] = Field(default_factory=list)
    replaced_source_candidate_ids: list[str] = Field(default_factory=list)
    retained_required_candidate_ids: list[str] = Field(default_factory=list)
    retained_recent_suffix_ids: list[str] = Field(default_factory=list)
    used_in_prompt: bool = False

    @model_validator(mode="after")
    def _simulation_is_consistent(self) -> "ReusableCompactionPromptUseSimulation":
        if len(self.rejection_reasons) != len(set(self.rejection_reasons)):
            raise ValueError("simulation rejection reasons must be unique")
        for label, values in (
            ("source candidate IDs", self.source_candidate_ids),
            ("required candidate IDs", self.required_candidate_ids),
            ("recent suffix IDs", self.recent_suffix_ids),
            ("semantic fact IDs", self.semantic_fact_ids),
            ("semantic evidence candidate IDs", self.semantic_evidence_candidate_ids),
            ("raw selected candidate IDs", self.raw_selected_candidate_ids),
            ("reusable selected candidate IDs", self.reusable_selected_candidate_ids),
            ("replaced source candidate IDs", self.replaced_source_candidate_ids),
            ("retained required candidate IDs", self.retained_required_candidate_ids),
            ("retained recent suffix IDs", self.retained_recent_suffix_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"simulation {label} must be unique")
        if self.status == ReusableCompactionPromptUseSimulationStatus.PASSED:
            if self.rejection_reasons:
                raise ValueError("passed simulation cannot carry rejection reasons")
            if not self.semantic_fact_ids or not self.semantic_evidence_candidate_ids:
                raise ValueError("passed simulation requires semantic evidence")
            if not set(self.semantic_evidence_candidate_ids).issubset(
                set(self.source_candidate_ids)
            ):
                raise ValueError("passed simulation semantic evidence must reference sources")
            if set(self.replaced_source_candidate_ids) != set(self.source_candidate_ids):
                raise ValueError("passed simulation must replace every source candidate")
            if set(self.retained_required_candidate_ids) != set(self.required_candidate_ids):
                raise ValueError("passed simulation must retain every required candidate")
            if set(self.retained_recent_suffix_ids) != set(self.recent_suffix_ids):
                raise ValueError("passed simulation must retain every recent suffix candidate")
            if self.prompt_char_delta is None or self.prompt_char_delta <= 0:
                raise ValueError("passed simulation requires positive prompt char reduction")
            token_fields = (
                self.raw_final_prompt_tokens,
                self.reusable_final_prompt_tokens,
                self.prompt_token_delta,
            )
            if any(value is not None for value in token_fields):
                if any(value is None for value in token_fields):
                    raise ValueError("token-aware simulation evidence must be complete")
                if self.prompt_token_delta <= 0:
                    raise ValueError("passed token-aware simulation requires positive token reduction")
                if not self.token_count_method or not self.tokenizer_id or not self.token_model:
                    raise ValueError("token-aware simulation requires tokenizer metadata")
            if not self.raw_prompt_hash or not self.reusable_prompt_hash:
                raise ValueError("passed simulation requires prompt hashes")
        elif not self.rejection_reasons:
            raise ValueError("rejected simulation requires a rejection reason")
        if self.used_in_prompt:
            raise ValueError("simulation is default-off and cannot mark prompt use")
        return self


def source_binding_hash_from_shadow_payload(
    shadow_payload: Mapping[str, Any],
    source_candidate_ids: Sequence[str],
) -> str | None:
    """Hash the current body-free source view for the candidate's sources."""

    source_ids = list(source_candidate_ids)
    digests = shadow_payload.get("candidate_digests")
    if not isinstance(digests, Sequence) or isinstance(digests, (str, bytes)):
        return None
    by_id = {
        str(item.get("candidate_id")): item
        for item in digests
        if isinstance(item, Mapping) and item.get("candidate_id") is not None
    }
    if set(source_ids) - set(by_id):
        return None
    ordered = []
    for source_id in source_ids:
        item = by_id[source_id]
        ordered.append(
            {
                "candidate_id": source_id,
                "kind": item.get("kind"),
                "source_id": item.get("source_id"),
                "role": item.get("role"),
                "retention": item.get("retention"),
                "trust": item.get("trust"),
                "freshness": item.get("freshness"),
                "truncation": item.get("truncation"),
                "source_order": item.get("source_order"),
                "content_sha256": item.get("content_sha256"),
            }
        )
    return _canonical_hash(ordered)


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _normalized_semantic_fact_evidence(
    facts: Sequence[ReusableCompactionSemanticFact],
) -> tuple[list[str], list[str], str]:
    """Return the body-free canonical identity for one explicit fact set."""

    ordered_facts = sorted(facts, key=lambda item: item.fact_id)
    fact_ids = [fact.fact_id for fact in ordered_facts]
    evidence_ids = sorted(
        {
            evidence_id
            for fact in ordered_facts
            for evidence_id in fact.evidence_candidate_ids
        }
    )
    facts_hash = _canonical_hash(
        [
            {
                "fact_id": fact.fact_id,
                "text": _normalize_text(fact.text),
                "evidence_candidate_ids": sorted(fact.evidence_candidate_ids),
            }
            for fact in ordered_facts
        ]
    )
    return fact_ids, evidence_ids, facts_hash


def _candidate_digest(candidate: ContextCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "kind": str(getattr(candidate.kind, "value", candidate.kind)),
        "source_id": candidate.source_id,
        "role": candidate.role,
        "retention": str(getattr(candidate.retention, "value", candidate.retention)),
        "trust": str(getattr(candidate.trust, "value", candidate.trust)),
        "freshness": str(getattr(candidate.freshness, "value", candidate.freshness)),
        "truncation": str(getattr(candidate.truncation, "value", candidate.truncation)),
        "source_order": candidate.source_order,
        "content_sha256": _sha256_text(candidate.content),
    }


def admit_reusable_compaction_candidate(
    candidate: ReusableCompactionArtifactCandidate,
    shadow_payload: Mapping[str, Any],
    *,
    admission_id: str | None = None,
) -> ContextCompactionReuseAdmission:
    """Return one shadow admission or typed rejection for the current context."""

    reason: ContextCompactionReuseRejectionReason | None = None
    selected_ids = {
        str(item)
        for item in shadow_payload.get("selected_candidate_ids", [])
        if isinstance(item, str)
    }
    current_source_binding_hash = source_binding_hash_from_shadow_payload(
        shadow_payload,
        candidate.source_candidate_ids,
    )
    if candidate.artifact_kind != "context_compaction":
        reason = ContextCompactionReuseRejectionReason.ARTIFACT_KIND_MISMATCH
    elif (
        candidate.expected_artifact_integrity_checksum is not None
        and candidate.expected_artifact_integrity_checksum != candidate.artifact_integrity_checksum
    ):
        reason = ContextCompactionReuseRejectionReason.ARTIFACT_INTEGRITY_MISMATCH
    elif current_source_binding_hash is None:
        reason = ContextCompactionReuseRejectionReason.SOURCE_CANDIDATE_IDS_MISMATCH
    elif current_source_binding_hash != candidate.source_binding_hash:
        reason = ContextCompactionReuseRejectionReason.SOURCE_BINDING_HASH_MISMATCH
    else:
        source_fingerprints = shadow_payload.get("source_fingerprint_by_candidate_ids")
        expected_source_fingerprint = (
            str(source_fingerprints.get(_source_candidate_ids_key(candidate.source_candidate_ids)) or "")
            if isinstance(source_fingerprints, Mapping)
            else ""
        )
        if expected_source_fingerprint != candidate.source_fingerprint:
            reason = ContextCompactionReuseRejectionReason.SOURCE_FINGERPRINT_MISMATCH
    if reason is None and not set(candidate.required_candidate_ids).issubset(selected_ids):
        reason = ContextCompactionReuseRejectionReason.REQUIRED_CANDIDATE_IDS_MISMATCH
    elif reason is None and not set(candidate.recent_suffix_ids).issubset(selected_ids):
        reason = ContextCompactionReuseRejectionReason.RECENT_SUFFIX_IDS_MISMATCH
    current_constraints_hash = str(shadow_payload.get("session_constraints_hash") or "")
    candidate_constraints_hash = str(candidate.session_constraints_hash or "")
    if reason is None and candidate_constraints_hash != current_constraints_hash:
        reason = ContextCompactionReuseRejectionReason.SESSION_CONSTRAINTS_HASH_MISMATCH

    status = (
        ContextCompactionReuseAdmissionStatus.REJECTED
        if reason is not None
        else ContextCompactionReuseAdmissionStatus.ADMITTED
    )
    return ContextCompactionReuseAdmission(
        admission_id=admission_id or f"reuse:{candidate.candidate_id}",
        status=status,
        rejection_reason=reason,
        source_candidate_ids=list(candidate.source_candidate_ids),
        source_fingerprint=candidate.source_fingerprint,
        source_binding_hash=candidate.source_binding_hash,
        required_candidate_ids=list(candidate.required_candidate_ids),
        recent_suffix_ids=list(candidate.recent_suffix_ids),
        session_constraints_hash=candidate.session_constraints_hash,
        artifact_id=candidate.artifact_id,
        artifact_kind=candidate.artifact_kind,
        artifact_integrity_checksum=candidate.artifact_integrity_checksum,
        generated_summary_fingerprint=candidate.generated_summary_fingerprint,
        used_in_prompt=False,
    )


def preflight_reusable_compaction_prompt_use(
    *,
    binding: ContextCompactionBinding | Mapping[str, Any],
    candidates: Sequence[ContextCandidate | Mapping[str, Any]],
    policy: ContextAssemblyPolicy | Mapping[str, Any],
    renderer: Callable[[list[ContextCandidate]], str],
    admission: ContextCompactionReuseAdmission | Mapping[str, Any] | None = None,
    semantic_facts: Sequence[ReusableCompactionSemanticFact | Mapping[str, Any]] = (),
    required_candidate_ids: Sequence[str] = (),
    recent_suffix_ids: Sequence[str] = (),
    session_constraints_hash: str | None = None,
    expected_artifact_integrity_checksum: str | None = None,
    preflight_id: str | None = None,
    summary_candidate_id: str | None = None,
    token_counter: Any | None = None,
) -> ReusableCompactionPromptUsePreflight:
    """Dry-run whether a reusable compaction may safely enter a future prompt."""

    validated_binding = (
        binding
        if isinstance(binding, ContextCompactionBinding)
        else ContextCompactionBinding.model_validate(binding)
    )
    validated_candidates = [
        item
        if isinstance(item, ContextCandidate)
        else ContextCandidate.model_validate(item)
        for item in candidates
    ]
    validated_policy = (
        policy
        if isinstance(policy, ContextAssemblyPolicy)
        else ContextAssemblyPolicy.model_validate(policy)
    )
    facts = [
        item
        if isinstance(item, ReusableCompactionSemanticFact)
        else ReusableCompactionSemanticFact.model_validate(item)
        for item in semantic_facts
    ]
    required_ids = list(required_candidate_ids)
    recent_ids = list(recent_suffix_ids)
    reasons: list[ReusableCompactionPromptUseRejectionReason] = []

    def add_reason(reason: ReusableCompactionPromptUseRejectionReason) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if len(required_ids) != len(set(required_ids)):
        add_reason(ReusableCompactionPromptUseRejectionReason.REQUIRED_CANDIDATE_OMITTED)
    if len(recent_ids) != len(set(recent_ids)):
        add_reason(ReusableCompactionPromptUseRejectionReason.RECENT_SUFFIX_OMITTED)
    if validated_binding.artifact.kind != "context_compaction":
        add_reason(ReusableCompactionPromptUseRejectionReason.ARTIFACT_KIND_MISMATCH)
    if (
        expected_artifact_integrity_checksum is not None
        and expected_artifact_integrity_checksum
        != validated_binding.artifact.integrity_checksum
    ):
        add_reason(ReusableCompactionPromptUseRejectionReason.ARTIFACT_INTEGRITY_MISMATCH)
    if not validated_binding.source_binding_hash:
        add_reason(ReusableCompactionPromptUseRejectionReason.SOURCE_BINDING_HASH_MISSING)

    admission_value: ContextCompactionReuseAdmission | None = None
    if admission is not None:
        admission_value = (
            admission
            if isinstance(admission, ContextCompactionReuseAdmission)
            else ContextCompactionReuseAdmission.model_validate(admission)
        )
        if admission_value.status != ContextCompactionReuseAdmissionStatus.ADMITTED:
            add_reason(ReusableCompactionPromptUseRejectionReason.ADMISSION_NOT_ADMITTED)
        if (
            admission_value.artifact_id != validated_binding.artifact.artifact_id
            or admission_value.artifact_integrity_checksum
            != validated_binding.artifact.integrity_checksum
            or admission_value.source_candidate_ids
            != validated_binding.record.source_candidate_ids
            or admission_value.source_fingerprint
            != validated_binding.record.source_fingerprint
            or admission_value.source_binding_hash
            != validated_binding.source_binding_hash
            or admission_value.required_candidate_ids != required_ids
            or admission_value.recent_suffix_ids != recent_ids
            or admission_value.session_constraints_hash != session_constraints_hash
            or admission_value.generated_summary_fingerprint
            != _sha256_text(validated_binding.record.summary)
        ):
            add_reason(ReusableCompactionPromptUseRejectionReason.ADMISSION_BINDING_MISMATCH)
    else:
        add_reason(ReusableCompactionPromptUseRejectionReason.ADMISSION_NOT_ADMITTED)

    by_id = {candidate.candidate_id: candidate for candidate in validated_candidates}
    source_ids = list(validated_binding.record.source_candidate_ids)
    source_candidates = [by_id[source_id] for source_id in source_ids if source_id in by_id]
    if len(source_candidates) != len(source_ids):
        add_reason(ReusableCompactionPromptUseRejectionReason.SOURCE_CANDIDATE_IDS_MISMATCH)
    elif validated_binding.source_binding_hash and (
        source_candidate_binding_hash(source_candidates)
        != validated_binding.source_binding_hash
    ):
        add_reason(ReusableCompactionPromptUseRejectionReason.SOURCE_BINDING_HASH_MISMATCH)

    candidate_ids = set(by_id)
    if not set(required_ids).issubset(candidate_ids):
        add_reason(ReusableCompactionPromptUseRejectionReason.REQUIRED_CANDIDATE_OMITTED)
    if not set(recent_ids).issubset(candidate_ids) or set(recent_ids).intersection(source_ids):
        add_reason(ReusableCompactionPromptUseRejectionReason.RECENT_SUFFIX_OMITTED)
    if not facts:
        add_reason(ReusableCompactionPromptUseRejectionReason.SEMANTIC_FACTS_MISSING)
    summary_text = _normalize_text(validated_binding.record.summary)
    for fact in facts:
        if not set(fact.evidence_candidate_ids).issubset(set(source_ids)):
            add_reason(ReusableCompactionPromptUseRejectionReason.SEMANTIC_EVIDENCE_MISMATCH)
        if _normalize_text(fact.text) not in summary_text:
            add_reason(ReusableCompactionPromptUseRejectionReason.SEMANTIC_FACT_MISSING)
    semantic_fact_ids, semantic_evidence_ids, semantic_facts_hash = (
        _normalized_semantic_fact_evidence(facts)
    )

    trial_selected_ids: list[str] = []
    trial_replaced_ids: list[str] = []
    trial_status: str | None = None
    trial_prompt_hash: str | None = None
    trial_chars: int | None = None
    summary_id = summary_candidate_id or f"reuse-compaction:{validated_binding.record.compaction_id}"
    if len(source_candidates) == len(source_ids):
        summary_candidate = ContextCandidate(
            candidate_id=summary_id,
            kind=ContextCandidateKind.ARTIFACT,
            source_id=validated_binding.record.source_fingerprint,
            content=validated_binding.record.summary,
            retention=ContextCandidateRetention.PREFERRED,
            priority=99,
            source_order=500,
            truncation=ContextCandidateTruncation.FORBIDDEN,
            trust=ContextCandidateTrust.DERIVED,
            freshness=ContextCandidateFreshness.CURRENT,
            compacted_candidate_ids=source_ids,
        )
        try:
            trial = _assemble_reusable_trial(
                candidates=validated_candidates,
                summary_candidate=summary_candidate,
                source_candidate_ids=source_ids,
                required_candidate_ids=required_ids,
                recent_suffix_ids=recent_ids,
                policy=validated_policy,
                renderer=renderer,
                token_counter=token_counter,
            )
            trial_status = trial.assembly_status
            trial_selected_ids = trial.selected_candidate_ids
            trial_prompt_hash = trial.prompt_hash
            trial_chars = trial.prompt_chars
            if trial.assembly_status != ContextAssemblyStatus.READY.value:
                add_reason(ReusableCompactionPromptUseRejectionReason.TRIAL_ASSEMBLY_NOT_READY)
            if not trial.summary_selected:
                add_reason(ReusableCompactionPromptUseRejectionReason.TRIAL_SUMMARY_NOT_SELECTED)
            trial_replaced_ids = trial.replaced_source_candidate_ids
            if not trial.source_complete:
                add_reason(ReusableCompactionPromptUseRejectionReason.TRIAL_SOURCE_NOT_GOVERNED)
            if not trial.required_complete:
                add_reason(ReusableCompactionPromptUseRejectionReason.TRIAL_REQUIRED_CANDIDATE_OMITTED)
            if not trial.recent_complete:
                add_reason(ReusableCompactionPromptUseRejectionReason.TRIAL_RECENT_SUFFIX_OMITTED)
        except Exception:
            add_reason(ReusableCompactionPromptUseRejectionReason.TRIAL_ASSEMBLY_NOT_READY)

    status = (
        ReusableCompactionPromptUsePreflightStatus.REJECTED
        if reasons
        else ReusableCompactionPromptUsePreflightStatus.PASSED
    )
    return ReusableCompactionPromptUsePreflight(
        preflight_id=preflight_id or f"preflight:{validated_binding.record.compaction_id}",
        status=status,
        rejection_reasons=reasons,
        source_candidate_ids=source_ids,
        source_fingerprint=validated_binding.record.source_fingerprint,
        source_binding_hash=validated_binding.source_binding_hash or _ZERO_HASH,
        required_candidate_ids=required_ids,
        recent_suffix_ids=recent_ids,
        semantic_fact_ids=semantic_fact_ids,
        semantic_evidence_candidate_ids=semantic_evidence_ids,
        semantic_facts_hash=semantic_facts_hash,
        session_constraints_hash=session_constraints_hash,
        artifact_id=validated_binding.artifact.artifact_id,
        artifact_kind=validated_binding.artifact.kind,
        artifact_integrity_checksum=validated_binding.artifact.integrity_checksum,
        generated_summary_fingerprint=_sha256_text(validated_binding.record.summary),
        trial_summary_candidate_id=summary_id,
        trial_assembly_status=trial_status,
        trial_selected_candidate_ids=trial_selected_ids,
        trial_replaced_source_candidate_ids=trial_replaced_ids,
        trial_prompt_hash=trial_prompt_hash,
        trial_final_prompt_chars=trial_chars,
        used_in_prompt=False,
    )


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _assembly_status_value(value: Any) -> str:
    return _enum_value(value)


def _selected_candidate_ids(result: Any) -> list[str]:
    return [candidate.candidate_id for candidate in result.selected_candidates]


class _ReusableTrialEvidence(BaseModel):
    """Neutral, typed evidence for one reusable-summary assembly trial."""

    model_config = ConfigDict(extra="forbid")

    assembly_status: str
    prompt_hash: str
    prompt_chars: int
    prompt_tokens: int | None = None
    token_count_method: str | None = None
    tokenizer_id: str | None = None
    token_model: str | None = None
    selected_candidate_ids: list[str] = Field(default_factory=list)
    replaced_source_candidate_ids: list[str] = Field(default_factory=list)
    retained_required_candidate_ids: list[str] = Field(default_factory=list)
    retained_recent_suffix_ids: list[str] = Field(default_factory=list)
    summary_selected: bool = False
    source_complete: bool = False
    required_complete: bool = False
    recent_complete: bool = False


def _assemble_reusable_trial(
    *,
    candidates: Sequence[ContextCandidate],
    summary_candidate: ContextCandidate,
    source_candidate_ids: Sequence[str],
    required_candidate_ids: Sequence[str],
    recent_suffix_ids: Sequence[str],
    policy: ContextAssemblyPolicy,
    renderer: Callable[[list[ContextCandidate]], str],
    token_counter: Any | None,
) -> _ReusableTrialEvidence:
    """Assemble and classify the shared reusable-summary trial once."""

    trial = ContextAssembler(
        renderer=lambda _payload: "",
        token_counter=token_counter,
    ).assemble_candidates(
        [*candidates, summary_candidate],
        policy=policy,
        renderer=renderer,
    )
    decision_by_id = {
        decision.candidate_id: decision
        for decision in trial.selection.candidate_decisions
    }
    summary_decision = decision_by_id.get(summary_candidate.candidate_id)
    replaced_source_ids: list[str] = []
    for source_id in source_candidate_ids:
        decision = decision_by_id.get(source_id)
        if (
            decision is not None
            and decision.action == "omitted"
            and decision.reason == "compacted"
            and decision.governed_by_candidate_id == summary_candidate.candidate_id
        ):
            replaced_source_ids.append(source_id)
    retained_required_ids = [
        candidate_id
        for candidate_id in required_candidate_ids
        if (decision_by_id.get(candidate_id) is not None
            and decision_by_id[candidate_id].action == "kept")
    ]
    retained_recent_ids = [
        candidate_id
        for candidate_id in recent_suffix_ids
        if (decision_by_id.get(candidate_id) is not None
            and decision_by_id[candidate_id].action == "kept")
    ]
    return _ReusableTrialEvidence(
        assembly_status=_assembly_status_value(trial.selection.assembly_status),
        prompt_hash=_sha256_text(trial.prompt_text),
        prompt_chars=len(trial.prompt_text),
        prompt_tokens=trial.selection.final_prompt_tokens,
        token_count_method=(
            trial.selection.token_count_method
            if trial.selection.budget_unit == "tokens"
            else None
        ),
        tokenizer_id=(
            trial.selection.tokenizer_id
            if trial.selection.budget_unit == "tokens"
            else None
        ),
        token_model=(
            trial.selection.model
            if trial.selection.budget_unit == "tokens"
            else None
        ),
        selected_candidate_ids=_selected_candidate_ids(trial),
        replaced_source_candidate_ids=replaced_source_ids,
        retained_required_candidate_ids=retained_required_ids,
        retained_recent_suffix_ids=retained_recent_ids,
        summary_selected=(summary_decision is not None and summary_decision.action == "kept"),
        source_complete=(len(replaced_source_ids) == len(source_candidate_ids)),
        required_complete=(len(retained_required_ids) == len(required_candidate_ids)),
        recent_complete=(len(retained_recent_ids) == len(recent_suffix_ids)),
    )


def simulate_reusable_compaction_prompt_use(
    *,
    binding: ContextCompactionBinding | Mapping[str, Any],
    candidates: Sequence[ContextCandidate | Mapping[str, Any]],
    policy: ContextAssemblyPolicy | Mapping[str, Any],
    renderer: Callable[[list[ContextCandidate]], str],
    preflight: ReusableCompactionPromptUsePreflight | Mapping[str, Any],
    admission: ContextCompactionReuseAdmission | Mapping[str, Any],
    semantic_facts: Sequence[ReusableCompactionSemanticFact | Mapping[str, Any]],
    simulation_id: str | None = None,
    summary_candidate_id: str | None = None,
    token_counter: Any | None = None,
) -> ReusableCompactionPromptUseSimulation:
    """Compare raw prompt assembly against a preflight-passed reusable projection.

    This helper is intentionally default-off and body-free: it reads only the
    already-present binding summary needed to construct an in-memory projection,
    returns hashes/sizes/IDs, and never mutates ``MemoryContextBuilder`` output
    or flips ``ContextCompactionReuseAdmission.used_in_prompt``.
    """

    validated_binding = (
        binding
        if isinstance(binding, ContextCompactionBinding)
        else ContextCompactionBinding.model_validate(binding)
    )
    validated_candidates = [
        item
        if isinstance(item, ContextCandidate)
        else ContextCandidate.model_validate(item)
        for item in candidates
    ]
    validated_policy = (
        policy
        if isinstance(policy, ContextAssemblyPolicy)
        else ContextAssemblyPolicy.model_validate(policy)
    )
    validated_preflight = (
        preflight
        if isinstance(preflight, ReusableCompactionPromptUsePreflight)
        else ReusableCompactionPromptUsePreflight.model_validate(preflight)
    )
    validated_admission = (
        admission
        if isinstance(admission, ContextCompactionReuseAdmission)
        else ContextCompactionReuseAdmission.model_validate(admission)
    )
    facts = [
        item
        if isinstance(item, ReusableCompactionSemanticFact)
        else ReusableCompactionSemanticFact.model_validate(item)
        for item in semantic_facts
    ]
    source_ids = list(validated_binding.record.source_candidate_ids)
    required_ids = list(validated_admission.required_candidate_ids)
    recent_ids = list(validated_admission.recent_suffix_ids)
    semantic_fact_ids, semantic_evidence_ids, semantic_facts_hash = (
        _normalized_semantic_fact_evidence(facts)
    )
    resolved_summary_id = validated_preflight.trial_summary_candidate_id
    reasons: list[ReusableCompactionPromptUseSimulationRejectionReason] = []

    def add_reason(reason: ReusableCompactionPromptUseSimulationRejectionReason) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if _enum_value(validated_preflight.status) != (
        ReusableCompactionPromptUsePreflightStatus.PASSED.value
    ):
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.PREFLIGHT_NOT_PASSED
        )
    if summary_candidate_id is not None and summary_candidate_id != resolved_summary_id:
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.PREFLIGHT_BINDING_MISMATCH
        )
    if (
        not semantic_fact_ids
        or not semantic_evidence_ids
        or not validated_preflight.semantic_fact_ids
        or not validated_preflight.semantic_evidence_candidate_ids
    ):
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.PREFLIGHT_SEMANTIC_EVIDENCE_MISSING
        )
    summary_text = _normalize_text(validated_binding.record.summary)
    semantic_identity_mismatch = (
        validated_preflight.semantic_fact_ids != semantic_fact_ids
        or validated_preflight.semantic_evidence_candidate_ids != semantic_evidence_ids
        or validated_preflight.semantic_facts_hash != semantic_facts_hash
        or any(
            not set(fact.evidence_candidate_ids).issubset(set(source_ids))
            or _normalize_text(fact.text) not in summary_text
            for fact in facts
        )
    )
    if semantic_identity_mismatch:
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.PREFLIGHT_SEMANTIC_EVIDENCE_MISMATCH
        )
    if validated_admission.status != ContextCompactionReuseAdmissionStatus.ADMITTED:
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.PREFLIGHT_BINDING_MISMATCH
        )
    if (
        validated_preflight.artifact_id != validated_binding.artifact.artifact_id
        or validated_preflight.artifact_kind != validated_binding.artifact.kind
        or validated_preflight.artifact_integrity_checksum
        != validated_binding.artifact.integrity_checksum
        or validated_preflight.source_candidate_ids != source_ids
        or validated_preflight.source_fingerprint
        != validated_binding.record.source_fingerprint
        or validated_preflight.source_binding_hash
        != (validated_binding.source_binding_hash or _ZERO_HASH)
        or validated_preflight.generated_summary_fingerprint
        != _sha256_text(validated_binding.record.summary)
        or validated_admission.artifact_id != validated_binding.artifact.artifact_id
        or validated_admission.artifact_kind != validated_binding.artifact.kind
        or validated_admission.artifact_integrity_checksum
        != validated_binding.artifact.integrity_checksum
        or validated_admission.source_candidate_ids != source_ids
        or validated_admission.source_fingerprint
        != validated_binding.record.source_fingerprint
        or validated_admission.source_binding_hash
        != validated_binding.source_binding_hash
        or validated_admission.required_candidate_ids
        != validated_preflight.required_candidate_ids
        or validated_admission.recent_suffix_ids
        != validated_preflight.recent_suffix_ids
        or validated_admission.session_constraints_hash
        != validated_preflight.session_constraints_hash
        or validated_admission.generated_summary_fingerprint
        != _sha256_text(validated_binding.record.summary)
    ):
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.PREFLIGHT_BINDING_MISMATCH
        )
    if not validated_binding.source_binding_hash:
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.SOURCE_BINDING_HASH_MISSING
        )

    by_id = {candidate.candidate_id: candidate for candidate in validated_candidates}
    source_candidates = [by_id[source_id] for source_id in source_ids if source_id in by_id]
    if len(source_candidates) != len(source_ids):
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.SOURCE_CANDIDATE_IDS_MISMATCH
        )
    elif validated_binding.source_binding_hash and (
        source_candidate_binding_hash(source_candidates)
        != validated_binding.source_binding_hash
    ):
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.SOURCE_BINDING_HASH_MISMATCH
        )

    raw_status: str | None = None
    reusable_status: str | None = None
    raw_prompt_hash: str | None = None
    reusable_prompt_hash: str | None = None
    raw_chars: int | None = None
    reusable_chars: int | None = None
    prompt_char_delta: int | None = None
    raw_tokens: int | None = None
    reusable_tokens: int | None = None
    prompt_token_delta: int | None = None
    token_count_method: str | None = None
    tokenizer_id: str | None = None
    token_model: str | None = None
    raw_selected_ids: list[str] = []
    reusable_selected_ids: list[str] = []
    replaced_ids: list[str] = []
    retained_required_ids: list[str] = []
    retained_recent_ids: list[str] = []
    assembler = ContextAssembler(renderer=lambda _payload: "", token_counter=token_counter)
    token_accounting_requested = (
        token_counter is not None or validated_policy.max_prompt_tokens is not None
    )

    if reasons:
        return ReusableCompactionPromptUseSimulation(
            simulation_id=simulation_id or f"simulation:{validated_binding.record.compaction_id}",
            status=ReusableCompactionPromptUseSimulationStatus.REJECTED,
            rejection_reasons=reasons,
            preflight_id=validated_preflight.preflight_id,
            source_candidate_ids=source_ids,
            source_fingerprint=validated_binding.record.source_fingerprint,
            source_binding_hash=validated_binding.source_binding_hash or _ZERO_HASH,
            required_candidate_ids=required_ids,
            recent_suffix_ids=recent_ids,
            semantic_fact_ids=semantic_fact_ids,
            semantic_evidence_candidate_ids=semantic_evidence_ids,
            semantic_facts_hash=semantic_facts_hash,
            session_constraints_hash=validated_admission.session_constraints_hash,
            artifact_id=validated_binding.artifact.artifact_id,
            artifact_kind=validated_binding.artifact.kind,
            artifact_integrity_checksum=validated_binding.artifact.integrity_checksum,
            generated_summary_fingerprint=_sha256_text(validated_binding.record.summary),
            summary_candidate_id=resolved_summary_id,
            raw_assembly_status=raw_status,
            reusable_assembly_status=reusable_status,
            raw_prompt_hash=raw_prompt_hash,
            reusable_prompt_hash=reusable_prompt_hash,
            raw_final_prompt_chars=raw_chars,
            reusable_final_prompt_chars=reusable_chars,
            prompt_char_delta=prompt_char_delta,
            raw_final_prompt_tokens=raw_tokens,
            reusable_final_prompt_tokens=reusable_tokens,
            prompt_token_delta=prompt_token_delta,
            token_count_method=token_count_method,
            tokenizer_id=tokenizer_id,
            token_model=token_model,
            raw_selected_candidate_ids=raw_selected_ids,
            reusable_selected_candidate_ids=reusable_selected_ids,
            replaced_source_candidate_ids=replaced_ids,
            retained_required_candidate_ids=retained_required_ids,
            retained_recent_suffix_ids=retained_recent_ids,
            used_in_prompt=False,
        )

    try:
        raw = assembler.assemble_candidates(
            list(validated_candidates),
            policy=validated_policy,
            renderer=renderer,
        )
        raw_status = _assembly_status_value(raw.selection.assembly_status)
        raw_prompt_hash = _sha256_text(raw.prompt_text)
        raw_chars = len(raw.prompt_text)
        raw_tokens = raw.selection.final_prompt_tokens
        if raw.selection.budget_unit == "tokens":
            token_count_method = raw.selection.token_count_method
            tokenizer_id = raw.selection.tokenizer_id
            token_model = raw.selection.model
        raw_selected_ids = _selected_candidate_ids(raw)
        raw_decision_by_id = {
            decision.candidate_id: decision
            for decision in raw.selection.candidate_decisions
        }
        if raw.selection.assembly_status != ContextAssemblyStatus.READY:
            add_reason(
                ReusableCompactionPromptUseSimulationRejectionReason.RAW_ASSEMBLY_NOT_READY
            )
        for source_id in source_ids:
            decision = raw_decision_by_id.get(source_id)
            if decision is None or decision.action != "kept":
                add_reason(
                    ReusableCompactionPromptUseSimulationRejectionReason.RAW_SOURCE_NOT_SELECTED
                )
    except Exception:
        add_reason(
            ReusableCompactionPromptUseSimulationRejectionReason.RAW_ASSEMBLY_NOT_READY
        )

    if len(source_candidates) == len(source_ids):
        summary_candidate = ContextCandidate(
            candidate_id=resolved_summary_id,
            kind=ContextCandidateKind.ARTIFACT,
            source_id=validated_binding.record.source_fingerprint,
            content=validated_binding.record.summary,
            retention=ContextCandidateRetention.PREFERRED,
            priority=99,
            source_order=500,
            truncation=ContextCandidateTruncation.FORBIDDEN,
            trust=ContextCandidateTrust.DERIVED,
            freshness=ContextCandidateFreshness.CURRENT,
            compacted_candidate_ids=source_ids,
        )
        try:
            reusable = _assemble_reusable_trial(
                candidates=validated_candidates,
                summary_candidate=summary_candidate,
                source_candidate_ids=source_ids,
                required_candidate_ids=required_ids,
                recent_suffix_ids=recent_ids,
                policy=validated_policy,
                renderer=renderer,
                token_counter=token_counter,
            )
            reusable_status = reusable.assembly_status
            reusable_prompt_hash = reusable.prompt_hash
            reusable_chars = reusable.prompt_chars
            reusable_tokens = reusable.prompt_tokens
            token_count_method = reusable.token_count_method or token_count_method
            tokenizer_id = reusable.tokenizer_id or tokenizer_id
            token_model = reusable.token_model or token_model
            reusable_selected_ids = reusable.selected_candidate_ids
            if raw_chars is not None:
                prompt_char_delta = raw_chars - reusable_chars
            if raw_tokens is not None and reusable_tokens is not None:
                prompt_token_delta = raw_tokens - reusable_tokens
            if reusable.assembly_status != ContextAssemblyStatus.READY.value:
                add_reason(
                    ReusableCompactionPromptUseSimulationRejectionReason.REUSABLE_ASSEMBLY_NOT_READY
                )
            if not reusable.summary_selected:
                add_reason(
                    ReusableCompactionPromptUseSimulationRejectionReason.SUMMARY_NOT_SELECTED
                )
            replaced_ids = reusable.replaced_source_candidate_ids
            retained_required_ids = reusable.retained_required_candidate_ids
            retained_recent_ids = reusable.retained_recent_suffix_ids
            if not reusable.source_complete:
                add_reason(ReusableCompactionPromptUseSimulationRejectionReason.SOURCE_REPLACEMENT_MISMATCH)
            if not reusable.required_complete:
                add_reason(ReusableCompactionPromptUseSimulationRejectionReason.REQUIRED_CANDIDATE_OMITTED)
            if not reusable.recent_complete:
                add_reason(ReusableCompactionPromptUseSimulationRejectionReason.RECENT_SUFFIX_OMITTED)
            if prompt_char_delta is not None and prompt_char_delta <= 0:
                add_reason(
                    ReusableCompactionPromptUseSimulationRejectionReason.NO_PROMPT_REDUCTION
                )
            if token_accounting_requested:
                if raw_tokens is None or reusable_tokens is None:
                    add_reason(
                        ReusableCompactionPromptUseSimulationRejectionReason.TOKEN_ACCOUNTING_UNAVAILABLE
                    )
                elif prompt_token_delta is None or prompt_token_delta <= 0:
                    add_reason(
                        ReusableCompactionPromptUseSimulationRejectionReason.NO_TOKEN_REDUCTION
                    )
        except Exception:
            add_reason(
                ReusableCompactionPromptUseSimulationRejectionReason.REUSABLE_ASSEMBLY_NOT_READY
            )

    status = (
        ReusableCompactionPromptUseSimulationStatus.REJECTED
        if reasons
        else ReusableCompactionPromptUseSimulationStatus.PASSED
    )
    return ReusableCompactionPromptUseSimulation(
        simulation_id=simulation_id or f"simulation:{validated_binding.record.compaction_id}",
        status=status,
        rejection_reasons=reasons,
        preflight_id=validated_preflight.preflight_id,
        source_candidate_ids=source_ids,
        source_fingerprint=validated_binding.record.source_fingerprint,
        source_binding_hash=validated_binding.source_binding_hash or _ZERO_HASH,
        required_candidate_ids=required_ids,
        recent_suffix_ids=recent_ids,
        semantic_fact_ids=semantic_fact_ids,
        semantic_evidence_candidate_ids=semantic_evidence_ids,
        semantic_facts_hash=semantic_facts_hash,
        session_constraints_hash=validated_admission.session_constraints_hash,
        artifact_id=validated_binding.artifact.artifact_id,
        artifact_kind=validated_binding.artifact.kind,
        artifact_integrity_checksum=validated_binding.artifact.integrity_checksum,
        generated_summary_fingerprint=_sha256_text(validated_binding.record.summary),
        summary_candidate_id=resolved_summary_id,
        raw_assembly_status=raw_status,
        reusable_assembly_status=reusable_status,
        raw_prompt_hash=raw_prompt_hash,
        reusable_prompt_hash=reusable_prompt_hash,
        raw_final_prompt_chars=raw_chars,
        reusable_final_prompt_chars=reusable_chars,
        prompt_char_delta=prompt_char_delta,
        raw_final_prompt_tokens=raw_tokens,
        reusable_final_prompt_tokens=reusable_tokens,
        prompt_token_delta=prompt_token_delta,
        token_count_method=token_count_method,
        tokenizer_id=tokenizer_id,
        token_model=token_model,
        raw_selected_candidate_ids=raw_selected_ids,
        reusable_selected_candidate_ids=reusable_selected_ids,
        replaced_source_candidate_ids=replaced_ids,
        retained_required_candidate_ids=retained_required_ids,
        retained_recent_suffix_ids=retained_recent_ids,
        used_in_prompt=False,
    )


def build_compaction_reuse_shadow_provider(
    candidates: Sequence[ReusableCompactionArtifactCandidate | Mapping[str, Any]],
) -> Callable[[dict[str, Any]], list[ContextCompactionReuseAdmission]]:
    """Build a MemoryContextBuilder shadow provider from explicit candidates."""

    frozen_candidates = tuple(
        item
        if isinstance(item, ReusableCompactionArtifactCandidate)
        else ReusableCompactionArtifactCandidate.model_validate(dict(item))
        for item in candidates
    )

    def provider(shadow_payload: dict[str, Any]) -> list[ContextCompactionReuseAdmission]:
        return [
            admit_reusable_compaction_candidate(
                candidate,
                shadow_payload,
                admission_id=f"reuse:{index}:{candidate.candidate_id}",
            )
            for index, candidate in enumerate(frozen_candidates, start=1)
        ]

    return provider


def _bindings_from_checkpoint_source(
    checkpoint_source: (
        RuntimePromptContextSnapshot
        | Sequence[ContextCompactionBinding | Mapping[str, Any]]
        | Mapping[str, Any]
    ),
) -> tuple[ContextCompactionBinding, ...]:
    """Return checkpoint-owned compaction bindings from a snapshot or list."""

    if isinstance(checkpoint_source, RuntimePromptContextSnapshot):
        raw_bindings = checkpoint_source.compaction_bindings
    elif isinstance(checkpoint_source, Mapping):
        raw_bindings = checkpoint_source.get("compaction_bindings", ())
    else:
        raw_bindings = checkpoint_source
    return tuple(
        item
        if isinstance(item, ContextCompactionBinding)
        else ContextCompactionBinding.model_validate(item)
        for item in raw_bindings
    )


def _rejected_admission_from_binding(
    binding: ContextCompactionBinding,
    *,
    reason: ContextCompactionReuseRejectionReason,
    admission_id: str,
    source_binding_hash: str = _ZERO_HASH,
    required_candidate_ids: Sequence[str] = (),
    recent_suffix_ids: Sequence[str] = (),
    session_constraints_hash: str | None = None,
) -> ContextCompactionReuseAdmission:
    """Build a body-free fail-closed admission without creating a candidate."""

    artifact_checksum = (
        binding.artifact.integrity_checksum
        if _SHA256_RE.fullmatch(binding.artifact.integrity_checksum or "")
        else _ZERO_HASH
    )
    safe_source_binding_hash = (
        source_binding_hash if _SHA256_RE.fullmatch(source_binding_hash or "") else _ZERO_HASH
    )
    return ContextCompactionReuseAdmission(
        admission_id=admission_id,
        status=ContextCompactionReuseAdmissionStatus.REJECTED,
        rejection_reason=reason,
        source_candidate_ids=list(binding.record.source_candidate_ids),
        source_fingerprint=binding.record.source_fingerprint,
        source_binding_hash=safe_source_binding_hash,
        required_candidate_ids=list(required_candidate_ids),
        recent_suffix_ids=list(recent_suffix_ids),
        session_constraints_hash=session_constraints_hash,
        artifact_id=binding.artifact.artifact_id,
        artifact_kind=binding.artifact.kind,
        artifact_integrity_checksum=artifact_checksum,
        generated_summary_fingerprint=_sha256_text(binding.record.summary),
        used_in_prompt=False,
    )


def build_checkpoint_compaction_reuse_shadow_provider(
    checkpoint_source: (
        RuntimePromptContextSnapshot
        | Sequence[ContextCompactionBinding | Mapping[str, Any]]
        | Mapping[str, Any]
    ),
    *,
    source_binding_hashes: Mapping[str, str] | None = None,
    required_candidate_ids_by_compaction_id: Mapping[str, Sequence[str]] | None = None,
    recent_suffix_ids_by_compaction_id: Mapping[str, Sequence[str]] | None = None,
    session_constraints_hash: str | None = None,
    expected_artifact_integrity_checksums: Mapping[str, str] | None = None,
) -> Callable[[dict[str, Any]], list[ContextCompactionReuseAdmission]]:
    """Build a shadow provider from checkpoint-owned compaction bindings.

    New checkpoint bindings carry the old body-free source binding hash.  The
    optional ``source_binding_hashes`` map exists only for historical bindings
    that predate that field.  Missing entries fail closed instead of deriving a
    new "expected" hash from the current prompt payload.
    """

    frozen_bindings = _bindings_from_checkpoint_source(checkpoint_source)
    compatibility_hashes = dict(source_binding_hashes or {})
    required_ids = dict(required_candidate_ids_by_compaction_id or {})
    recent_ids = dict(recent_suffix_ids_by_compaction_id or {})
    expected_checksums = dict(expected_artifact_integrity_checksums or {})

    def provider(shadow_payload: dict[str, Any]) -> list[ContextCompactionReuseAdmission]:
        admissions: list[ContextCompactionReuseAdmission] = []
        for index, binding in enumerate(frozen_bindings, start=1):
            compaction_id = binding.record.compaction_id
            admission_id = f"checkpoint-reuse:{index}:{compaction_id}"
            required_candidate_ids = list(required_ids.get(compaction_id, ()))
            recent_suffix_ids = list(recent_ids.get(compaction_id, ()))
            persisted_hash = binding.source_binding_hash
            compatibility_hash = compatibility_hashes.get(compaction_id)
            if persisted_hash and compatibility_hash and persisted_hash != compatibility_hash:
                admissions.append(
                    _rejected_admission_from_binding(
                        binding,
                        reason=(
                            ContextCompactionReuseRejectionReason.ARTIFACT_CONTRACT_INVALID
                        ),
                        admission_id=admission_id,
                        source_binding_hash=persisted_hash,
                        required_candidate_ids=required_candidate_ids,
                        recent_suffix_ids=recent_suffix_ids,
                        session_constraints_hash=session_constraints_hash,
                    )
                )
                continue
            source_binding_hash = persisted_hash or compatibility_hash
            if not source_binding_hash:
                admissions.append(
                    _rejected_admission_from_binding(
                        binding,
                        reason=(
                            ContextCompactionReuseRejectionReason.ARTIFACT_CONTRACT_INVALID
                        ),
                        admission_id=admission_id,
                        required_candidate_ids=required_candidate_ids,
                        recent_suffix_ids=recent_suffix_ids,
                        session_constraints_hash=session_constraints_hash,
                    )
                )
                continue
            try:
                candidate = ReusableCompactionArtifactCandidate.from_binding(
                    binding,
                    source_binding_hash=source_binding_hash,
                    candidate_id=f"checkpoint:{binding.artifact.artifact_id}",
                    required_candidate_ids=required_candidate_ids,
                    recent_suffix_ids=recent_suffix_ids,
                    session_constraints_hash=session_constraints_hash,
                    expected_artifact_integrity_checksum=expected_checksums.get(
                        binding.artifact.artifact_id
                    ),
                )
                admissions.append(
                    admit_reusable_compaction_candidate(
                        candidate,
                        shadow_payload,
                        admission_id=admission_id,
                    )
                )
            except Exception:
                admissions.append(
                    _rejected_admission_from_binding(
                        binding,
                        reason=ContextCompactionReuseRejectionReason.ARTIFACT_CONTRACT_INVALID,
                        admission_id=admission_id,
                        source_binding_hash=source_binding_hash,
                        required_candidate_ids=required_candidate_ids,
                        recent_suffix_ids=recent_suffix_ids,
                        session_constraints_hash=session_constraints_hash,
                    )
                )
        return admissions

    return provider


__all__ = [
    "ReusableCompactionArtifactCandidate",
    "ReusableCompactionPromptUsePreflight",
    "ReusableCompactionPromptUsePreflightStatus",
    "ReusableCompactionPromptUseRejectionReason",
    "ReusableCompactionPromptUseSimulation",
    "ReusableCompactionPromptUseSimulationStatus",
    "ReusableCompactionPromptUseSimulationRejectionReason",
    "ReusableCompactionSemanticFact",
    "admit_reusable_compaction_candidate",
    "build_checkpoint_compaction_reuse_shadow_provider",
    "build_compaction_reuse_shadow_provider",
    "preflight_reusable_compaction_prompt_use",
    "simulate_reusable_compaction_prompt_use",
    "source_binding_hash_from_shadow_payload",
]
