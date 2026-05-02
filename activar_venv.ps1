# Activar entorno o prepararlo si falta (delegar en setup_env.ps1 si existe)
$here = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$venvAct = Join-Path $here "venv\Scripts\Activate.ps1"
$setup = Join-Path $here "setup_env.ps1"

if (Test-Path $setup) {
  Write-Host "Ejecutando setup_env.ps1 para preparar/activar el entorno..." -ForegroundColor Cyan
  & $setup
} elseif (Test-Path $venvAct) {
  Write-Host "Activando venv existente..." -ForegroundColor Cyan
  . $venvAct
} else {
  Write-Host "No se encontró venv ni setup_env.ps1. Crea el venv con 'py -3.11 -m venv venv' y vuelve a intentar." -ForegroundColor Yellow
}