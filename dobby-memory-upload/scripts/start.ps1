<#
.SYNOPSIS
    Dobby 项目一键启动脚本

.DESCRIPTION
    使用 Docker Compose 启动 Dobby 全部服务。
    支持可选 profile：neo4j, weknora。

.PARAMETER Profile
    可选服务配置：neo4j, weknora, all

.PARAMETER Build
    启动前强制重新构建镜像

.PARAMETER Stop
    停止所有服务

.PARAMETER Logs
    查看指定服务的日志

.PARAMETER Status
    显示服务运行状态

.EXAMPLE
    .\scripts\start.ps1                    # 启动核心服务
    .\scripts\start.ps1 -Profile neo4j    # 启动 + Neo4j
    .\scripts\start.ps1 -Profile all      # 启动全部
    .\scripts\start.ps1 -Build            # 重新构建并启动
    .\scripts\start.ps1 -Stop             # 停止所有服务
    .\scripts\start.ps1 -Logs web         # 查看 Web 服务日志
    .\scripts\start.ps1 -Status           # 查看服务状态
#>

param(
    [ValidateSet("neo4j", "weknora", "all", "")]
    [string]$Profile = "",

    [switch]$Build,

    [switch]$Stop,

    [string]$Logs = "",

    [switch]$Status
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

# ── Ensure .env exists ──
if (-not (Test-Path ".env")) {
    Write-Host "⚠️  .env file not found. Copying from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️  Please edit .env and set DEEPSEEK_API_KEY, then re-run." -ForegroundColor Red
    exit 1
}

# ── Check .env has API key ──
$envContent = Get-Content ".env" -Raw
if ($envContent -match "DEEPSEEK_API_KEY=sk-your-deepseek-key-here") {
    Write-Host "⚠️  DEEPSEEK_API_KEY not configured in .env!" -ForegroundColor Red
    Write-Host "   Edit .env and set your actual API key." -ForegroundColor Yellow
    exit 1
}

# ── Build compose args ──
$composeArgs = @()

if ($Profile -eq "neo4j") {
    $composeArgs += "--profile", "neo4j"
} elseif ($Profile -eq "weknora") {
    $composeArgs += "--profile", "weknora"
} elseif ($Profile -eq "all") {
    $composeArgs += "--profile", "neo4j", "--profile", "weknora"
}

# ── Execute ──
if ($Stop) {
    Write-Host "🛑 Stopping all Dobby services..." -ForegroundColor Yellow
    docker compose @composeArgs down
    Write-Host "✅ All services stopped." -ForegroundColor Green
    exit 0
}

if ($Status) {
    Write-Host "📊 Dobby Service Status" -ForegroundColor Cyan
    Write-Host "=" * 40
    docker compose @composeArgs ps
    exit 0
}

if ($Logs) {
    Write-Host "📋 Logs for: $Logs (Ctrl+C to exit)" -ForegroundColor Cyan
    docker compose @composeArgs logs -f $Logs
    exit 0
}

# ── Build (optional) ──
if ($Build) {
    Write-Host "🔨 Building Docker images..." -ForegroundColor Cyan
    docker compose @composeArgs build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Build failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Build complete." -ForegroundColor Green
}

# ── Start ──
Write-Host "🚀 Starting Dobby services..." -ForegroundColor Cyan
if ($composeArgs.Count -gt 0) {
    Write-Host "   Profiles: $($composeArgs -join ' ')" -ForegroundColor Gray
}

docker compose @composeArgs up -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to start services!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=" * 50 -ForegroundColor Green
Write-Host "✅ Dobby is starting!" -ForegroundColor Green
Write-Host "=" * 50 -ForegroundColor Green
Write-Host ""
Write-Host "  Web 界面:     http://localhost:7860"
if ($Profile -eq "neo4j" -or $Profile -eq "all") {
    Write-Host "  Neo4j Browser: http://localhost:7474"
}
Write-Host ""
Write-Host "  查看日志:     docker compose @composeArgs logs -f"
Write-Host "  停止服务:     .\scripts\start.ps1 -Stop"
Write-Host "  服务状态:     .\scripts\start.ps1 -Status"
Write-Host ""
Write-Host "⏳ 等待服务就绪（约 10 秒）..."
Write-Host ""

# Wait for web service to be healthy
$retries = 0
$maxRetries = 12
do {
    Start-Sleep -Seconds 5
    $retries++
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:7860" -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ Web 界面已就绪！打开 http://localhost:7860" -ForegroundColor Green
            break
        }
    } catch {
        Write-Host "⏳ 等待中... ($retries/$maxRetries)" -ForegroundColor Gray
    }
} while ($retries -lt $maxRetries)

if ($retries -ge $maxRetries) {
    Write-Host "⚠️  Web 服务启动超时，请检查日志: docker compose logs web" -ForegroundColor Yellow
}
