@echo on
title run MiniQmt without logon

set qmtPath=D:\QMT\bin.x64
CD /D %qmtPath%

taskkill /F /IM xtMiniQmt.exe /T

start "" "xtMiniQmt.exe" linkMini
  