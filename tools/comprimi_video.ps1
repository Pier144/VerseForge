# Re-encode an MP4 to H.264 at a given bitrate with Windows' built-in Media Foundation transcoder (no ffmpeg needed).
# Usage: powershell -ExecutionPolicy Bypass -File comprimi_video.ps1 -In input.mp4 -Out output.mp4 [-Kbps 4000]
param(
    [Parameter(Mandatory = $true)][string]$In,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Kbps = 4000,
    [int]$Width = 1600,
    [int]$Height = 900
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Transcoding.MediaTranscoder, Windows.Media.Transcoding, ContentType = WindowsRuntime]
$null = [Windows.Media.MediaProperties.MediaEncodingProfile, Windows.Media.MediaProperties, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait() | Out-Null
    $task.Result
}
$asTaskProgress = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncActionWithProgress`1' })[0]
function AwaitActionProgress($op, [Type]$ptype) {
    $task = $asTaskProgress.MakeGenericMethod($ptype).Invoke($null, @($op))
    $task.Wait() | Out-Null
}

$inPath = (Resolve-Path $In).Path
$outDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($Out))
$outName = Split-Path -Leaf $Out
$src = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($inPath)) ([Windows.Storage.StorageFile])
$folder = Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($outDir)) ([Windows.Storage.StorageFolder])
$dst = Await ($folder.CreateFileAsync($outName, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])

$profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateMp4([Windows.Media.MediaProperties.VideoEncodingQuality]::HD1080p)
$profile.Audio = $null
$profile.Video.Width = $Width
$profile.Video.Height = $Height
$profile.Video.Bitrate = [uint32]($Kbps * 1000)
$profile.Video.FrameRate.Numerator = 30
$profile.Video.FrameRate.Denominator = 1

$transcoder = New-Object Windows.Media.Transcoding.MediaTranscoder
$transcoder.HardwareAccelerationEnabled = $true
$prep = Await ($transcoder.PrepareFileTranscodeAsync($src, $dst, $profile)) ([Windows.Media.Transcoding.PrepareTranscodeResult])
if (-not $prep.CanTranscode) { throw "Transcodifica non possibile: $($prep.FailureReason)" }
AwaitActionProgress ($prep.TranscodeAsync()) ([double])
"OK $((Get-Item $Out).Length) byte"
