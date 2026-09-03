param(
    [string]$ImageName = "tg-forward-hub",
    [string]$ContainerName = "tg-forward-hub",
    [int]$Port = 10000,
    [string]$DataDir = (Join-Path $PSScriptRoot "data"),
    [string]$DownloadsDir = (Join-Path $PSScriptRoot "downloads")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".env"))) {
    throw "Missing .env file. Copy .env.example to .env and fill in your Telegram credentials first."
}

New-Item -ItemType Directory -Force -Path $DataDir, $DownloadsDir | Out-Null

docker build -t $ImageName $PSScriptRoot

docker rm -f $ContainerName 2>$null | Out-Null

docker run -d `
    --name $ContainerName `
    --restart unless-stopped `
    -p "${Port}:10000" `
    -v "${DataDir}:/app/data" `
    -v "${DownloadsDir}:/app/downloads" `
    --env-file (Join-Path $PSScriptRoot ".env") `
    -e DATA_DIR=/app/data `
    -e PORT=10000 `
    -e TZ=Asia/Shanghai `
    $ImageName

Write-Host "TG Forward Hub is running at http://localhost:$Port"
Write-Host "Use 'docker logs -f $ContainerName' to view logs."
