<# 
  setup_env.ps1 (versión robusta)
  1) Activa (o crea si falta) el venv
  2) Instala -r requirements.txt:
     - Si el requirements tiene "+cuXYZ", usa índice PyTorch para ese canal
     - Si no, instala normal (CPU por defecto)
  3) Si detecta nvidia-smi, upgrade automático a +cu124 / +cu121 / +cu118 según driver
  4) Test de CUDA y faster-whisper (con archivo temporal)
#>

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-StrictMode -Version Latest

Write-Host "==> Iniciando script de preparación del entorno..." -ForegroundColor Cyan

# --- Ubicación del proyecto (donde está este .ps1) ---
$ProjectRoot = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $ProjectRoot
Write-Host "Proyecto: $ProjectRoot" -ForegroundColor DarkCyan

# --- Paths del venv ---
$VenvPath = Join-Path $ProjectRoot "venv"
$Py     = Join-Path $VenvPath "Scripts\python.exe"
$Pip    = Join-Path $VenvPath "Scripts\pip.exe"
$ActPS1 = Join-Path $VenvPath "Scripts\Activate.ps1"

# --- Crear venv si no existe ---
if (!(Test-Path $Py)) {
  Write-Host "No se encontró venv. Creando venv..." -ForegroundColor Yellow
  try {
    & py -3.11 -m venv $VenvPath
  } catch {
    Write-Host "No se encontró 'py -3.11'. Probando con 'python' del sistema..." -ForegroundColor Yellow
    & python -m venv $VenvPath
  }
}

# --- Activar venv ---
if (Test-Path $ActPS1) {
  Write-Host "Activando venv..." -ForegroundColor Cyan
  . $ActPS1
} else {
  throw "No se pudo activar el venv (no existe $ActPS1)."
}

# --- Asegurar pip/wheel/setuptools actualizados ---
Write-Host "Actualizando pip/wheel/setuptools..." -ForegroundColor Cyan
& $Py -m pip install --upgrade pip wheel setuptools

# --- 2) Instalar dependencias desde requirements.txt ---
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
$ReqChannel = $null   # cu124/cu121/cu118 si viene fijado en requirements

if (Test-Path $ReqFile) {
  $reqText = Get-Content $ReqFile -Raw
  $reqMatch = [regex]::Match($reqText, '\+cu(\d+)')
  $hasCu = $reqMatch.Success
  if ($hasCu) { $ReqChannel = "cu$($reqMatch.Groups[1].Value)" }

  if ($hasCu -and $ReqChannel) {
    Write-Host "requirements.txt contiene wheels CUDA (+$ReqChannel). Usando índice de PyTorch..." -ForegroundColor Cyan
    & $Py -m pip install --extra-index-url ("https://download.pytorch.org/whl/{0}" -f $ReqChannel) -r $ReqFile
  } else {
    Write-Host "Instalando dependencias desde requirements.txt (CPU por defecto)..." -ForegroundColor Cyan
    & $Py -m pip install -r $ReqFile
  }
} else {
  Write-Host "ADVERTENCIA: No existe requirements.txt en $ProjectRoot" -ForegroundColor Yellow
}

# --- 3) Si hay NVIDIA, autodetectar canal recomendado y hacer upgrade a builds CUDA ---
$HasNvidia = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$CudaChannel = $null  # cu124 / cu121 / cu118

