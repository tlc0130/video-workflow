import json
from pathlib import Path

import pytest

from src import workflow


def test_ensure_dirs_creates_paths(tmp_path):
    cfg = {
        "paths": {
            "work_dir": str(tmp_path / "work"),
            "output_dir": str(tmp_path / "out"),
        }
    }

    work_dir, output_dir = workflow.ensure_dirs(cfg)

    assert work_dir.exists()
    assert output_dir.exists()
    assert work_dir.is_dir()
    assert output_dir.is_dir()


def test_write_subtitle_file_covers_total_duration(tmp_path):
    subtitle_path = tmp_path / "test.srt"
    script = "One two three four five six seven eight nine ten eleven twelve"

    workflow.write_subtitle_file(script, subtitle_path, duration=12)

    text = subtitle_path.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 -->" in text
    assert "00:00:12,000" in text


def test_compose_video_writes_expected_output_path(monkeypatch, tmp_path):
    cfg = {
        "video": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "duration_seconds": 10,
            "background_color": "#000000",
            "title_prefix": "AutoClip",
        }
    }

    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()

    generated_audio = []

    def fake_generate_silent_audio(audio_path: Path, duration: int):
        generated_audio.append((audio_path, duration))
        audio_path.write_bytes(b"fake-wav")

    calls = []

    class Result:
        returncode = 0

    def fake_subprocess_run(cmd, check, capture_output):
        calls.append(cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"fake-mp4")
        return Result()

    monkeypatch.setattr(workflow, "generate_silent_audio", fake_generate_silent_audio)
    monkeypatch.setattr(workflow.subprocess, "run", fake_subprocess_run)

    audio_path, video_path = workflow.compose_video(
        cfg=cfg,
        script_text="hello world",
        work_dir=work_dir,
        output_dir=output_dir,
    )

    assert generated_audio, "Expected audio generation to be invoked"
    assert audio_path.exists()
    assert video_path.exists()
    assert video_path.suffix == ".mp4"
    assert any("color=c=#000000:s=1080x1920:r=30:d=10" in str(part) for part in calls[0])


def test_validate_config_raises_on_missing_top_level_key():
    with pytest.raises(ValueError, match="topic_prompt"):
        workflow.validate_config({})


def test_run_once_dry_run_skips_uploads(monkeypatch, tmp_path):
    cfg = {
        "topic_prompt": "test",
        "video": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "duration_seconds": 10,
            "background_color": "#000000",
            "title_prefix": "AutoClip",
        },
        "paths": {
            "work_dir": str(tmp_path / "work"),
            "output_dir": str(tmp_path / "out"),
        },
        "openai": {"api_key": "dummy", "model": "gpt-4o-mini"},
        "youtube": {"enabled": True},
        "tiktok": {"enabled": True},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")

    def fake_generate_script(_cfg):
        return "hello"

    def fake_compose_video(_cfg, _script, work_dir, output_dir):
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = work_dir / "a.wav"
        video = output_dir / "v.mp4"
        audio.write_bytes(b"a")
        video.write_bytes(b"v")
        return audio, video

    called = {"yt": 0, "tt": 0}

    def fake_upload_yt(_cfg, _artifacts):
        called["yt"] += 1

    def fake_upload_tt(_cfg, _artifacts):
        called["tt"] += 1

    monkeypatch.setattr(workflow, "generate_script", fake_generate_script)
    monkeypatch.setattr(workflow, "compose_video", fake_compose_video)
    monkeypatch.setattr(workflow, "upload_youtube", fake_upload_yt)
    monkeypatch.setattr(workflow, "upload_tiktok", fake_upload_tt)

    artifacts = workflow.run_once(config_path, dry_run=True)

    assert artifacts.video_path.exists()
    assert called["yt"] == 0
    assert called["tt"] == 0
