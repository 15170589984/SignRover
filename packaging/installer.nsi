; 社区签到助手 · NSIS 安装脚本
; 编译：makensis /DPROJ="<项目根>" installer.nsi
; 说明：安装包文件名与向导界面为简体中文，实际安装目录为英文
;       %LOCALAPPDATA%\Programs\SignRover（免 UAC 的用户级安装）

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!ifndef PROJ
  !define PROJ "."
!endif

; 显示名（开始菜单 / 控制面板）用中文，磁盘上的目录与 exe 一律用英文，
; 避免中文路径在部分工具链、脚本、杀软白名单里出问题
!define APP_NAME    "社区签到助手"
!define APP_DIR     "SignRover"
!define APP_VERSION "1.3.8"
!define APP_EXE     "SignRover.exe"
!define APP_KEY     "社区签到助手"
!define APP_PUB     "社区签到助手"
!define SRC_DIR     "${PROJ}\dist\SignRover"
; 默认装到 D:\Games\SignRover（用户习惯的位置）；该盘不可用时退回用户目录
!define DEFAULT_ROOT "D:\Games"
!define FALLBACK_DIR "$LOCALAPPDATA\Programs\${APP_DIR}"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${PROJ}\dist\SignRover_v${APP_VERSION}.exe"
InstallDir "${DEFAULT_ROOT}\${APP_DIR}"
; 装在用户可写目录，不需要管理员权限，双击直接装完（也便于自动化安装验证）
RequestExecutionLevel user
BrandingText "${APP_NAME} v${APP_VERSION}"
ShowInstDetails show
ShowUninstDetails show

; ---------------- 外观 ----------------
!define MUI_ICON   "${PROJ}\tools\icon.ico"
!define MUI_UNICON "${PROJ}\tools\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP    "${PROJ}\packaging\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP  "${PROJ}\packaging\wizard.bmp"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "确定要退出安装吗？"

!define MUI_WELCOMEPAGE_TITLE "${APP_NAME} 安装向导"
!define MUI_WELCOMEPAGE_TEXT "本向导将引导你完成 ${APP_NAME} v${APP_VERSION} 的安装。$\r$\n$\r$\n${APP_NAME} 是一款游戏社区与开发工具每日签到的助手，支持米游社（原神 / 星穹铁道 / 绝区零 / 崩坏3 / 未定 / 崩坏学园2）、库街区（鸣潮 / 战双）、以及 Trae / Qoder / WorkBuddy 三个 PC 工具的每日签到与积分查询。$\r$\n$\r$\n社区任务需先在安卓模拟器内登录对应 App；Trae / Qoder / WorkBuddy 只要本机客户端已登录，在「登录账号」里点「自动获取」即可，读不到再手动粘贴 token。同一平台可以登录多个账号。详细步骤见安装目录下的「使用说明.txt」。$\r$\n$\r$\n点击「下一步」继续。"

!define MUI_DIRECTORYPAGE_TEXT_TOP "请选择安装位置。检测到本机已安装旧版本时会自动定位到原位置；你也可以自行修改。全新安装建议使用默认路径。"

