$ErrorActionPreference = 'Stop'
$testPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $testPython (Join-Path $PSScriptRoot 'tools\verify.py')
if ($LASTEXITCODE -ne 0) { throw 'Verification failed. See reports\pytest.txt and reports\evaluation.json.' }
