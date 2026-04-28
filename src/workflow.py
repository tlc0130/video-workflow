import argparse
import json
import logging
import subprocess
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class RunArtifacts:
    script_text: str
    audio_path: Path
    video_path: Path
    title: str
    description: str


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_config(cfg: dict) -> None:
    required_top_level = ["topic_prompt", "video", "paths", "openai"]
    for key in required_top_level:
        if key not in cfg:
            raise ValueError(f"Missing required config key: {key}")

    required_video = ["width", "height", "fps", "duration_seconds", "background_color"]
    for key in required_video:
        if key not in cfg["video"]:
            raise ValueError(f"Missing required video config key: video.{key}")

    required_paths = ["work_dir", "output_dir"]
    for key in required_paths:
        if key not in cfg["paths"]:
            raise ValueError(f"Missing required paths config key: paths.{key}")

    if "api_key" not in cfg["openai"]:
        raise ValueError("Missing required openai config key: openai.api_key")


def ensure_dirs(cfg: dict) -> tuple[Path, Path]:
    work_dir = Path(cfg["paths"]["work_dir"]).resolve()
    output_dir = Path(cfg["paths"]["output_dir"]).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return work_dir, output_dir


def retry(operation: Callable[[], Any], retries: int, delay_seconds: float, op_name: str) -> Any:
    attempts = 0
    while True:
        try:
            return operation()
        except Exception as exc:
            attempts += 1
            if attempts > retries:
                raise
            wait = delay_seconds * (2 ** (attempts - 1))
            logger.warning("%s failed (%s). Retrying in %.2fs (%d/%d)", op_name, exc, wait, attempts, retries)
            time.sleep(wait)


def generate_script(cfg: dict) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=cfg["openai"]["api_key"])
    prompt = cfg["topic_prompt"]
    retries = cfg.get("runtime", {}).get("upload_retries", 2)
    delay = cfg.get("runtime", {}).get("retry_delay_seconds", 2.0)

    def call_api():
        response = client.responses.create(
            model=cfg["openai"].get("model", "gpt-4o-mini"),
            input=(
                "Write a short, engaging script for a vertical short-form video. "
                "Keep it under 85 words, hook in first sentence, and end with a CTA. "
                f"Topic: {prompt}"
            ),
        )
        return response.output_text.strip()

    return retry(call_api, retries=retries, delay_seconds=delay, op_name="generate_script")


def write_subtitle_file(script_text: str, subtitle_path: Path, duration: int) -> None:
    lines = textwrap.wrap(script_text, width=38)
    chunk_duration = max(2, duration // max(1, len(lines)))

    def ts(seconds: int) -> str:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02}:{m:02}:{s:02},000"

    current = 0
    with subtitle_path.open("w", encoding="utf-8") as f:
        for idx, line in enumerate(lines, start=1):
            start = current
            end = min(duration, start + chunk_duration)
            if idx == len(lines):
                end = duration
            f.write(f"{idx}\n{ts(start)} --> {ts(end)}\n{line}\n\n")
            current = end


def generate_silent_audio(audio_path: Path, duration: int) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        str(duration),
        str(audio_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def compose_video(cfg: dict, script_text: str, work_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    width = cfg["video"]["width"]
    height = cfg["video"]["height"]
    fps = cfg["video"]["fps"]
    duration = cfg["video"]["duration_seconds"]
    color = cfg["video"]["background_color"]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    subtitle_path = work_dir / f"subs-{ts}.srt"
    audio_path = work_dir / f"audio-{ts}.wav"
    video_path = output_dir / f"short-{ts}.mp4"

    write_subtitle_file(script_text, subtitle_path, duration)
    generate_silent_audio(audio_path, duration)

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}:r={fps}:d={duration}",
        "-i",
        str(audio_path),
        "-vf",
        (
            f"subtitles={subtitle_path}:"
            "force_style='FontName=Arial,FontSize=14,PrimaryColour=&HFFFFFF&,"
            "OutlineColour=&H000000&,BorderStyle=3,Outline=1,MarginV=120,Alignment=2'"
        ),
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(video_path),
    ]
    subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
    return audio_path, video_path


