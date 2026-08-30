#!/usr/bin/env python3
"""Bake ISE codec dialogue to per-line MP3s via the xAI TTS API.

Parses ISE_Codec_120.85.md, synthesizes each utterance with a character
voice (Big Boss = leo, Jeerasak = rex), optionally runs an ffmpeg radio
band-pass, and writes audio/ plus audio/manifest.json.

Usage (from repo root):

    python scripts/bake_codec_audio.py --dry-run
    python scripts/bake_codec_audio.py --limit 3
    python scripts/bake_codec_audio.py

Auth: set XAI_API_KEY, or put it in a repo-root .env file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TTS_URL = "https://api.x.ai/v1/tts"
VOICES_URL = "https://api.x.ai/v1/tts/voices"

DEFAULT_VOICES = {
    "BIG BOSS": {"voice_id": "leo", "speed": 0.9, "wrap": "low-pitch"},
    "JEERASAK": {"voice_id": "rex", "speed": 1.0, "wrap": None},
}

# Applied locally before the request. Thai and subscript N2O cannot go
# through the API replace map (punctuation / non-Latin keys).
LOCAL_REPLACEMENTS = (
    (re.compile(r"N₂O"), "N2O"),
    (re.compile(r"เกรงใจ"), "greng jai"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"\*([^*]+)\*"), r"\1"),
)

# Whole-word substitutions spoken by the API (keys: letters, digits, spaces).
PRONUNCIATION = {
    "N2O": "nitrous oxide",
    "ISE": "I S E",
    "ESS": "E S S",
    "FMEA": "F M E A",
    "AIAA": "A I A A",
    "MTR": "M T R",
    "CIA": "C I A",
    "CUHAR": "C U HAR",
}

SPEAKER_RE = re.compile(r"^\*\*([A-Z][A-Z0-9 ]*)\*\*\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
RULE_RE = re.compile(r"^---+\s*$", re.MULTILINE)
URL_ONLY_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

CODEC_FILTER = (
    "highpass=f=400,lowpass=f=3000,"
    "acompressor=threshold=-20dB:ratio=6:attack=5:release=50:makeup=3"
)

RETRY_STATUS = {429, 500, 503}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def api_key() -> str:
    load_dotenv(repo_root() / ".env")
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "XAI_API_KEY is not set. Export it, or add XAI_API_KEY=... to a "
            ".env file at the repo root."
        )
    return key


def is_mostly_cjk(text: str) -> bool:
    letters = [c for c in text if c.isalpha() or CJK_RE.search(c)]
    if not letters:
        return False
    cjk = sum(1 for c in letters if CJK_RE.search(c))
    return (cjk / len(letters)) > 0.5


def normalize_paragraph(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return ""
    joined = "\n".join(lines)
    if is_mostly_cjk(joined):
        return joined
    return " ".join(lines)


def spoken_text(display: str) -> str:
    text = display
    for pattern, repl in LOCAL_REPLACEMENTS:
        text = pattern.sub(repl, text)
    text = text.replace("ISE's", "I S E's")
    return text.strip()


def wrap_delivery(text: str, wrap: str | None, language: str) -> str:
    if not wrap or language != "en":
        return text
    return f"<{wrap}>{text}</{wrap}>"


def parse_dialogue(source: Path) -> list[dict]:
    src = FENCE_RE.sub("", source.read_text(encoding="utf-8"))
    matches = list(SPEAKER_RE.finditer(src))
    if not matches:
        raise SystemExit(f"No **SPEAKER** headings found in {source}")

    lines: list[dict] = []
    index = 0
    for i, match in enumerate(matches):
        speaker = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        body = RULE_RE.sub("", src[start:end])
        for chunk in re.split(r"\n\s*\n", body):
            text = normalize_paragraph(chunk)
            if not text:
                continue
            text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
            text = re.sub(r"\*([^*]+)\*", r"\1", text)
            index += 1
            slug = speaker.lower().replace(" ", "-")
            language = "ja" if is_mostly_cjk(text) else "en"
            skip_tts = bool(URL_ONLY_RE.fullmatch(text))
            lines.append(
                {
                    "index": index,
                    "speaker": speaker,
                    "slug": slug,
                    "text": text,
                    "spoken": spoken_text(text),
                    "language": language,
                    "skip_tts": skip_tts,
                    "file": None if skip_tts else f"{index:03d}-{slug}.mp3",
                }
            )
    return lines


def slug_filename(line: dict, out_dir: Path) -> Path | None:
    if line["skip_tts"] or not line["file"]:
        return None
    return out_dir / line["file"]


def http_json(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tts_request(
    key: str,
    text: str,
    voice_id: str,
    language: str,
    speed: float,
    retries: int = 4,
) -> bytes:
    payload: dict = {
        "text": text,
        "voice_id": voice_id,
        "language": language,
        "speed": speed,
        "text_normalization": True,
        "output_format": {
            "codec": "mp3",
            "sample_rate": 24000,
            "bit_rate": 128000,
        },
    }
    if language.startswith("en"):
        payload["replace"] = PRONUNCIATION

    body = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(retries):
        req = urllib.request.Request(
            TTS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                req, timeout=180, context=ssl.create_default_context()
            ) as resp:
                data = resp.read()
            if not data:
                raise RuntimeError("TTS returned an empty body")
            return data
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {err_body}"
            if exc.code in RETRY_STATUS and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(last_error) from exc
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(last_error) from exc
    raise RuntimeError(last_error or "TTS request failed")


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def apply_codec_filter(src: Path, ffmpeg: str, tmp_dir: Path) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dst = tmp_dir / src.name
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-af",
        CODEC_FILTER,
        "-codec:a",
        "libmp3lame",
        "-ar",
        "24000",
        "-b:a",
        "128k",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    dst.replace(src)


def write_manifest(
    out_dir: Path,
    source: Path,
    lines: list[dict],
    voices: dict,
    filtered: bool,
) -> Path:
    records = []
    for line in lines:
        path = slug_filename(line, out_dir)
        baked = bool(path and path.is_file() and path.stat().st_size > 0)
        records.append(
            {
                "index": line["index"],
                "speaker": line["speaker"],
                "text": line["text"],
                "language": line["language"],
                "skip_tts": line["skip_tts"],
                "file": None if line["skip_tts"] else f"audio/{line['file']}",
                "voice_id": None if line["skip_tts"] else voices[line["speaker"]]["voice_id"],
                "baked": baked,
                "bytes": path.stat().st_size if baked and path else 0,
            }
        )
    manifest = {
        "freq": "120.85",
        "source": source.name,
        "voices": {
            name: {"voice_id": cfg["voice_id"], "speed": cfg["speed"]}
            for name, cfg in voices.items()
        },
        "codec_filter": filtered,
        "line_count": len(records),
        "baked_count": sum(1 for r in records if r["baked"]),
        "lines": records,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def preview(lines: list[dict], voices: dict) -> None:
    print(f"{len(lines)} utterances\n")
    for line in lines:
        cfg = voices[line["speaker"]]
        flag = "SKIP" if line["skip_tts"] else f"{cfg['voice_id']:5s} {line['language']}"
        snippet = line["text"].replace("\n", " / ")
        if len(snippet) > 88:
            snippet = snippet[:85] + "..."
        print(f"{line['index']:03d}  {line['speaker']:<10}  {flag:<10}  {snippet}")


def build_voices(args: argparse.Namespace) -> dict:
    voices = {
        name: dict(cfg) for name, cfg in DEFAULT_VOICES.items()
    }
    voices["BIG BOSS"]["voice_id"] = args.voice_boss
    voices["JEERASAK"]["voice_id"] = args.voice_jeerasak
    voices["BIG BOSS"]["speed"] = args.speed_boss
    voices["JEERASAK"]["speed"] = args.speed_jeerasak
    return voices


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Bake ISE codec dialogue to per-line MP3s (xAI TTS)."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=root / "ISE_Codec_120.85.md",
        help="Dialogue markdown (default: repo ISE_Codec_120.85.md)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "audio",
        help="Output directory (default: repo audio/)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and print the bake plan")
    parser.add_argument("--check", action="store_true", help="List TTS voices and exit")
    parser.add_argument("--limit", type=int, default=0, help="Bake at most N speakable lines")
    parser.add_argument("--force", action="store_true", help="Overwrite existing MP3s")
    parser.add_argument(
        "--filter",
        choices=("auto", "on", "off"),
        default="auto",
        help="Radio band-pass via ffmpeg (default: auto)",
    )
    parser.add_argument("--voice-boss", default="leo", help="xAI voice_id for Big Boss")
    parser.add_argument("--voice-jeerasak", default="rex", help="xAI voice_id for Jeerasak")
    parser.add_argument("--speed-boss", type=float, default=0.9)
    parser.add_argument("--speed-jeerasak", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()
    voices = build_voices(args)

    if args.check:
        key = api_key()
        payload = http_json(VOICES_URL, key)
        for voice in payload.get("voices", []):
            print(f"{voice.get('voice_id', ''):12s}  {voice.get('name', '')}")
        return 0

    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit(f"Source not found: {source}")

    lines = parse_dialogue(source)
    unknown = sorted({ln["speaker"] for ln in lines if ln["speaker"] not in voices})
    if unknown:
        raise SystemExit(f"Unknown speaker(s): {', '.join(unknown)}")

    if args.dry_run:
        preview(lines, voices)
        ffmpeg = ffmpeg_path()
        print(f"\nffmpeg: {ffmpeg or 'not found (filter will be skipped unless --filter on)'}")
        return 0

    key = api_key()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "_tmp"

    ffmpeg = ffmpeg_path()
    if args.filter == "on" and not ffmpeg:
        raise SystemExit("ffmpeg not found; install it or pass --filter off")
    use_filter = (args.filter == "on") or (args.filter == "auto" and bool(ffmpeg))
    if args.filter == "auto" and not ffmpeg:
        print("ffmpeg not found; writing unfiltered MP3s")

    speakable = [ln for ln in lines if not ln["skip_tts"]]
    if args.limit:
        speakable = speakable[: args.limit]

    baked = 0
    skipped = 0
    failed: list[str] = []

    try:
        for n, line in enumerate(speakable, start=1):
            path = slug_filename(line, out_dir)
            assert path is not None
            cfg = voices[line["speaker"]]
            label = f"[{n}/{len(speakable)}] {line['index']:03d} {line['speaker']}"

            if path.is_file() and path.stat().st_size > 0 and not args.force:
                print(f"{label}  skip (exists)")
                skipped += 1
                continue

            text = wrap_delivery(line["spoken"], cfg["wrap"], line["language"])
            print(f"{label}  {cfg['voice_id']}  {line['language']}  -> {path.name}")
            try:
                audio = tts_request(
                    key,
                    text,
                    cfg["voice_id"],
                    line["language"],
                    cfg["speed"],
                )
                path.write_bytes(audio)
                if use_filter and ffmpeg:
                    apply_codec_filter(path, ffmpeg, tmp_dir)
                baked += 1
            except Exception as exc:
                failed.append(f"{line['index']:03d}: {exc}")
                print(f"  FAILED: {exc}")
                if path.is_file() and path.stat().st_size == 0:
                    path.unlink()

            time.sleep(0.15)
    except KeyboardInterrupt:
        print("\nInterrupted; writing manifest for what exists.")

    manifest = write_manifest(out_dir, source, lines, voices, use_filter)
    if tmp_dir.is_dir() and not any(tmp_dir.iterdir()):
        tmp_dir.rmdir()

    print(
        f"\nBaked {baked}, skipped {skipped}, failed {len(failed)}. "
        f"Manifest: {manifest}"
    )
    if failed:
        for item in failed:
            print(f"  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
