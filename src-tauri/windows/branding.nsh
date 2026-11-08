; Reuse the existing installation when upgrading from the former product name.
; The application's identifier, executable name, and data directory stay stable.
!macro NSIS_HOOK_PREINSTALL
  ReadRegStr $0 SHCTX "Software\oooing\云鉴" ""
  ${If} $0 == ""
    ReadRegStr $0 SHCTX "Software\oooing\节点优选" ""
    ${If} $0 != ""
    ${AndIf} ${FileExists} "$0\node-quality.exe"
      StrCpy $INSTDIR $0
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ReadRegStr $0 SHCTX "Software\oooing\节点优选" ""
  ${If} $0 == $INSTDIR
    DeleteRegKey SHCTX "Software\Microsoft\Windows\CurrentVersion\Uninstall\节点优选"
    DeleteRegKey SHCTX "Software\oooing\节点优选"
  ${EndIf}
  ; Only remove former shortcuts that point to this exact installation.
  !insertmacro IsShortcutTarget "$DESKTOP\节点优选.lnk" "$INSTDIR\node-quality.exe"
  Pop $0
  ${If} $0 = 1
    Delete "$DESKTOP\节点优选.lnk"
  ${EndIf}
  !insertmacro IsShortcutTarget "$SMPROGRAMS\节点优选.lnk" "$INSTDIR\node-quality.exe"
  Pop $0
  ${If} $0 = 1
    Delete "$SMPROGRAMS\节点优选.lnk"
  ${EndIf}
!macroend
