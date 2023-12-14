:loop
if exist linkMini (
    copy linkMini linkMini_copy 
    echo finish
    goto end
)
if exist linkmini (
    copy linkmini linkMini_copy 
    echo finish
    goto end
)
echo continue
timeout /t 0.1 >nul
goto loop
:end