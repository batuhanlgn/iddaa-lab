# 8765 ve 3000 portlarini dinleyen iddaa-lab sureclerini durdurur
foreach ($port in 8765, 3000) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop; Write-Host "Durduruldu: port $port (PID $($c.OwningProcess))" }
        catch { Write-Host "Durdurulamadi: port $port - $($_.Exception.Message)" }
    }
}
