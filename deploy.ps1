$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
git add .
$msg = Read-Host "커밋 메시지 입력"
git commit -m $msg
git push origin main
ssh ubuntu@192.168.71.90 "cd /home/ubuntu/legionbot && git pull && sudo systemctl restart legionbot && sudo systemctl status legionbot --no-pager"
