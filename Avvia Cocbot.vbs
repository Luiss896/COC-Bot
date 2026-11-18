' Avvia la GUI di cocbot senza finestra console (doppio click su questo file).
' Gli errori di avvio vengono scritti in out\gui-launcher.log
Option Explicit

Dim fso, shell, repo, pythonw, logDir, logFile, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

repo = fso.GetParentFolderName(WScript.ScriptFullName)

' pythonw preferito (nessuna console); fallback al PATH se il percorso fisso manca
pythonw = "C:\Python314\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

logDir = repo & "\out"
If Not fso.FolderExists(logDir) Then
    fso.CreateFolder(logDir)
End If
logFile = logDir & "\gui-launcher.log"

command = "cmd.exe /c cd /d """ & repo & """ && """ & pythonw & """ -u -m cocbot gui >> """ & logFile & """ 2>&1"

On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    MsgBox "Impossibile avviare cocbot: " & Err.Description & vbCrLf & _
           "Apri 'Avvia Cocbot (debug).bat' per vedere l'errore.", 16, "cocbot"
    Err.Clear
End If
