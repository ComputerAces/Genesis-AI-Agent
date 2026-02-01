@echo off
SETLOCAL EnableDelayedExpansion

:: Check for env folder
IF NOT EXIST "env" (
    echo [INFO] Creating virtual environment in 'env' directory...
    python -m venv env
)

:: Activate environment
echo [INFO] Activating virtual environment...
CALL env\Scripts\activate.bat

:: Install requirements
echo [INFO] Installing requirements from requirements.txt...
pip install -r requirements.txt

:: Collect parameters and check for 'gui'
SET "IS_GUI=0"
SET "PARAMS="

:ARG_LOOP
IF "%~1"=="" GOTO ARG_END
SET "VAL=%~1"
IF /I "!VAL!"=="/gui" (
    SET "IS_GUI=1"
) ELSE IF /I "!VAL!"=="gui" (
    SET "IS_GUI=1"
) ELSE (
    IF DEFINED PARAMS (
        SET "PARAMS=!PARAMS! %1"
    ) ELSE (
        SET "PARAMS=%1"
    )
)
SHIFT
GOTO ARG_LOOP
:ARG_END

IF "%IS_GUI%"=="1" (
    echo [INFO] Launching Flask Web UI...
    python app.py %PARAMS%
) ELSE (
    echo [INFO] Launching CLI Interface...
    python modules\cli.py %PARAMS%
)

DEACTIVATE
ENDLOCAL
pause
