## STOP PROCESS
```
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force
```
