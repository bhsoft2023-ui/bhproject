; ملف Inno Setup لإنشاء مثبت بنقرة واحدة.
; البناء: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\BaqalaPOS.iss
; المدخل: dist\BaqalaPOS (ناتج PyInstaller)   المخرج: Output\BaqalaPOS-Setup-<version>.exe
;
; البيانات (قاعدة البيانات والنسخ الاحتياطية والسجلات) تُحفظ في %ProgramData%\BaqalaPOS
; وليست داخل مجلد البرنامج، والمثبت/المزيل لا يلمسها، لذلك تبقى عند التحديث أو إعادة التثبيت.

#define AppName "نظام البقالة - كاشير ومخزون"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C7B1D2E-4F3A-4B8E-9C61-BA9A1A0B0C01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=BaqalaPOS
DefaultDirName={autopf}\BaqalaPOS
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\Output
OutputBaseFilename=BaqalaPOS-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\BaqalaPOS.exe

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Files]
Source: "..\dist\BaqalaPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; مجلد البيانات مشترك لكل مستخدمي ويندوز على الجهاز وقابل للكتابة، ولا يُحذف عند الإزالة.
Name: "{commonappdata}\BaqalaPOS"; Permissions: users-modify; Flags: uninsneveruninstall
; خدمة SQL Server تكتب ملفات النسخ (.bak) بنفسها، لذلك تُمنح الخدمات صلاحية الكتابة في مجلد النسخ.
Name: "{commonappdata}\BaqalaPOS\backups"; Permissions: users-modify service-modify; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\BaqalaPOS.exe"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\BaqalaPOS.exe"

[Run]
Filename: "{app}\BaqalaPOS.exe"; Description: "تشغيل البرنامج الآن"; Flags: nowait postinstall skipifsilent
