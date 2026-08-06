; ABcode Windows Installer Script (NSIS)
; Compile with: makensis /DVERSION="0.4.0" installer.nsi

!define APP_NAME "ABcode"
!ifndef VERSION
  !define APP_VERSION "0.4.0"
!else
  !define APP_VERSION "${VERSION}"
!endif
!define APP_PUBLISHER "ABcode Team"
!define APP_URL "https://github.com/qinfanglong/abcode"
!define APP_EXE "ABcode.exe"

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; General settings
Name "${APP_NAME} ${APP_VERSION}"
OutFile "dist\ABcode-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" ""
RequestExecutionLevel user

; Interface settings
!define MUI_ICON "build\icon.ico"
!define MUI_UNICON "build\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "build\banner.bmp"
!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "本向导将引导您安装 ${APP_NAME} ${APP_VERSION}。\n\n点击下一步继续。"
!define MUI_FINISHPAGE_TITLE "安装完成"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} 已成功安装在您的电脑上。\n\n点击完成启动 ${APP_NAME}。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_ABORTWARNING

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
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
    File /r "dist\ABcode.exe"
    File /r "frontend\*"
    File /r "backend\*"
    File "backend\requirements.txt"
    File "build\icon.ico"
    
    ; Create start script
    File "build\start_windows.bat"
    
    ; Create shortcuts
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\build\icon.ico" 0
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\build\icon.ico" 0
    
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
    Delete "$INSTDIR\build\icon.ico"
    RMDir /r "$INSTDIR\frontend"
    RMDir /r "$INSTDIR\backend"
    RMDir "$INSTDIR\build"
    RMDir "$INSTDIR"
    
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    
    DeleteRegKey HKCU "Software\${APP_NAME}"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
SectionEnd

Function .onInit
    ; Check if already running
    ${GetProcessName} "$EXEPATH" $R0
    StrCmp $R0 "${APP_EXE}" 0 +2
    MessageBox MB_OK|MB_ICONEXCLAMATION "${APP_NAME} 正在运行，请先关闭后再安装。"
    Abort
FunctionEnd