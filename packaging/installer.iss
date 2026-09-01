; Transkript kurulum betigi (Inno Setup 6)
;
; Once PyInstaller calistirilmali:
;     pyinstaller packaging/transkript.spec --noconfirm
; Sonra:
;     iscc packaging/installer.iss
;
; Cikti: dist/Transkript-Setup-1.0.0.exe
;
; Not: imzasiz kurulum dosyasinda Windows SmartScreen uyarisi cikar.
; "Daha fazla bilgi" > "Yine de calistir" ile gecilir. Kod imzalama
; sertifikasi yillik ucretli ve kisisel kullanim icin gerekli degil.

#define AppName "Transkript"
#define AppVersion "1.0.0"
#define AppExeName "Transkript.exe"
#define AppPublisher "Transkript"

[Setup]
AppId={{8F3A6C21-4B7E-4E2A-9D18-2C5E7A9B4D63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes

; Gorunum: uygulamayla ayni palet ve yazi tipi. Gorseller
; scripts/make_brand.py tarafindan uretiliyor, elle duzenlenmemeli.
WizardStyle=modern
WizardSizePercent=110
WizardImageFile=..\assets\installer\wizard-large-164x314.bmp,..\assets\installer\wizard-large-192x386.bmp,..\assets\installer\wizard-large-246x459.bmp,..\assets\installer\wizard-large-273x556.bmp,..\assets\installer\wizard-large-328x604.bmp
WizardSmallImageFile=..\assets\installer\wizard-small-55x58.bmp,..\assets\installer\wizard-small-64x68.bmp,..\assets\installer\wizard-small-83x80.bmp,..\assets\installer\wizard-small-92x97.bmp,..\assets\installer\wizard-small-110x106.bmp,..\assets\installer\wizard-small-119x123.bmp,..\assets\installer\wizard-small-138x140.bmp
; Gorseller tam olcude uretildi, gerilmesine gerek yok.
WizardImageStretch=no
WizardImageAlphaFormat=none
; Yonetici hakki istemiyoruz: kullanici klasorune kurulabiliyor ve
; SmartScreen disinda ek bir uyari cikmiyor.
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
turkish.WelcomeLabel1=Transkript kurulumu
turkish.WelcomeLabel2=YouTube linkinden veya yerel videodan PDF transkript ureten uygulama.%n%nTranskripsiyon tamamen bilgisayarinizda calisir; ses hicbir servise gonderilmez.%n%nDevam etmek icin Ileri'ye tiklayin.
turkish.FinishedHeadingLabel=Transkript kuruldu
turkish.FinishedLabelNoIcons=Uygulamayi ilk actiginizda bilgisayariniz incelenecek ve uygun model secilecek.
turkish.FinishedLabel=Uygulamayi ilk actiginizda bilgisayariniz incelenecek ve uygun model secilecek.
english.WelcomeLabel1=Install Transkript
english.WelcomeLabel2=Turns a YouTube link or a local video into a PDF transcript.%n%nTranscription runs entirely on your computer; audio is never uploaded.%n%nClick Next to continue.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Transkript\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Kurulum sirasinda olusan Python onbellegi. Kullanici verisi (ayarlar, kuyruk,
; modeller) BILEREK silinmiyor; asagidaki soru ile ayrica soruluyor.
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataPath: string;
  LocalPath: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataPath := ExpandConstant('{userappdata}\Transkript');
    LocalPath := ExpandConstant('{localappdata}\Transkript');
    if DirExists(AppDataPath) or DirExists(LocalPath) then
    begin
      if MsgBox('Ayarlar, is kuyrugu ve indirilmis Whisper modelleri de silinsin mi?' + #13#10 +
                'Modeller birkac gigabayt yer kaplayabilir.' + #13#10#13#10 +
                'Hayir derseniz uygulamayi tekrar kurdugunuzda her sey yerinde kalir.',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(AppDataPath, True, True, True);
        DelTree(LocalPath, True, True, True);
      end;
    end;
  end;
end;
