param(
    [string]$ImageName = "ghcr.io/wolf575/tg-forward-hub:latest",
    [string]$ContainerName = "tg-forward-hub",
    [int]$Port = 10000,
    [string]$DataDir = (Join-Path $PSScriptRoot "data"),
    [string]$DownloadsDir = (Join-Path $PSScriptRoot "downloads")
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $DataDir, $DownloadsDir | Out-Null

docker rm -f $ContainerName 2>$null | Out-Null

docker run -d `
    --name $ContainerName `
    --restart unless-stopped `
    -p "${Port}:10000" `
    -v "${DataDir}:/app/data" `
    -v "${DownloadsDir}:/app/downloads" `
    -e DATA_DIR=/app/data `
    -e PORT=10000 `
    -e TZ=Asia/Shanghai `
    $ImageName

Write-Host "TG Forward Hub is running at http://localhost:$Port"
Write-Host "Open the page and finish Telegram setup in the web UI."
Write-Host "Use 'docker logs -f $ContainerName' to view logs."
