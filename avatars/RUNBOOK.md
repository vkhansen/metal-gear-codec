# Codec avatar runbook

Crop portraits to the exact Metal Gear codec face-box used by this repo.

## Target (do not change)

| Spec | Value | Why |
|---|---|---|
| Pixel size | **140 × 180** | `#mgs-codec .img-left / .img-right` in `index.html` |
| Aspect | **7:9** | 140:180 |
| Format | **JPEG** | `<img>` avatars; quality 95 |
| Colorspace | **sRGB** | Matches sources |
| Framing | Head and shoulders, face centered | Original MGS codec portraits |

CSS also sets `border: 1px` and `box-sizing: border-box`, so the painted picture is 138 × 178. Export **140 × 180** anyway — that is the element box. There is no `object-fit`; a non-7:9 file will be stretched.

Optional 2× export for sharp displays: **280 × 360** (still 7:9). Same commands, pass `-Width 280 -Height 360`.

## 1. Install ImageMagick

Already present on this machine:

```
ImageMagick 7.1.2-12 Q16-HDRI x64
magick.exe  C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe
```

If `magick` is missing, install with winget, then **open a new terminal**:

```powershell
winget install --id ImageMagick.ImageMagick -e --accept-package-agreements --accept-source-agreements
magick -version
```

Chocolatey alternative: `choco install imagemagick -y`

Confirm you are calling ImageMagick, not Windows `C:\Windows\System32\convert.exe`. Always use `magick`, never `convert`.

## 2. Sources

Leave the masters at the repo root. Do not overwrite them.

| File | Geometry | Notes |
|---|---|---|
| `jeerasak_ise.jpg` | 1408 × 1408 JPEG q95 sRGB | Jeerasak (left box) |
| `big_boss_cigar.jpg` | 1408 × 1408 JPEG q95 sRGB | Big Boss (right box) |

Outputs go in `avatars/` with the **same file names**.

## 3. Geometry for these two files

Largest exact 7:9 rectangle inside 1408 × 1408:

```
k      = floor(min(1408/7, 1408/9)) = 156
crop   = (7k) × (9k) = 1092 × 1404
offset = ((1408-1092)/2, (1408-1404)/2) = +158+2
```

ImageMagick geometry string: **`1092x1404+158+2`**

Center crop is correct for both: Jeerasak’s face stays in the middle; Big Boss’s cigar and smoke stay inside the frame. Do not use west/east gravity.

Scale factor 1092/140 = 1404/180 = **7.8** (no stretch).

## 4. One-shot (script)

From the repo root, PowerShell 7+:

```powershell
Set-Location D:\GitHub\metal-gear-codec
.\scripts\crop-codec-avatars.ps1
```

That writes:

```
avatars/jeerasak_ise.jpg      140x180 JPEG
avatars/big_boss_cigar.jpg    140x180 JPEG
```

Another portrait:

```powershell
.\scripts\crop-codec-avatars.ps1 -File viggo.jpg
```

2×:

```powershell
.\scripts\crop-codec-avatars.ps1 -Width 280 -Height 360
```

## 5. One-shot (raw magick)

Same result without the script. Run from the repo root.

```powershell
New-Item -ItemType Directory -Force -Path .\avatars | Out-Null

foreach ($name in @('jeerasak_ise.jpg', 'big_boss_cigar.jpg')) {
    # Forward slashes: ImageMagick treats '\' as an escape on Windows.
    magick $name `
        -crop 1092x1404+158+2 +repage `
        -filter Lanczos `
        -resize '140x180!' `
        -unsharp '0x0.6+0.6+0.02' `
        -colorspace sRGB `
        -quality 95 `
        -strip `
        "avatars/$name"
}
```

For a source that is **not** 1408 × 1408, do not reuse `1092x1404+158+2`. Use the script (it computes the inscribed 7:9 box) or:

```powershell
# Fill 140x180 then center-crop. Works for any source size.
magick -- SOURCE.jpg -resize '140x180^' -gravity Center -extent 140x180 -quality 95 -strip avatars\OUT.jpg
```

The `^` fill-area resize is slightly different from the exact-7:9-then-scale method (it does not snap to a 7k×9k pixel rectangle first). Prefer the script when you need bit-exact repeatability.

## 6. Verify

```powershell
magick identify avatars\jeerasak_ise.jpg avatars\big_boss_cigar.jpg
```

Required line for each:

```
JPEG 140x180 140x180+0+0 8-bit sRGB
```

Fail if width/height is anything else, or if identify reports a different aspect.

## 7. Drop into the codec

```html
<img src="avatars/jeerasak_ise.jpg" alt="Jeerasak" class="img-left">
<img src="avatars/big_boss_cigar.jpg" alt="Big Boss" class="img-right">
```

Left = callee (Jeerasak), right = caller (Big Boss), matching `ISE_Codec_120.85.md`.

## Repeat checklist

1. `magick -version` works.
2. Master is still the large file at repo root (or another path passed as `-SourceDir`).
3. Crop is center, 7:9, then resize to 140×180 with `!` (force exact size).
4. `-strip` so no EXIF orientation rotates the face in-browser.
5. `identify` says `140x180`.
6. Open both outputs; face not clipped, no letterboxing, no stretch.