def upload_youtube(cfg: dict, artifacts: RunArtifacts) -> None:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yc = cfg["youtube"]
    creds = Credentials(
        token=None,
        refresh_token=yc["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=yc["client_id"],
        client_secret=yc["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": artifacts.title,
            "description": artifacts.description,
            "categoryId": yc.get("category_id", "22"),
        },
        "status": {"privacyStatus": yc.get("privacy_status", "public")},
    }

    retries = cfg.get("runtime", {}).get("upload_retries", 2)
    delay = cfg.get("runtime", {}).get("retry_delay_seconds", 2.0)

    def do_upload():
        media = MediaFileUpload(str(artifacts.video_path), chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
            time.sleep(0.25)
        return response

    response = retry(do_upload, retries=retries, delay_seconds=delay, op_name="YouTube upload")
    logger.info("YouTube upload completed. Video ID: %s", response.get("id"))


def upload_tiktok(cfg: dict, artifacts: RunArtifacts) -> None:
    import requests

    tk = cfg["tiktok"]
    access_token = tk["access_token"]

    init_url = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
    init_payload = {
        "post_info": {
            "title": artifacts.title,
            "privacy_level": tk.get("privacy_level", "PUBLIC_TO_EVERYONE"),
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": artifacts.video_path.stat().st_size,
            "chunk_size": artifacts.video_path.stat().st_size,
            "total_chunk_count": 1,
        },
    }

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    retries = cfg.get("runtime", {}).get("upload_retries", 2)
    delay = cfg.get("runtime", {}).get("retry_delay_seconds", 2.0)

    init_res = retry(
        lambda: requests.post(init_url, headers=headers, json=init_payload, timeout=60),
        retries=retries,
        delay_seconds=delay,
        op_name="TikTok init",
    )
    init_res.raise_for_status()
    init_data = init_res.json()

    upload_url = init_data["data"]["upload_url"]
    with artifacts.video_path.open("rb") as f:
        raw = f.read()

    put_headers = {
        "Content-Type": "video/mp4",
        "Content-Range": f"bytes 0-{len(raw)-1}/{len(raw)}",
    }
    put_res = retry(
        lambda: requests.put(upload_url, headers=put_headers, data=raw, timeout=300),
        retries=retries,
        delay_seconds=delay,
        op_name="TikTok upload",
    )
    put_res.raise_for_status()

    logger.info("TikTok upload completed (inbox flow initialized).")


def run_once(config_path: Path, dry_run: bool = False) -> RunArtifacts:
    cfg = load_config(config_path)
    validate_config(cfg)
    work_dir, output_dir = ensure_dirs(cfg)

    script_text = generate_script(cfg)
    audio_path, video_path = compose_video(cfg, script_text, work_dir, output_dir)

    title = f"{cfg['video'].get('title_prefix', 'AutoClip')} - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    description = script_text + "\n\n#shorts #ai #automation"

    artifacts = RunArtifacts(
        script_text=script_text,
        audio_path=audio_path,
        video_path=video_path,
        title=title,
        description=description,
    )

    if dry_run:
        logger.info("Dry run enabled; skipping uploads.")
        logger.info("Done. Output video: %s", artifacts.video_path)
        return artifacts

    if cfg.get("youtube", {}).get("enabled", False):
        upload_youtube(cfg, artifacts)

    if cfg.get("tiktok", {}).get("enabled", False):
        upload_tiktok(cfg, artifacts)

    logger.info("Done. Output video: %s", artifacts.video_path)
    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated short-video workflow")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--run-once", action="store_true", help="Run one end-to-end execution")
    parser.add_argument("--dry-run", action="store_true", help="Generate assets but do not upload")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.run_once:
        run_once(Path(args.config).resolve(), dry_run=args.dry_run)
    else:
        raise SystemExit("Only --run-once is currently implemented.")


if __name__ == "__main__":
    main()
