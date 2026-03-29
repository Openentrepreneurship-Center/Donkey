"""화자 분리 순수 함수 (오디오·LLM 없음)."""

import numpy as np

from app.services.rule_based_diarization import (
    assign_roles_to_segments,
    build_turns,
    cluster_speakers,
)


def test_build_turns_merges_close_segments():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "길게 말합니다"},
        {"start": 1.1, "end": 2.0, "text": "이어서 말함"},
    ]
    turns = build_turns(segs, gap_threshold=0.4, max_turn_duration_sec=25.0)
    assert len(turns) == 1
    assert len(turns[0]) == 2


def test_assign_roles_to_segments():
    labels = np.array([0, 1, 0])
    role_map = {"cluster_0_role": "DOCTOR", "cluster_1_role": "PATIENT"}
    out = assign_roles_to_segments(labels, role_map)
    assert out[0] == "SPEAKER_00"
    assert out[1] == "SPEAKER_01"
    assert out[2] == "SPEAKER_00"


def test_cluster_speakers_two_clusters():
    v0 = np.zeros(8)
    v1 = np.ones(8)
    labels = cluster_speakers([v0, v0, v1, v1], connectivity=True)
    assert set(labels.tolist()) <= {0, 1}