if ($HasNvidia) {
  Write-Host "Detectado 'nvidia-smi'. Autodetectando canal CUDA recomendado..." -ForegroundColor Cyan

  try {
    $smi = & nvidia-smi
    $cudaVerMatch = Select-String -InputObject $smi -Pattern 'CUDA Version:\s*([\d\.]+)' | Select-Object -First 1
    if ($cudaVerMatch) {
      $verStr = $cudaVerMatch.Matches[0].Groups[1].Value
      Write-Host "Driver soporta CUDA runtime: $verStr" -ForegroundColor DarkCyan

      $v = [version]$verStr
      if ($v.Major -ge 12 -and $v.Minor -ge 4) {
        $CudaChannel = "cu124"
      } elseif ($v.Major -ge 12 -and $v.Minor -ge 1) {
        $CudaChannel = "cu121"
      } elseif ($v.Major -eq 11 -and $v.Minor -ge 8) {
        $CudaChannel = "cu118"
      } else {
        Write-Host "Runtime CUDA poco común; usando cu121 por defecto." -ForegroundColor Yellow
        $CudaChannel = "cu121"
      }
    } else {
      Write-Host "No se pudo leer la versión CUDA del driver. Usando cu121 por defecto." -ForegroundColor Yellow
      $CudaChannel = "cu121"
    }
  } catch {
    Write-Host "Error ejecutando nvidia-smi: $_. Usando cu121 por defecto." -ForegroundColor Yellow
    $CudaChannel = "cu121"
  }

  Write-Host "Intentando actualizar a builds CUDA (+$CudaChannel)..." -ForegroundColor Cyan

  # === Bloque robusto para leer versiones instaladas (sin depender de 'import torch') ===
  $pyQuery = @'
import json, importlib.util
try:
    import importlib.metadata as im  # py3.8+
except Exception:
    im = None

def is_installed(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

def ver(name):
    if im is None:
        return None
    try:
        return im.version(name)
    except Exception:
        return None

out = {}
for pkg in ("torch","torchvision","torchaudio"):
    out[pkg] = ver(pkg) if is_installed(pkg) else None

print(json.dumps(out))
'@

  $versJson = $null
  try {
    $versJson = & $Py -c $pyQuery 2>$null
  } catch {
    $versJson = $null
  }

  $vers = @{}
  try {
    if ($versJson) { $vers = $versJson | ConvertFrom-Json }
  } catch {
    $vers = @{}
  }

  function Add-Cu([string]$v, [string]$suffix) {
    if (-not $v) { return $null }
    if ($v -match '\+cu\d+') { return $v }  # ya tiene sufijo CUDA
    return "$v+$suffix"
  }

  $torchVer       = $null
  $torchvisionVer = $null
  $torchaudioVer  = $null

  if ($vers -is [hashtable]) {
    $torchVer       = $vers["torch"]
    $torchvisionVer = $vers["torchvision"]
    $torchaudioVer  = $vers["torchaudio"]
  } elseif ($vers.PSObject) {
    if ($vers.PSObject.Properties.Name -contains "torch")       { $torchVer       = $vers.torch }
    if ($vers.PSObject.Properties.Name -contains "torchvision") { $torchvisionVer = $vers.torchvision }
    if ($vers.PSObject.Properties.Name -contains "torchaudio")  { $torchaudioVer  = $vers.torchaudio }
  }

  $torchSpec       = if ($torchVer)       { "torch==$((Add-Cu $torchVer $CudaChannel))" } else { $null }
  $torchvisionSpec = if ($torchvisionVer) { "torchvision==$((Add-Cu $torchvisionVer $CudaChannel))" } else { $null }
  $torchaudioSpec  = if ($torchaudioVer)  { "torchaudio==$((Add-Cu $torchaudioVer $CudaChannel))" } else { $null }

  $targets = @()
  if ($torchSpec)       { $targets += $torchSpec }
  if ($torchvisionSpec) { $targets += $torchvisionSpec }
  if ($torchaudioSpec)  { $targets += $torchaudioSpec }

  $indexUrl = "https://download.pytorch.org/whl/$CudaChannel"

  try {
    if ($targets.Count -gt 0) {
      Write-Host "Actualizando a: $($targets -join ', ')" -ForegroundColor DarkCyan
      & $Py -m pip install --index-url $indexUrl --upgrade --no-cache-dir @targets
    } else {
      Write-Host "No hay versiones previas detectadas; instalando builds CUDA por defecto..." -ForegroundColor Yellow
      & $Py -m pip install --index-url $indexUrl --upgrade --no-cache-dir torch torchvision torchaudio
    }
  } catch {
    Write-Host "Falló el upgrade con versiones fijadas. Intentando upgrade genérico a +$CudaChannel..." -ForegroundColor Yellow
    & $Py -m pip install --index-url $indexUrl --upgrade --no-cache-dir torch torchvision torchaudio
  }
} else {
  Write-Host "No se detectó 'nvidia-smi'. Se mantiene instalación CPU." -ForegroundColor Yellow
}

# --- 4) Test de CUDA y faster-whisper ---
Write-Host "`n==> Prueba rápida de PyTorch / CUDA / faster-whisper..." -ForegroundColor Cyan

$testCode = @'
import sys

def p(msg): 
    print(msg); sys.stdout.flush()

# --- Torch / CUDA ---
try:
    import torch
    p(f"torch: {torch.__version__}")
    p(f"torch.version.cuda: {getattr(torch.version, 'cuda', None)}")
    p(f"cuda.is_available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        try:
            p(f"cuda device: {torch.cuda.get_device_name(0)}")
        except Exception as e:
            p(f"cuda device: (error al consultar) {e}")
except Exception as e:
    p(f"ERROR importando torch: {e}")

# --- faster-whisper ---
try:
    from faster_whisper import WhisperModel
    device = "cuda" if ('torch' in globals() and torch.cuda.is_available()) else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    model = WhisperModel("tiny", device=device, compute_type=compute_type)
    p(f"faster-whisper OK (device={device}, compute_type={compute_type})")
except Exception as e:
    p(f"ERROR en faster-whisper: {e}")
'@

$tempPy = Join-Path $env:TEMP ("torch_test_{0}.py" -f ([guid]::NewGuid().ToString("N")))
Set-Content -Path $tempPy -Value $testCode -Encoding UTF8

try {
  & $Py $tempPy
} finally {
  Remove-Item $tempPy -Force -ErrorAction SilentlyContinue
}

Write-Host "`n==> Listo. Revisa los mensajes anteriores para confirmar CUDA/faster-whisper." -ForegroundColor Green