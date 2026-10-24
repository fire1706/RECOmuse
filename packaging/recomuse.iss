; Installateur Windows de RECOmuse (Inno Setup 6).
;
; Il installe le dossier produit par PyInstaller (dist\RECOmuse), qui contient déjà
; Audiveris, Tesseract et ses langues : rien d'autre à installer (MuseScore reste
; facultatif). Installation pour l'utilisateur seul : pas besoin d'être administrateur.
; Les données de l'utilisateur (%LOCALAPPDATA%\RECOmuse : base, extraits, pages) ne sont
; PAS effacées à la désinstallation : elles contiennent tout ce que RECOmuse a appris.
;
; Lancement :  ISCC.exe /DAppVersion=0.1.0 packaging\recomuse.iss
; (packaging\build_windows.py le fait, avec la version de pyproject.toml).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define Root ".."

[Setup]
AppId={{6B0E3C4A-2F59-4D7B-9E0B-6A1C3F0E8D21}
AppName=RECOmuse
AppVersion={#AppVersion}
AppPublisher=Fanfare Royale d'Acoz
DefaultDirName={localappdata}\Programs\RECOmuse
DefaultGroupName=RECOmuse
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist
OutputBaseFilename=RECOmuse-{#AppVersion}-installation
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\RECOmuse.exe
#if FileExists(AddBackslash(SourcePath) + "..\LICENSE")
LicenseFile={#Root}\LICENSE
#endif

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Root}\dist\RECOmuse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RECOmuse"; Filename: "{app}\RECOmuse.exe"
Name: "{group}\{cm:UninstallProgram,RECOmuse}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\RECOmuse"; Filename: "{app}\RECOmuse.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RECOmuse.exe"; Description: "{cm:LaunchProgram,RECOmuse}"; Flags: nowait postinstall skipifsilent
