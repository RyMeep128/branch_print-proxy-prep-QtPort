$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root "Launch Print Proxy Prep.cmd"
$exe = Join-Path $root "dist\Print Proxy Prep\Print Proxy Prep.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Print Proxy Prep.lnk"

if (Test-Path $exe) {
    $targetPath = $exe
    $workingDirectory = Split-Path -Parent $exe
}
elseif (Test-Path $launcher) {
    $targetPath = $launcher
    $workingDirectory = $root
}
else {
    throw "Neither launcher nor built EXE was found."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $workingDirectory

$iconCandidate = Join-Path $root "proxy.png"
if (Test-Path $iconCandidate) {
    $shortcut.IconLocation = $iconCandidate
}

$shortcut.Save()

Write-Host ""
Write-Host "Created desktop shortcut:"
Write-Host "  $shortcutPath"
Write-Host ""
Read-Host "Press Enter to close"
