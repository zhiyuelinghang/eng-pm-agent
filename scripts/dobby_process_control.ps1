[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("StopPorts", "RegisterPorts")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$Ports,

    [ValidateRange(0, 300)]
    [int]$WaitSeconds = 0,

    [switch]$Quiet,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

try {
    $resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd([char[]]@('\', '/'))
}
catch {
    Write-Host "[安全停止] 无法解析项目目录：$ProjectRoot" -ForegroundColor Red
    exit 1
}

$portList = @(
    $Ports.Split(",", [System.StringSplitOptions]::RemoveEmptyEntries) |
        ForEach-Object {
            $parsedPort = 0
            if (-not [int]::TryParse($_.Trim(), [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
                throw "无效端口：$_"
            }
            $parsedPort
        } |
        Sort-Object -Unique
)

if ($portList.Count -eq 0) {
    Write-Host "[安全停止] 未提供需要处理的端口。" -ForegroundColor Red
    exit 1
}

$portRules = @{
    38429 = @{
        Role = "平台前端"
        Names = @("python.exe", "pythonw.exe", "node.exe")
        Tokens = @("\frontend\", "/frontend/", "dobby_web_gateway.py")
    }
    38430 = @{
        Role = "平台后端"
        Names = @("python.exe", "pythonw.exe")
        Tokens = @("app.main:app", "\backend\", "/backend/")
    }
    38431 = @{
        Role = "群聊实时服务"
        Names = @("centrifugo.exe")
        Tokens = @("centrifugo", "runtime\centrifugo", "runtime/centrifugo")
    }
    18642 = @{
        Role = "AgentScope API"
        Names = @("python.exe", "pythonw.exe")
        Tokens = @("scripts.agentscope_dev_app:app", "agentscope_dev_runner.py")
    }
    25173 = @{
        Role = "Dobby 管理端"
        Names = @("python.exe", "pythonw.exe", "node.exe")
        Tokens = @("agentscope-web-ui", "dobby_web_gateway.py")
    }
    23000 = @{
        Role = "AgentScope Web UI 辅助服务"
        Names = @("node.exe")
        Tokens = @("agentscope-web-ui")
    }
}

$protectedNames = @(
    "system",
    "registry",
    "explorer.exe",
    "dwm.exe",
    "winlogon.exe",
    "csrss.exe",
    "lsass.exe",
    "services.exe",
    "svchost.exe",
    "sihost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "searchhost.exe",
    "taskmgr.exe",
    "windowsterminal.exe",
    "conhost.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe"
)

$auditDirectory = Join-Path $resolvedProjectRoot "data\runtime"
$auditPath = Join-Path $auditDirectory "process-control.log"
$registryPath = Join-Path $auditDirectory "dobby-service-pids.json"

function Write-Audit {
    param(
        [string]$Level,
        [string]$Message
    )

    try {
        if (-not (Test-Path -LiteralPath $auditDirectory)) {
            New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        }
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
        Add-Content -LiteralPath $auditPath -Encoding UTF8 -Value "$timestamp [$Level] $Message"
    }
    catch {
        if (-not $Quiet) {
            Write-Host "[安全停止] 无法写入审计日志，但不会放宽进程校验：$($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

function Get-ListeningProcessIds {
    param([int]$Port)

    # Get-NetTCPConnection 在部分标准用户会话中会返回“拒绝访问”；
    # netstat 只读取系统连接表，不需要提升权限，也不会更改任何进程。
    $escapedPort = [regex]::Escape([string]$Port)
    return @(
        & "$env:SystemRoot\System32\netstat.exe" -ano -p tcp |
            ForEach-Object {
                if ($_ -match "^\s*TCP\s+\S+:$escapedPort\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                    [int]$Matches[1]
                }
            } |
            Where-Object { $_ -gt 0 } |
            Sort-Object -Unique
    )
}

function Get-ProcessRecord {
    param([int]$ProcessId)

    if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {
        try {
            $cimRecord = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
            if ($cimRecord) {
                $creationTime = $null
                if ($cimRecord.CreationDate -is [datetime]) {
                    $creationTime = $cimRecord.CreationDate.ToUniversalTime()
                }
                return [pscustomobject]@{
                    ProcessId = [int]$cimRecord.ProcessId
                    Name = [string]$cimRecord.Name
                    ExecutablePath = [string]$cimRecord.ExecutablePath
                    CommandLine = [string]$cimRecord.CommandLine
                    StartKey = if ($creationTime) { $creationTime.Ticks } else { 0 }
                }
            }
        }
        catch {
            # 标准用户可能无权访问 Win32_Process；继续使用 Get-Process 的只读信息。
        }
    }

    $nativeProcess = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $nativeProcess) {
        return $null
    }

    try {
        $processName = [string]$nativeProcess.ProcessName
        if (-not $processName.EndsWith(".exe", [System.StringComparison]::OrdinalIgnoreCase)) {
            $processName += ".exe"
        }
        return [pscustomobject]@{
            ProcessId = [int]$nativeProcess.Id
            Name = $processName
            ExecutablePath = [string]$nativeProcess.Path
            CommandLine = ""
            StartKey = $nativeProcess.StartTime.ToUniversalTime().Ticks
        }
    }
    catch {
        return $null
    }
}

function Read-ServiceRegistry {
    if (-not (Test-Path -LiteralPath $registryPath)) {
        return @()
    }

    try {
        $content = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($content)) {
            return @()
        }
        $document = $content | ConvertFrom-Json
        return @($document.Services)
    }
    catch {
        Write-Audit -Level "WARN" -Message "service registry unreadable; ignored: $($_.Exception.Message)"
        return @()
    }
}

function Write-ServiceRegistry {
    param([object[]]$Services)

    if (-not (Test-Path -LiteralPath $auditDirectory)) {
        New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
    }

    $document = [ordered]@{
        Version = 1
        ProjectRoot = $resolvedProjectRoot
        UpdatedAt = (Get-Date).ToUniversalTime().ToString("o")
        Services = @($Services | Sort-Object Port)
    }
    $temporaryPath = "$registryPath.$PID.tmp"
    try {
        $document | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $registryPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Remove-ServiceRegistryPorts {
    param([int[]]$RemovedPorts)

    $remainingEntries = @(
        Read-ServiceRegistry | Where-Object { $RemovedPorts -notcontains [int]$_.Port }
    )
    Write-ServiceRegistry -Services $remainingEntries
}

function Test-PathInsideProject {
    param([string]$CandidatePath)

    if ([string]::IsNullOrWhiteSpace($CandidatePath)) {
        return $false
    }

    try {
        $resolvedCandidate = [System.IO.Path]::GetFullPath($CandidatePath).TrimEnd([char[]]@('\', '/'))
        if ($resolvedCandidate.Equals($resolvedProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
        $rootPrefix = $resolvedProjectRoot + [System.IO.Path]::DirectorySeparatorChar
        return $resolvedCandidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

function Test-CommandContains {
    param(
        [string]$CommandLine,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine) -or [string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    return $CommandLine.IndexOf($Value, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Test-DobbyServiceProcess {
    param(
        [int]$Port,
        $Record
    )

    if (-not $portRules.ContainsKey($Port)) {
        return [pscustomobject]@{
            Accepted = $false
            Role = "未知服务"
            Reason = "端口不在 Dobby 服务白名单中"
        }
    }

    $rule = $portRules[$Port]
    $processName = ([string]$Record.Name).ToLowerInvariant()
    if ($protectedNames -contains $processName) {
        return [pscustomobject]@{
            Accepted = $false
            Role = $rule.Role
            Reason = "命中系统与终端进程保护名单"
        }
    }

    if ($rule.Names -notcontains $processName) {
        return [pscustomobject]@{
            Accepted = $false
            Role = $rule.Role
            Reason = "进程名不属于该服务允许的程序"
        }
    }

    foreach ($registered in @($script:registeredServices)) {
        if ([int]$registered.Port -ne $Port -or [int]$registered.ProcessId -ne [int]$Record.ProcessId) {
            continue
        }

        $sameName = ([string]$registered.Name).Equals(
            [string]$Record.Name,
            [System.StringComparison]::OrdinalIgnoreCase
        )
        $samePath = ([string]$registered.ExecutablePath).Equals(
            [string]$Record.ExecutablePath,
            [System.StringComparison]::OrdinalIgnoreCase
        )
        $sameStart = [long]$registered.StartKey -gt 0 -and
            [long]$registered.StartKey -eq [long]$Record.StartKey
        if ($sameName -and $samePath -and $sameStart) {
            return [pscustomobject]@{
                Accepted = $true
                Role = $rule.Role
                Reason = "PID、启动时间和可执行文件均与启动登记一致"
            }
        }
    }

    $commandLine = [string]$Record.CommandLine
    $pathInsideProject = Test-PathInsideProject -CandidatePath ([string]$Record.ExecutablePath)
    if ($pathInsideProject) {
        return [pscustomobject]@{
            Accepted = $true
            Role = $rule.Role
            Reason = "可执行文件位于当前项目目录且进程名符合服务白名单"
        }
    }

    $commandReferencesProject = Test-CommandContains -CommandLine $commandLine -Value $resolvedProjectRoot
    if (-not $commandReferencesProject) {
        return [pscustomobject]@{
            Accepted = $false
            Role = $rule.Role
            Reason = "可执行文件和命令行都不属于当前项目目录"
        }
    }

    $roleTokenMatched = $false
    foreach ($token in $rule.Tokens) {
        if ((Test-CommandContains -CommandLine $commandLine -Value $token) -or
            (Test-CommandContains -CommandLine ([string]$Record.ExecutablePath) -Value $token)) {
            $roleTokenMatched = $true
            break
        }
    }

    if (-not $roleTokenMatched) {
        return [pscustomobject]@{
            Accepted = $false
            Role = $rule.Role
            Reason = "命令行不符合该端口对应的 Dobby 服务特征"
        }
    }

    return [pscustomobject]@{
        Accepted = $true
        Role = $rule.Role
        Reason = "已通过项目目录、进程名和服务特征三重校验"
    }
}

function Register-ServicePorts {
    param(
        [int[]]$RequestedPorts,
        [int]$MaximumWaitSeconds
    )

    $deadline = (Get-Date).AddSeconds($MaximumWaitSeconds)
    $newEntries = @()
    $missingPorts = @($RequestedPorts)

    do {
        $newEntries = @()
        $missingPorts = @()

        foreach ($port in $RequestedPorts) {
            $processIds = @(Get-ListeningProcessIds -Port $port)
            if ($processIds.Count -ne 1) {
                $missingPorts += $port
                continue
            }

            $processId = [int]$processIds[0]
            $record = Get-ProcessRecord -ProcessId $processId
            if (-not $record -or -not $portRules.ContainsKey($port)) {
                $missingPorts += $port
                continue
            }

            $rule = $portRules[$port]
            $processName = ([string]$record.Name).ToLowerInvariant()
            if ($protectedNames -contains $processName -or $rule.Names -notcontains $processName) {
                Write-Host "[进程登记] 端口 $port 的进程不符合 $($rule.Role) 程序白名单，拒绝登记。" -ForegroundColor Yellow
                return $false
            }

            $pathInsideProject = Test-PathInsideProject -CandidatePath ([string]$record.ExecutablePath)
            $recentNodeProcess = $false
            if ($processName -eq "node.exe" -and [long]$record.StartKey -gt 0) {
                $startedAt = [datetime]::new([long]$record.StartKey, [System.DateTimeKind]::Utc)
                $recentNodeProcess = ((Get-Date).ToUniversalTime() - $startedAt).TotalMinutes -le 5
            }

            if (-not $pathInsideProject -and -not $recentNodeProcess) {
                Write-Host "[进程登记] 端口 $port 的进程无法证明由当前 Dobby 启动，拒绝登记。" -ForegroundColor Yellow
                return $false
            }

            $newEntries += [pscustomobject]@{
                Port = $port
                Role = $rule.Role
                ProcessId = $processId
                Name = [string]$record.Name
                ExecutablePath = [string]$record.ExecutablePath
                StartKey = [long]$record.StartKey
                RegisteredAt = (Get-Date).ToUniversalTime().ToString("o")
            }
        }

        if ($missingPorts.Count -eq 0) {
            break
        }
        if ((Get-Date) -ge $deadline) {
            break
        }
        Start-Sleep -Milliseconds 250
    } while ($true)

    if ($missingPorts.Count -gt 0) {
        Write-Host "[进程登记] 等待服务端口超时：$($missingPorts -join ', ')。" -ForegroundColor Red
        return $false
    }

    $preservedEntries = @(
        Read-ServiceRegistry | Where-Object { $RequestedPorts -notcontains [int]$_.Port }
    )
    Write-ServiceRegistry -Services @($preservedEntries + $newEntries)
    foreach ($entry in $newEntries) {
        Write-Audit -Level "REGISTER" -Message "role=$($entry.Role) port=$($entry.Port) pid=$($entry.ProcessId)"
        if (-not $Quiet) {
            Write-Host "[进程登记] $($entry.Role)：端口 $($entry.Port)，PID=$($entry.ProcessId)。" -ForegroundColor Green
        }
    }
    return $true
}

function Stop-VerifiedProcess {
    param(
        [int]$ProcessId,
        [string]$Role
    )

    $nativeProcess = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $nativeProcess) {
        return $true
    }

    try {
        $null = $nativeProcess.CloseMainWindow()
        if (-not $nativeProcess.WaitForExit(700)) {
            Stop-Process -InputObject $nativeProcess -Force -ErrorAction Stop
        }
        Write-Audit -Level "STOP" -Message "role=$Role pid=$ProcessId result=stopped"
        return $true
    }
    catch {
        Write-Audit -Level "ERROR" -Message "role=$Role pid=$ProcessId result=failed error=$($_.Exception.Message)"
        Write-Host "[安全停止] 无法结束 $Role，PID=$ProcessId：$($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

$script:registeredServices = @(Read-ServiceRegistry)

if ($Action -eq "RegisterPorts") {
    if ($DryRun) {
        Write-Host "[进程登记] RegisterPorts 不接受 DryRun；未写入登记。" -ForegroundColor Yellow
        exit 1
    }
    if (Register-ServicePorts -RequestedPorts $portList -MaximumWaitSeconds $WaitSeconds) {
        exit 0
    }
    exit 1
}

$hadRefusal = $false
$hadFailure = $false
$reportedDryRun = @{}

for ($attempt = 1; $attempt -le 3; $attempt++) {
    $foundListener = $false

    foreach ($port in $portList) {
        foreach ($processId in @(Get-ListeningProcessIds -Port $port)) {
            $foundListener = $true
            $record = Get-ProcessRecord -ProcessId $processId
            if (-not $record) {
                continue
            }

            $assessment = Test-DobbyServiceProcess -Port $port -Record $record
            $identity = "port=$port pid=$processId name=$($record.Name) path=$($record.ExecutablePath)"
            if (-not $assessment.Accepted) {
                $hadRefusal = $true
                Write-Audit -Level "REFUSE" -Message "$identity reason=$($assessment.Reason)"
                Write-Host "[已阻止] 端口 $port 由非本项目服务占用，未结束进程。" -ForegroundColor Yellow
                Write-Host "          PID=$processId，进程=$($record.Name)"
                Write-Host "          原因：$($assessment.Reason)"
                continue
            }

            if ($DryRun) {
                $dryRunKey = "$port/$processId"
                if (-not $reportedDryRun.ContainsKey($dryRunKey)) {
                    $reportedDryRun[$dryRunKey] = $true
                    Write-Host "[安全检查] $($assessment.Role)：端口 $port，PID=$processId，校验通过；DryRun 未结束。" -ForegroundColor Green
                }
                continue
            }

            if (-not $Quiet) {
                Write-Host "[安全停止] $($assessment.Role)：端口 $port，PID=$processId，身份校验通过。"
            }
            Write-Audit -Level "ALLOW" -Message "$identity role=$($assessment.Role)"
            if (-not (Stop-VerifiedProcess -ProcessId $processId -Role $assessment.Role)) {
                $hadFailure = $true
            }
        }
    }

    if ($DryRun -or -not $foundListener -or $hadRefusal) {
        break
    }

    Start-Sleep -Milliseconds 500
}

if ($DryRun) {
    if (-not $Quiet -and $reportedDryRun.Count -eq 0 -and -not $hadRefusal) {
        Write-Host "[安全检查] 指定端口当前均未监听，无需停止。"
    }
    if ($hadRefusal) {
        exit 2
    }
    exit 0
}

$remainingPorts = @(
    $portList | Where-Object { @(Get-ListeningProcessIds -Port $_).Count -gt 0 }
)
if ($remainingPorts.Count -gt 0 -and -not $hadRefusal) {
    $hadFailure = $true
    Write-Host "[安全停止] 以下端口仍在监听：$($remainingPorts -join ', ')。未扩大查杀范围。" -ForegroundColor Red
}

if ($hadRefusal) {
    Write-Host "[安全停止] 检测到非 Dobby 进程，已保留该进程。请先人工处理端口冲突。" -ForegroundColor Yellow
    exit 2
}

if ($hadFailure) {
    exit 1
}

Remove-ServiceRegistryPorts -RemovedPorts $portList
if (-not $Quiet) {
    Write-Host "[安全停止] 指定的 Dobby 服务端口已全部释放。" -ForegroundColor Green
}
exit 0
