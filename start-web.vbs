' Washing-text web workbench silent launcher
' Runs start-web.bat with a hidden console window.
' Do NOT use pythonw.exe here: it sets sys.stdout to None and HanLP crashes
' with "'NoneType' object has no attribute 'write'".
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\AI\program\washing-text"
sh.Run "cmd /c ""D:\AI\program\washing-text\start-web.bat""", 0, False
