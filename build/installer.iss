; ============================================================
;  文本改写降重工作台 · Windows 安装包脚本
;  编译: ISCC.exe installer.iss   (产物在 ..\dist)
; ============================================================

#define MyAppName "文本改写降重工作台"
#define MyAppCode "WashingText"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "washing-text"

; HanLP 模型缓存目录: 本机装过一次就存在, 直接随包分发, 用户装完即用
#define ModelSrc GetEnv('APPDATA') + "\hanlp"

[Setup]
AppId={{8E2C5F31-7A4D-4E62-9B8F-2D3C6A1F5E90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppCode}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#MyAppCode}-{#MyAppVersion}-Setup
SetupIconFile=WashingText.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\WashingText.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
DisableWelcomePage=no
ShowLanguageDialog=auto

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "stage\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "stage\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "stage\WashingText.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "stage\使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "WashingText.ico"; DestDir: "{app}"; Flags: ignoreversion
; 模型放程序目录, 由 launcher 用 HANLP_HOME 指过去: 跟程序一起卸载,
; 也不会因为提权安装而落到"管理员账户"的用户目录里
#if DirExists(ModelSrc)
Source: "{#ModelSrc}\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Dirs]
; 提前建好, 否则「打开日志目录」快捷方式在首次启动前点了会报找不到
Name: "{userappdata}\{#MyAppCode}\logs"

[Icons]
; 指向应用自己的 exe, 不再指向 pythonw.exe —— 用户看到的就是"一个程序"
Name: "{group}\{#MyAppName}"; Filename: "{app}\WashingText.exe"; WorkingDir: "{app}"; Comment: "启动改写工作台"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{group}\打开日志目录"; Filename: "{userappdata}\{#MyAppCode}\logs"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\WashingText.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\WashingText.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\WashingText.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python 在只读安装目录下不会写 __pycache__, 这里只清理可能残留的临时文件
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\app\rewriter\__pycache__"
Type: filesandordirs; Name: "{app}\app\web\__pycache__"
