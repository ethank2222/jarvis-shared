@echo off
setlocal
set "JARVIS_HOME=C:\Users\ethan\Desktop\Jarvis"
set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"

if not "%~1"=="" (
    if exist "%PYTHON%" (
        "%PYTHON%" "%JARVIS_HOME%\run_jarvis.py" %*
    ) else (
        python "%JARVIS_HOME%\run_jarvis.py" %*
    )
) else if exist "%PYTHONW%" (
    start "Jarvis" /D "%JARVIS_HOME%" "%PYTHONW%" "%JARVIS_HOME%\run_jarvis.py"
) else (
    start "Jarvis" /D "%JARVIS_HOME%" python "%JARVIS_HOME%\run_jarvis.py"
)

endlocal
