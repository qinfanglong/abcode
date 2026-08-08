; ABcode Windows Installer Script (NSIS)
; Compile with: makensis -DVERSION="0.4.0" -DROOT=".." installer.nsi
; 注意：
;  1. NSIS 相对路径按脚本所在目录(build/)解析，因此统一用 ${ROOT} 绝对路径
;  2. NSIS File 指令的绝对路径必须用反斜杠（X:\...）形式；
;     正斜杠(/)或混合分隔符会被解析为相对路径导致 "no files found"

!define APP_NAME "ABcode"
!ifndef VERSION
  !define APP_VERSION "0.4.0"
!else
  !define APP_VERSION "${VERSION}"
!endif
!define APP_PUBLISHER "ABcode Team"
!define APP_URL "https://github.com/qinfanglong/abcode"
!define APP_EXE "ABcode.exe"

; ROOT = 仓库根目录（工作流传 -DROOT=$env:GITHUB_WORKSPACE；本地默认 .. 即 build/..）
!ifndef ROOT
  !define ROOT ".."
!endif

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; General settings
Name "${APP_NAME} ${APP_VERSION}"
OutFile "${ROOT}\dist\ABcode-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" ""
RequestExecutionLevel user

; Interface settings
!define MUI_ICON "${ROOT}\build\icon.ico"
!define MUI_UNICON "${ROOT}\build\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${ROOT}\build\banner.bmp"
!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "本向导将引导您安装 ${APP_NAME} ${APP_VERSION}。\n\n点击下一步继续。"
!define MUI_FINISHPAGE_TITLE "安装完成"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} 已成功安装在您的电脑上。\n\n点击完成启动 ${APP_NAME}。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_ABORTWARNING

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${ROOT}\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Languages
!insertmacro MUI_LANGUAGE "SimpChinese"

; Installer sections
Section "MainSection" SEC_MAIN
    SetOutPath "$INSTDIR"
    File "${ROOT}\dist\ABcode.exe"
    File /r "${ROOT}\frontend\*"
    File /r "${ROOT}\backend\*"
    File "${ROOT}\build\icon.ico"
    
    ; Create start script
    File "${ROOT}\build\start_windows.bat"
    
    ; Create shortcuts
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\icon.ico" 0
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\icon.ico" 0
    
    ; Registry for uninstaller
    WriteRegStr HKCU "Software\${APP_NAME}" "" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_URL}"
SectionEnd

; Uninstaller
Section "Uninstall"
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$INSTDIR\start_windows.bat"
    Delete "$INSTDIR\icon.ico"
    RMDir /r "$INSTDIR\frontend"
    RMDir /r "$INSTDIR\backend"
    RMDir "$INSTDIR"
    
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    
    DeleteRegKey HKCU "Software\${APP_NAME}"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
SectionEnd

Function .onInit
    ; 已安装且文件存在时给出提示（简化检测，避免对进程名宏的跨平台依赖）
    IfFileExists "$INSTDIR\${APP_EXE}" 0 +2
    MessageBox MB_OK|MB_ICONEXCLAMATION "${APP_NAME} 似乎已安装。若正在运行，请先关闭后再安装。"
FunctionEnd
