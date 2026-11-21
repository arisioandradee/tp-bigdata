# Roda o teste de carga da busca (k6 em container, na mesma rede da API) e guarda os resultados em bench/resultados/.
# Uso: .\bench\rodar_carga.ps1 [-Repeticoes 3]
# Pre-requisito: stack no ar (docker compose up -d). Cada rodada dura cerca de 5 minutos e 30 segundos.
# Com varias repeticoes gera k6-resumo-r1.json, r2, r3...; depois: python bench/resumo_carga.py
param([int]$Repeticoes = 1)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
New-Item -ItemType Directory -Force "bench\resultados" | Out-Null

# credenciais do .env (nao sao impressas)
$senha = (Select-String -Path .env -Pattern '^LDAP_PROFESSOR_SENHA=').Line.Split('=', 2)[1]

function Token { $b = @{ username = "professor1"; password = $senha }; (Invoke-RestMethod "http://127.0.0.1:8000/auth/token" -Method Post -Body $b).access_token }
function CacheStats { $h = @{ Authorization = "Bearer " + (Token) }; Invoke-RestMethod "http://127.0.0.1:8000/metricas/cache" -Headers $h }

"ambiente: " + (docker info --format "{{.NCPU}} CPUs, {{.MemTotal}} bytes de memoria no Docker" 2>$null)
for ($i = 1; $i -le $Repeticoes; $i++) {
    $antes = CacheStats
    "rodada ${i} de ${Repeticoes} | cache antes : hits=$($antes.hits) misses=$($antes.misses)"
    $rodada = if ($Repeticoes -gt 1) { "$i" } else { "" }
    # O k6 sai com codigo 99 quando um limiar de referencia e ultrapassado (isso e resultado, nao falha) e escreve
    # no stderr; por isso o tratamento de erro e relaxado so nesta chamada.
    $ErrorActionPreference = "Continue"
    docker run --rm -i --network tp2-bigdata-net -v "${raiz}\bench:/bench" `
        -e SENHA=$senha -e BASE=http://api:8000 -e RODADA=$rodada grafana/k6:0.54.0 run /bench/k6/busca.js 2>&1 |
        Tee-Object -FilePath "bench\resultados\k6-saida-r$i.txt" | Out-Null
    $ErrorActionPreference = "Stop"
    $depois = CacheStats
    "rodada ${i} | cache depois: hits=$($depois.hits) misses=$($depois.misses)"
    @{ antes = $antes; depois = $depois } | ConvertTo-Json | Set-Content "bench\resultados\cache-antes-depois-r$i.json" -Encoding utf8
}
