; Custom uninstall cleanup for BotBuilder (per-machine NSIS installer).
; Removes user AppData and any leftover files in the install directory.

!macro customUnInstall
  ; Per-user AppData (app.setPath userData -> %AppData%\botbuilder-desktop)
  SetShellVarContext current
  RMDir /r "$APPDATA\botbuilder-desktop"

  ; Electron may also cache under Local AppData for some versions
  RMDir /r "$LOCALAPPDATA\botbuilder-desktop"
  RMDir /r "$LOCALAPPDATA\BotBuilder"

  ; Ensure install folder is fully removed (including untracked leftovers)
  SetShellVarContext all
  RMDir /r "$INSTDIR"
!macroend
