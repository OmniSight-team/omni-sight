"""OMNI-604: one test per loader trap in `docs/dataset-layout.md`.

Each test builds a tiny dataset in the dataset's native layout that contains the trap,
and fails if the loader falls into it. No database, no video files.
"""

import json
from pathlib import Path

import pytest
from omnisight_common.datasets import AnnotationSource, ccd, ucf_crime, virat


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- UCF-Crime

UCF_LISTING = [
    "videos/Anomaly-Videos-Part-3/Robbery/Robbery048_x264.mp4",
    "videos/Anomaly-Videos-Part-3/Robbery/Robbery050_x264.mp4",
    "videos/Anomaly-Videos-Part-3/Robbery/Robbery051_x264.mp4",
    "videos/Anomaly-Videos-Part-1/Abuse/Abuse028_x264.mp4",
    "videos/Training-Normal-Videos-Part-1/Normal_Videos001_x264.mp4",
    "videos/Testing_Normal_Videos_Anomaly/Normal_Videos_003_x264.mp4",
    # namesake of the testing normal above
    "videos/Normal_Videos_for_Event_Recognition/Normal_Videos_003_x264.mp4",
]


@pytest.fixture
def ucf(tmp_path: Path) -> Path:
    root = tmp_path / "ucf_crime"
    ann = root / "annotations"
    write(root / "video_files.txt", "\n".join(UCF_LISTING) + "\n")
    write(
        ann / "Anomaly_Train.txt",
        "Robbery/Robbery048_x264.mp4\nRobbery/Robbery050_x264.mp4\n"
        "Training_Normal_Videos_Anomaly/Normal_Videos001_x264.mp4\n",
    )
    write(ann / "Anomaly_Detection_splits" / "Anomaly_Train.txt", "")  # 0 bytes, as shipped
    write(
        ann / "Anomaly_Detection_splits" / "Anomaly_Test.txt",
        "Abuse/Abuse028_x264.mp4\nRobbery/Robbery051_x264.mp4\n"
        "Testing_Normal_Videos_Anomaly/Normal_Videos_003_x264.mp4\n",
    )
    write(
        ann / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt",
        "Abuse028_x264.mp4  Abuse  165  240  -1  -1\n"
        "Robbery051_x264.mp4  Robbery  300  450  900  1200\n"
        "Normal_Videos_003_x264.mp4  Normal  -1  -1  -1  -1\n",
    )
    uca = {
        "Train": {
            "Robbery048_x264": {"duration": 90.0, "timestamps": [[20.0, 25.0], [12.5, 18.0], [3.0, 6.0]],
                                "sentences": ["A man points a gun at the clerk.", "A man grabs the bag.",
                                              "A customer walks in."]},
            "Robbery050_x264": {"duration": 60.0, "timestamps": [[1.0, 5.0]], "sentences": ["Two people talk."]},
            # in UCA's own Train, but in the official test list: official times must win
            "Robbery051_x264": {"duration": 60.0, "timestamps": [[0.5, 2.0]], "sentences": ["A man points a gun."]},
        },
        "Val": {},
        "Test": {},
    }
    for split, content in uca.items():
        write(ann / "uca" / "json" / f"UCFCrime_{split}.json", json.dumps(content))
    return root


def by_key(entries):
    return {e.clip_key: e for e in entries}


def test_ucf_event_recognition_namesakes_are_excluded(ucf):
    e = by_key(ucf_crime.load(ucf))["Normal_Videos_003_x264.mp4"]
    assert e.video_relpath.startswith("videos/Testing_Normal_Videos_Anomaly/")


def test_ucf_duplicate_filename_is_an_error_not_a_silent_pick(ucf):
    listing = ucf / "video_files.txt"
    write(listing, listing.read_text() + "videos/Testing_Normal_Videos_Anomaly/Abuse028_x264.mp4\n")
    with pytest.raises(ValueError, match="listed twice"):
        ucf_crime.load(ucf)


def test_ucf_training_list_is_the_top_level_one(ucf):
    entries = ucf_crime.load(ucf)
    assert sum(e.attributes["official_list"] == "train" for e in entries) == 3


def test_ucf_empty_training_list_is_an_error(ucf):
    write(ucf / "annotations" / "Anomaly_Train.txt", "")
    with pytest.raises(ValueError, match="empty"):
        ucf_crime.load(ucf)


def test_ucf_class_is_the_class_folder_not_part_n(ucf):
    entries = by_key(ucf_crime.load(ucf))
    assert entries["Robbery048_x264.mp4"].event_class == "Robbery"
    assert entries["Abuse028_x264.mp4"].event_class == "Abuse"
    assert entries["Normal_Videos001_x264.mp4"].event_class == "Normal"
    assert not any(e.event_class.startswith("Anomaly-Videos") for e in entries.values())


def test_ucf_test_times_are_frames_at_30_fps_with_a_second_interval(ucf):
    entries = by_key(ucf_crime.load(ucf))
    abuse = entries["Abuse028_x264.mp4"]
    assert (abuse.event_start_s, abuse.event_end_s) == (5.5, 8.0)
    assert abuse.annotation_source == AnnotationSource.UCF_CRIME_TEMPORAL
    assert "second_interval" not in abuse.attributes
    robbery = entries["Robbery051_x264.mp4"]
    assert (robbery.event_start_s, robbery.event_end_s) == (10.0, 15.0)
    assert robbery.attributes["second_interval"] == [30.0, 40.0]


def test_ucf_uca_split_is_not_the_official_split(ucf):
    e = by_key(ucf_crime.load(ucf))["Robbery051_x264.mp4"]
    assert e.attributes["official_list"] == "test"
    assert e.annotation_source == AnnotationSource.UCF_CRIME_TEMPORAL


