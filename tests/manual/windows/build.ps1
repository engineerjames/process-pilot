
# Set the path to the build.ps1
$scriptPath = $(Split-Path -parent $MyInvocation.MyCommand.Definition)

# Set the output directory for the executable
$outputDir = "$scriptPath/dist"

# Ensure the output directory exists
if (-Not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir
}

# Run PyInstaller to build the executable
pyinstaller --onefile --distpath $outputDir $scriptPath/pyinstaller.py

# Notify the user of the build status
if ($?) {
    Write-Host "Build successful. Executable created in $outputDir" -ForegroundColor Green
}
else {
    Write-Host "Build failed." -ForegroundColor Red
}