!define MUI_FINISHPAGE_TITLE "${APP_NAME} 安装完成"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} v${APP_VERSION} 已安装到：$\r$\n$INSTDIR$\r$\n$\r$\n第一次使用前，请先在模拟器里登录米游社或库街区；然后启动程序，进入「账号」页点右上角「登录账号」，选平台后「自动获取」或「手动添加」。Trae / Qoder / WorkBuddy 客户端已登录时会自动读取登录态，无需粘贴。同一平台可登录多个账号并在总览页切换。$\r$\n$\r$\n完整操作步骤见安装目录下的「使用说明.txt」。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchApp"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\使用说明.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "打开使用说明"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; ---------------- 初始化 ----------------
; 统一写 64 位注册表视图（否则会被重定向进 WOW6432Node）
Function .onInit
  SetRegView 64

  ; 1) 命令行 /D 指定了目录时（NSIS 在 .onInit 之前已写入 $INSTDIR），
  ;    只要和默认值不同就说明是用户指定的，一律尊重
  ${If} $INSTDIR != "${DEFAULT_ROOT}\${APP_DIR}"
    Goto done
  ${EndIf}

  ; 2) 覆盖安装：注册表里记录了上次安装位置，且该位置确实是本程序的安装目录，
  ;    自动定位过去做原地升级（用户仍可在目录页改成别处）
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "InstallLocation"
  ${If} $0 != ""
  ${AndIf} ${FileExists} "$0\${APP_EXE}"
    StrCpy $INSTDIR $0
    Goto done
  ${EndIf}

  ; 3) 默认根目录不可用（比如换了一台没有 D 盘的机器）→ 退回用户目录
  ${IfNot} ${FileExists} "${DEFAULT_ROOT}\*.*"
    StrCpy $INSTDIR "${FALLBACK_DIR}"
  ${EndIf}

  IfSilent done
  ; 旧版残留（老式中文 exe 名 / Program Files 的管理员级安装 / 早前装到用户目录的版本）：
  ; 本版默认装到 ${DEFAULT_ROOT}\${APP_DIR}，仅提示，安装时会自动清掉旧目录
  StrCpy $2 ""
  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "InstallLocation"
  ${If} $1 != ""
  ${AndIf} ${FileExists} "$1\${APP_NAME}.exe"
    StrCpy $2 "$2$\r$\n  · $1"
  ${EndIf}
  ${If} ${FileExists} "$LOCALAPPDATA\Programs\${APP_NAME}\uninstall.exe"
    StrCpy $2 "$2$\r$\n  · $LOCALAPPDATA\Programs\${APP_NAME}"
  ${EndIf}
  ReadRegStr $1 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "InstallLocation"
  ${If} $1 != ""
    StrCpy $2 "$2$\r$\n  · $1"
  ${EndIf}
  ${If} $2 != ""
    MessageBox MB_OK|MB_ICONINFORMATION "检测到旧版本安装在：$2$\r$\n$\r$\n本版将安装到：$\r$\n$INSTDIR$\r$\n$\r$\n安装完成后旧位置会被自动清理，账号与执行记录会保留。如需安装到其它位置，可在下一步修改路径。"
  ${EndIf}
  done:
FunctionEnd

Function un.onInit
  SetRegView 64
FunctionEnd

; 卸载一个旧版安装目录（入参 $R0 = 目录）
Function UninstallLegacy
  ${If} $R0 == ""
    Return
  ${EndIf}
  ${If} $R0 == "$INSTDIR"
    Return
  ${EndIf}
  ${If} ${FileExists} "$R0\uninstall.exe"
    ; 静默卸载：只删程序文件，不影响 %USERPROFILE%\.signrover 里的账号数据
    ExecWait '"$R0\uninstall.exe" /S _?=$R0'
    ; _?= 模式下卸载器不会删自己，这里补一刀；确认不是新目录再删
    ${If} $R0 != "$INSTDIR"
    ${AndIf} ${FileExists} "$R0\uninstall.exe"
      Delete "$R0\uninstall.exe"
      RMDir /r "$R0"
    ${EndIf}
  ${ElseIf} ${FileExists} "$R0\${APP_NAME}.exe"
    RMDir /r "$R0"
  ${EndIf}
FunctionEnd

; 自动结束正在运行的程序（账号与签到记录都是即时落盘的，强杀无损）。
; 进程被 /F 杀掉后 Windows 释放 exe 句柄有延迟，杀软也可能短暂扫描文件，
; 所以重试 5 次、每次隔 1.5 秒。成功后 exe 已被改名清走；
; 调用方用 FileExists("$INSTDIR\exe") 判断是否仍被锁。
!macro KillRunningApp
  StrCpy $3 "0"
  kill_retry:
    nsExec::Exec 'taskkill /IM "${APP_EXE}" /F'
    Pop $0
    Sleep 1500
    ClearErrors
    Rename "$INSTDIR\${APP_EXE}" "$INSTDIR\_occupied_check.tmp"
    ${If} ${Errors}
      IntOp $3 $3 + 1
      ${If} $3 < 5
        Goto kill_retry
      ${EndIf}
    ${Else}
      Delete "$INSTDIR\_occupied_check.tmp"
    ${EndIf}
!macroend

Function CleanLegacy
  StrCpy $R0 ""
  ReadRegStr $R0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "InstallLocation"
  Call UninstallLegacy
  StrCpy $R0 "$LOCALAPPDATA\Programs\${APP_NAME}"
  Call UninstallLegacy
  StrCpy $R0 ""
  ReadRegStr $R0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "InstallLocation"
  Call UninstallLegacy
FunctionEnd

