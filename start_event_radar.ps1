param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8089,
    [string]$EnvFile = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$jobApi = @"
using System;
using System.Runtime.InteropServices;

public static class EventRadarJobObject {
    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public long Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetInformationJobObject(
        IntPtr hJob,
        int infoType,
        IntPtr lpJobObjectInfo,
        uint cbJobObjectInfoLength
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    public static IntPtr CreateKillOnCloseJob() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) {
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
        }

        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>();
        IntPtr buffer = Marshal.AllocHGlobal(length);
        try {
            Marshal.StructureToPtr(info, buffer, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, buffer, (uint)length)) {
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "SetInformationJobObject failed");
            }
        } finally {
            Marshal.FreeHGlobal(buffer);
        }

        return job;
    }
}
"@

if (-not ("EventRadarJobObject" -as [type])) {
    Add-Type -TypeDefinition $jobApi
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$ReadyMarker = Join-Path $VenvDir ".event_radar_python_ready"
$jobHandle = [IntPtr]::Zero
$childProcess = $null

if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $DefaultEnvFile = Join-Path $ProjectRoot "config\env.sh"
    if (Test-Path $DefaultEnvFile) {
        $EnvFile = $DefaultEnvFile
    }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python launcher not found. Install Python or ensure `py` or `python` is on PATH."
}

function New-EventRadarVenv {
    if (Test-Path $VenvDir) {
        Write-Host "Rebuilding Python virtual environment..."
        Remove-Item -Recurse -Force $VenvDir
    }
    else {
        Write-Host "Creating Python virtual environment..."
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $VenvDir
        if ($LASTEXITCODE -eq 0 -and (Test-Path $PythonExe)) {
            return
        }
    }

    if (Test-Path $VenvDir) {
        Remove-Item -Recurse -Force $VenvDir
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $VenvDir
        if ($LASTEXITCODE -eq 0 -and (Test-Path $PythonExe)) {
            return
        }
    }

    throw "Failed to create virtual environment at $VenvDir. Try running `py -3 -m venv `"$VenvDir`"` manually."
}

if (-not (Test-Path $PythonExe)) {
    New-EventRadarVenv
}

if (-not (Test-Path $PythonExe)) {
    throw "Virtual environment is missing python.exe at $PythonExe"
}

if (-not $SkipInstall -or -not (Test-Path $ReadyMarker) -or ((Get-Item (Join-Path $ProjectRoot "pyproject.toml")).LastWriteTimeUtc -gt (Get-Item $ReadyMarker).LastWriteTimeUtc)) {
    & $PythonExe -m pip install -U pip
    & $PythonExe -m pip install -e "$ProjectRoot[dev]"
    Set-Content -Path $ReadyMarker -Value (Get-Date).ToString("o") -NoNewline
}

if (-not (Test-Path (Join-Path $ProjectRoot "event_radar\static\app\index.html"))) {
    throw "Built frontend assets are missing. Copy event_radar\static\app or build the frontend first."
}

if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
    $env:EVENT_RADAR_ENV_FILE = $EnvFile
}

Write-Host ""
Write-Host "Starting Event Radar..."
Write-Host "Project: $ProjectRoot"
if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
    Write-Host "Env file: $EnvFile"
}
Write-Host "URL: http://$HostAddress`:$Port/"
Write-Host ""

Set-Location $ProjectRoot
$jobHandle = [EventRadarJobObject]::CreateKillOnCloseJob()

try {
    $childProcess = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "event_radar.main:app", "--host", $HostAddress, "--port", "$Port") `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -PassThru

    if (-not [EventRadarJobObject]::AssignProcessToJobObject($jobHandle, $childProcess.Handle)) {
        throw "AssignProcessToJobObject failed for PID $($childProcess.Id)"
    }

    $childProcess.WaitForExit()
    exit $childProcess.ExitCode
}
finally {
    if ($jobHandle -ne [IntPtr]::Zero) {
        [EventRadarJobObject]::CloseHandle($jobHandle) | Out-Null
    }
}
