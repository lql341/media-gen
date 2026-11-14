# media-gen configuration entry point for Windows PowerShell.
#
# Same interactive wizard as macOS/Linux (scripts/wizard.py) — Windows has no
# system credential store here, so the wizard offers the 0600-file fallback or
# environment variables (MEDIA_API_KEY / MEDIA_API_KEY_<PROFILE>).
#
#   .\scripts\setup.ps1                         interactive wizard
#   .\scripts\setup.ps1 add <name> --protocol openai --base-url https://host/v1
#   .\scripts\setup.ps1 list | show <name> | audit | status | doctor
#   .\scripts\setup.ps1 set-url <name> --base-url https://host/v1
#   .\scripts\setup.ps1 set-key <name>          (key on stdin, never in argv)
#   .\scripts\setup.ps1 rename <old> <new> | rm <name> | rm --all
#   .\scripts\setup.ps1 export | import <file>
#   .\scripts\setup.ps1 mcp                     print MCP registration for GUI clients
#
# Requires Python 3.9+ ("python", "py -3" or full path via $env:MEDIA_PYTHON).

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-Python {
    if ($env:MEDIA_PYTHON) { return $env:MEDIA_PYTHON }
    foreach ($candidate in @('python3', 'python', 'py')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) {
            if ($candidate -eq 'py') { return @('py', '-3') }
            return @($found.Source)
        }
    }
    throw '未找到 python3：安装 Python 3.9+，或用 $env:MEDIA_PYTHON 指向解释器'
}

$python = Resolve-Python
$exe = $python[0]
$pre = @()
if ($python.Count -gt 1) { $pre = $python[1..($python.Count - 1)] }

$action = ''
if ($Args -and $Args.Count -gt 0) { $action = $Args[0] }

$wizard = Join-Path $here 'wizard.py'
$config = Join-Path $here 'media_config.py'
$media = Join-Path $here 'media.py'

switch ($action) {
    ''            { & $exe @pre $wizard; break }
    'mcp'         { & $exe @pre $wizard mcp; break }
    'modify'      { & $exe @pre $wizard modify; break }
    'custom'      { & $exe @pre $wizard custom; break }
    'doctor'      { & $exe @pre $media doctor @($Args | Select-Object -Skip 1); break }
    'status'      { & $exe @pre $config status @($Args | Select-Object -Skip 1); break }
    'add'         { & $exe @pre $config add @($Args | Select-Object -Skip 1); break }
    'set-key'     { & $exe @pre $config set-key @($Args | Select-Object -Skip 1); break }
    'set-url'     { & $exe @pre $config set-url @($Args | Select-Object -Skip 1); break }
    'set-protocol'{ & $exe @pre $config set-protocol @($Args | Select-Object -Skip 1); break }
    { $_ -in @('list', 'show', 'audit', 'rm', 'rename', 'use', 'export', 'import', 'migrate') } {
        & $exe @pre $config $action @($Args | Select-Object -Skip 1); break
    }
    default {
        Write-Host '用法：setup.ps1 [add|custom|modify|list|show|audit|status|doctor|set-url|set-key|set-protocol|rename|rm|export|import|migrate|mcp]'
        Write-Host '不带参数进入交互向导。'
        exit 2
    }
}
exit $LASTEXITCODE