; ---------------- 安装 ----------------
Section "主程序" SecMain
  SectionIn RO
  SetRegView 64
  ; 先清掉旧版（旧版装在中文目录 / Program Files，不清理会出现两份并在注册表打架）
  Call CleanLegacy
  SetOutPath "$INSTDIR"

  ; 程序正在运行会占住 exe：先自动结束（数据即时落盘，强杀无损），
  ; 重试 3 次仍被锁（极少见，如杀软正在扫描）才提示人工处理
  ${If} ${FileExists} "$INSTDIR\${APP_EXE}"
    !insertmacro KillRunningApp
    Delete "$INSTDIR\_occupied_check.tmp"          ; 兜底清理
    ${If} ${FileExists} "$INSTDIR\${APP_EXE}"
      MessageBox MB_ICONSTOP|MB_OK "检测到 ${APP_NAME} 正在运行，且自动结束失败。$\r$\n$\r$\n请在任务管理器里结束 ${APP_EXE} 进程后，再重新安装。"
      Abort
    ${EndIf}
  ${EndIf}

  ; 程序主体（目录与 exe 均为英文 SignRover，显示名仍是中文）
  File /r "${SRC_DIR}\*.*"

  ; 自带的 adb（提取凭证时用，目标机无需另装 Android SDK）
  SetOutPath "$INSTDIR\bin"
  File "${PROJ}\bin\adb.exe"
  File "${PROJ}\bin\AdbWinApi.dll"
  File "${PROJ}\bin\AdbWinUsbApi.dll"
  SetOutPath "$INSTDIR"

  ; 使用说明放在安装根目录
  File "/oname=使用说明.txt" "${PROJ}\packaging\使用说明.txt"

  ; 卸载程序
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; 开始菜单
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\使用说明.lnk" "$INSTDIR\使用说明.txt"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"

  ; 桌面快捷方式
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  ; 注册表：程序信息
  WriteRegStr HKCU "Software\${APP_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\${APP_KEY}" "Version" "${APP_VERSION}"

  ; 注册表：控制面板「程序和功能」
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "Publisher" "${APP_PUB}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}" "EstimatedSize" "$0"
SectionEnd

; ---------------- 卸载 ----------------
Section "Uninstall"
  SetRegView 64
  ; 把工作目录挪出安装目录，否则 $INSTDIR 会被占用导致删不干净
  SetOutPath "$TEMP"

  ; 程序还开着的话 exe 会被占用：先自动结束（强杀无损），仍锁住才提示
  ${If} ${FileExists} "$INSTDIR\${APP_EXE}"
    !insertmacro KillRunningApp
    Delete "$INSTDIR\_occupied_check.tmp"          ; 兜底清理
    ${If} ${FileExists} "$INSTDIR\${APP_EXE}"
    ${AndIfNot} ${Silent}
      MessageBox MB_ICONSTOP|MB_OK "检测到 ${APP_NAME} 正在运行，且自动结束失败。$\r$\n$\r$\n请在任务管理器里结束 ${APP_EXE} 进程后，再重新卸载。"
      Abort
    ${EndIf}
  ${EndIf}

  ; 自带 adb 会以 server 形式常驻后台，不先关掉 bin\adb.exe 删不掉
  ${If} ${FileExists} "$INSTDIR\bin\adb.exe"
    nsExec::Exec '"$INSTDIR\bin\adb.exe" kill-server'
    Pop $0
    Sleep 400
  ${EndIf}

  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}"
  DeleteRegKey HKCU "Software\${APP_KEY}"
  ; 开机自启项也要清掉，否则卸载后每次开机都会报「找不到文件」
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "SignRover"

  ; 只有确认是本程序的安装目录才整体删除
  ${If} ${FileExists} "$INSTDIR\uninstall.exe"
    RMDir /r "$INSTDIR"
  ${Else}
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\使用说明.txt"
  ${EndIf}
  ; 兜底：被占用没删掉的（极少见）再试一轮
  Delete "$INSTDIR\bin\adb.exe"
  Delete "$INSTDIR\bin\AdbWinApi.dll"
  Delete "$INSTDIR\bin\AdbWinUsbApi.dll"
  RMDir "$INSTDIR\bin"
  RMDir "$INSTDIR"

  ; 个人数据（账号 / 记录）保留，除非用户明确选择删除
  IfSilent skip_data_prompt
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除本机保存的账号与执行记录？$\r$\n$\r$\n位置：$PROFILE\.signrover$\r$\n$\r$\n选择「否」将保留数据，以后重新安装可直接继续使用。" IDNO skip_data_prompt
    RMDir /r "$PROFILE\.signrover"
  skip_data_prompt:
SectionEnd

; 以当前登录用户身份启动（不继承安装程序的提权），避免数据写进管理员账户
Function LaunchApp
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\${APP_EXE}"'
FunctionEnd
