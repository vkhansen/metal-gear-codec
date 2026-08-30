# Codec audio bake runbook

Turn `ISE_Codec_120.85.md` into per-line MP3s in the Metal Gear codec voice style, then play them from the page later.

Do **not** call the TTS API from the browser. The page is static; a client-side key would leak. Bake offline, commit or host the MP3s, and let the codec player advance line-by-line.

## Target

| Spec | Value | Why |
|---|---|---|
| Input | `ISE_Codec_120.85.md` | Canonical briefing script |
| Output | `audio/NNN-speaker.mp3` + `audio/manifest.json` | One file per codec click |
| Voices | Big Boss `leo`, Jeerasak `rex` | xAI TTS voice IDs |
| Format | MP3 24 kHz / 128 kbps | Plays in `<audio>` / Web Audio |
| Filter | Band-pass 400–3000 Hz + compressor | Radio/codec coloration |
| Lines | 118 utterances (117 spoken, 1 URL skipped) | Blank-line splits inside a speaker turn |

MGS style is mostly the **radio filter** and two distinct voices, not a celebrity clone. Do not clone David Hayter or Kiefer Sutherland.

## 1. Voices

| Character | `voice_id` | Speed | Delivery |
|---|---|---|---|
| Big Boss | `leo` | 0.9 | wrapped in `<low-pitch>` |
| Jeerasak | `rex` | 1.0 | unmodified |

Fallbacks if you retune: Big Boss `orion` or `zagan`; Jeerasak `rigel` or `lux`.

```powershell
python scripts/bake_codec_audio.py --voice-boss orion --voice-jeerasak rigel --limit 3
```

Custom clones (a short clip of Viggo / Jeerasak, 10–120 s) are set in the [xAI voice library](https://console.x.ai/team/default/voice/voice-library). Pass the returned ID with `--voice-boss` / `--voice-jeerasak`. Custom voices are US-only, not Illinois.

## 2. Auth

The script reads `XAI_API_KEY` from the environment, or from a repo-root `.env` (gitignored):

```
XAI_API_KEY=xai-...
```

```powershell
python scripts/bake_codec_audio.py --check
```

That lists built-in voice IDs and confirms the key works. It does not synthesize audio.

## 3. What the parser does

1. Drops fenced ` ``` ` blocks (the CONNECTED / SIGNAL LOST frames).
2. Splits on `**SPEAKER**` headings (`BIG BOSS`, `JEERASAK`).
3. Splits each turn on blank lines → one MP3 per paragraph (codec click).
4. Strips markdown italics.
5. URL-only paragraphs (`https://...`) are recorded in the manifest with `skip_tts: true` and no file.
6. Mostly-CJK text (the haiku) is synthesized with `language: "ja"`.

Spoken substitutions (not shown on screen):

| Written | Spoken |
|---|---|
| `N₂O` / `N2O` | nitrous oxide |
| `ISE` | I S E |
| `ESS` | E S S |
| `FMEA` | F M E A |
| `AIAA` | A I A A |
| `MTR` | M T R |
| `CIA` | C I A |
| `CUHAR` | C U HAR |
| `เกรงใจ` | greng jai |

Thai is not a first-class TTS language, so `เกรงใจ` is respelt before the request.

## 4. Bake

Python 3.10+ and an API key. ffmpeg is optional (radio filter). No Node.

From the repo root:

```powershell
Set-Location D:\GitHub\metal-gear-codec

# plan only — no API calls
python scripts/bake_codec_audio.py --dry-run

# three lines, to hear both voices
python scripts/bake_codec_audio.py --limit 3

# full bake (skips MP3s that already exist)
python scripts/bake_codec_audio.py
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print the 118-line plan |
| `--limit N` | Synthesize the first N speakable lines |
| `--force` | Overwrite existing MP3s |
| `--filter auto` | ffmpeg band-pass when ffmpeg is on PATH (default) |
| `--filter on` | Require ffmpeg; fail if missing |
| `--filter off` | Leave the raw TTS MP3 |

ffmpeg is already on this machine. If it disappears:

```powershell
winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
```

Radio filter applied after TTS:

```
highpass=f=400, lowpass=f=3000, acompressor=threshold=-20dB:ratio=6:attack=5:release=50:makeup=3
```

Interrupted runs resume: existing non-empty MP3s are skipped unless `--force`. The manifest is rewritten at the end from whatever files exist.

## 5. Output

```
audio/001-big-boss.mp3
audio/002-jeerasak.mp3
...
audio/118-big-boss.mp3
audio/manifest.json
audio/_tmp/          (scratch; gitignored)
```

Index `038` is the YouTube URL — no MP3.

`manifest.json` (excerpt):

```json
{
  "freq": "120.85",
  "source": "ISE_Codec_120.85.md",
  "voices": {
    "BIG BOSS": { "voice_id": "leo", "speed": 0.9 },
    "JEERASAK": { "voice_id": "rex", "speed": 1.0 }
  },
  "codec_filter": true,
  "line_count": 118,
  "baked_count": 117,
  "lines": [
    {
      "index": 1,
      "speaker": "BIG BOSS",
      "text": "Jeerasak. This is Big Boss. Do you copy?",
      "language": "en",
      "skip_tts": false,
      "file": "audio/001-big-boss.mp3",
      "voice_id": "leo",
      "baked": true,
      "bytes": 12345
    }
  ]
}
```

Cost is per character of the briefing (a few thousand characters). `--limit 3` first.

## 6. Drop into the codec (not wired yet)

The player still advances on click with no speech. Next step is `mgs-player.js`: on each advance, play `manifest.lines[i].file`, dim the listener portrait, and drive the volume bar from a Web Audio `AnalyserNode` instead of `Math.random()`. Keep `codec.mp3` as the connect beep.

Until that is wired, you can audition a line with:

```powershell
Start-Process audio\001-big-boss.mp3
```

## Repeat checklist

1. `python scripts/bake_codec_audio.py --dry-run` still reports 118 utterances, haiku as `ja`, URL as `SKIP`.
2. `XAI_API_KEY` is set; `.env` is not committed.
3. `--limit 3` before a full bake; both speakers audible and distinct.
4. ffmpeg filter on unless you are iterating voice IDs (then `--filter off` is faster).
5. `audio/manifest.json` `baked_count` matches the speakable line count (117).
6. Do not call `https://api.x.ai/v1/tts` from `index.html`.