def test_ucf_training_time_is_the_earliest_matching_uca_segment(ucf):
    entries = by_key(ucf_crime.load(ucf))
    timed = entries["Robbery048_x264.mp4"]
    assert (timed.event_start_s, timed.event_end_s, timed.annotation_source) == (12.5, 18.0, AnnotationSource.UCA)
    untimed = entries["Robbery050_x264.mp4"]
    assert untimed.event_start_s is None and untimed.annotation_source == AnnotationSource.UNTIMED


def test_ucf_normals_keep_their_official_list(ucf):
    entries = by_key(ucf_crime.load(ucf))
    assert entries["Normal_Videos_003_x264.mp4"].attributes["official_list"] == "test"
    assert entries["Normal_Videos001_x264.mp4"].attributes["official_list"] == "train"
    assert entries["Normal_Videos001_x264.mp4"].annotation_source == AnnotationSource.NORMAL


# ---------------------------------------------------------------- CCD

def bins(first_one: int) -> str:
    return "[" + ", ".join("1" if i >= first_one else "0" for i in range(50)) + "]"


@pytest.fixture
def ccd_root(tmp_path: Path) -> Path:
    root = tmp_path / "ccd"
    write(
        root / "video_files.txt",
        "videos/Crash-1500/000001.mp4\nvideos/Crash-1500/000002.mp4\n"
        "videos/Normal/000001.mp4\nvideos/Normal/000002.mp4\nvideos/Normal/000003.mp4\n",
    )
    write(
        root / "videos" / "Crash-1500.txt",
        f"000001,{bins(32)},000285,0000,Day,Normal,Yes\n000002,{bins(30)},000646,0007,Night,Rainy,No\n",
    )
    return root


def test_ccd_label_line_is_not_split_on_commas():
    row = ccd.parse_label_line(f"000001,{bins(32)},000285,0000,Day,Normal,Yes")
    assert len(row["bins"]) == 50
    assert (row["youtube_id"], row["timing"], row["weather"], row["ego_involved"]) == ("0000", "Day", "Normal", "Yes")


def test_ccd_event_start_is_first_one_at_10_fps(ccd_root):
    e = by_key(ccd.load(ccd_root))["Crash-1500/000001"]
    assert e.event_start_s == 3.2
    assert e.event_end_s == 5.0
    assert e.attributes["youtube_id"] == "0000"


def test_ccd_identity_is_subset_and_id(ccd_root):
    entries = by_key(ccd.load(ccd_root))
    assert len(entries) == 5
    crash, normal = entries["Crash-1500/000001"], entries["Normal/000001"]
    assert crash.event_class == "Crash" and normal.event_class == "Normal"
    assert normal.event_start_s is None and normal.annotation_source == AnnotationSource.NORMAL
    assert crash.video_relpath != normal.video_relpath


def test_ccd_crash_clip_without_a_label_line_is_an_error(ccd_root):
    listing = ccd_root / "video_files.txt"
    write(listing, listing.read_text() + "videos/Crash-1500/000003.mp4\n")
    with pytest.raises(ValueError, match="no label line"):
        ccd.load(ccd_root)


# ---------------------------------------------------------------- VIRAT

GOOD = "VIRAT_S_050201_05_000890_000944"
EMPTY_DIRS = "VIRAT_S_010001_00_000000_000030"
OBJECTS_ONLY = "VIRAT_S_000002_00_000100_000200"


@pytest.fixture
def virat_root(tmp_path: Path) -> Path:
    root = tmp_path / "virat"
    ann = root / "annotations"
    write(
        root / "video_files.txt",
        "".join(f"videos_original/{n}.mp4\n" for n in (GOOD, EMPTY_DIRS, OBJECTS_ONLY)),
    )
    write(ann / f"{GOOD}.viratdata.events.txt", "0 9 405 0 404 0 326 227 38 82\n1 1 80 415 494 415 1 1 1 1\n")
    write(ann / f"{GOOD}.viratdata.objects.txt", "0 268 54 1 2 3 4 1\n1 10 5 1 2 3 4 2\n2 10 5 1 2 3 4 1\n")
    write(ann / f"{GOOD}.viratdata.mapping.txt", "0 9 405 0 404 2 1 0 1\n1 1 80 415 494 1 0 1 0\n")
    for kind in virat.KINDS:  # names that are empty directories, as in the archive
        (ann / f"{EMPTY_DIRS}.viratdata.{kind}.txt").mkdir(parents=True)
    write(ann / f"{OBJECTS_ONLY}.viratdata.objects.txt", "0 10 5 1 2 3 4 1\n")
    (ann / f"{OBJECTS_ONLY}.viratdata.events.txt").mkdir()
    return root


def test_virat_empty_directories_are_not_annotations(virat_root):
    keys = [e.clip_key for e in virat.load(virat_root)]
    assert keys == [GOOD]


def test_virat_three_files_are_read_together(virat_root):
    e = virat.load(virat_root)[0]
    assert (e.attributes["events"], e.attributes["objects"], e.attributes["event_types"]) == (2, 3, [1, 9])


def test_virat_mapping_to_a_missing_object_is_an_error(virat_root):
    write(virat_root / "annotations" / f"{GOOD}.viratdata.objects.txt", "0 268 54 1 2 3 4 1\n")
    with pytest.raises(ValueError, match="not all in objects file"):
        virat.load(virat_root)


def test_virat_events_without_mapping_is_an_error(virat_root):
    (virat_root / "annotations" / f"{GOOD}.viratdata.mapping.txt").unlink()
    with pytest.raises(ValueError, match="mapping"):
        virat.load(virat_root)


def test_virat_scene_is_from_the_filename(virat_root):
    assert virat.load(virat_root)[0].attributes["scene"] == "0502"
