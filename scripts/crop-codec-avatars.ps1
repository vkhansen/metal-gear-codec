#Requires -Version 7.0

<#
.SYNOPSIS
    Crop and resize portraits to Metal Gear codec avatar size (140x180, 7:9 JPEG).

.DESCRIPTION
    Inscribes the largest exact 7:9 rectangle in each source, center-crops it,
    then Lanczos-resizes to 140x180. Writes JPEG quality 95, sRGB, stripped.

.PARAMETER SourceDir
    Directory containing source portraits. Defaults to the repo root.

.PARAMETER OutputDir
    Directory for 140x180 outputs. Defaults to <repo>/avatars.

.PARAMETER Width
    Output width in pixels. Default 140 (codec CSS box).

.PARAMETER Height
    Output height in pixels. Default 180 (codec CSS box).

.PARAMETER File
    Source file names relative to SourceDir. Defaults to the two ISE portraits.

.EXAMPLE
    PS> .\scripts\crop-codec-avatars.ps1

.EXAMPLE
    PS> .\scripts\crop-codec-avatars.ps1 -File viggo.jpg -Width 280 -Height 360
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string]$SourceDir,

    [Parameter()]
    [string]$OutputDir,

    [Parameter()]
    [ValidateRange(1, 4096)]
    [int]$Width = 140,

    [Parameter()]
    [ValidateRange(1, 4096)]
    [int]$Height = 180,

    [Parameter()]
    [string[]]$File = @('jeerasak_ise.jpg', 'big_boss_cigar.jpg')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-RepoRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    }
    return (Get-Location).Path
}

function Get-LargestSevenByNineCrop {
    param(
        [Parameter(Mandatory)]
        [int]$SourceWidth,
        [Parameter(Mandatory)]
        [int]$SourceHeight
    )

    $k = [int][Math]::Floor([Math]::Min($SourceWidth / 7.0, $SourceHeight / 9.0))
    if ($k -lt 1) {
        throw "Source ${SourceWidth}x${SourceHeight} is smaller than 7x9."
    }

    $cropW = 7 * $k
    $cropH = 9 * $k
    $x = [int][Math]::Floor(($SourceWidth - $cropW) / 2.0)
    $y = [int][Math]::Floor(($SourceHeight - $cropH) / 2.0)

    return [pscustomobject]@{
        Width     = $cropW
        Height    = $cropH
        X         = $x
        Y         = $y
        Geometry  = "${cropW}x${cropH}+${x}+${y}"
        K         = $k
    }
}

function Test-Magick {
    $cmd = Get-Command magick -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "ImageMagick 'magick' not on PATH. Install: winget install --id ImageMagick.ImageMagick -e"
    }
}

try {
    Test-Magick

    $repoRoot = Get-RepoRoot
    if (-not $SourceDir) { $SourceDir = $repoRoot }
    if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot 'avatars' }

    $SourceDir = (Resolve-Path $SourceDir).Path
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir | Out-Null
    }
    $OutputDir = (Resolve-Path $OutputDir).Path

    if (($Width / 7) -ne ($Height / 9)) {
        throw "Output ${Width}x${Height} is not 7:9 (codec avatars must be 140x180 or a 7:9 multiple)."
    }

    Write-Verbose "SourceDir=$SourceDir OutputDir=$OutputDir Size=${Width}x${Height}"

    foreach ($name in $File) {
        $src = Join-Path $SourceDir $name
        if (-not (Test-Path $src)) {
            throw "Source not found: $src"
        }

        # ImageMagick treats '\' as an escape; use POSIX paths.
        $srcIm = $src.Replace('\', '/')
        $ident = & magick identify -format '%w %h' $srcIm
        $parts = $ident.Trim() -split '\s+'
        $sw = [int]$parts[0]
        $sh = [int]$parts[1]
        $crop = Get-LargestSevenByNineCrop -SourceWidth $sw -SourceHeight $sh

        $dst = Join-Path $OutputDir $name
        $dstIm = $dst.Replace('\', '/')
        Write-Host "$name  ${sw}x${sh}  crop $($crop.Geometry)  ->  ${Width}x${Height}"

        & magick $srcIm `
            -crop $crop.Geometry +repage `
            -filter Lanczos `
            -resize "${Width}x${Height}!" `
            -unsharp '0x0.6+0.6+0.02' `
            -colorspace sRGB `
            -quality 95 `
            -strip `
            $dstIm

        if ($LASTEXITCODE -ne 0) {
            throw "magick failed on $name (exit $LASTEXITCODE)"
        }

        $outIdent = & magick identify -format '%wx%h %m %[colorspace] %Q' $dstIm
        $outSize = (& magick identify -format '%wx%h' $dstIm).Trim()
        if ($outSize -ne "${Width}x${Height}") {
            throw "Output $dst is $outSize, expected ${Width}x${Height}"
        }
        Write-Host "  ok  $outIdent  $dst"
    }
}
catch {
    Write-Error "crop-codec-avatars failed: $_"
    exit 1
}
