#!/usr/bin/env bash
# Testes rápidos da extensão pelo D-Bus.
# Uso:
#   ./testar.sh                      lista as janelas abertas e o app em foco
#   ./testar.sh ativar <appId>       traz o app para a frente
#   ./testar.sh rodando <appId>      diz se o app está aberto
#   ./testar.sh fechar <appId>       pede para o app fechar
#   ./testar.sh launcher             mostra o launcher
#   ./testar.sh foco [segundos]      acompanha as trocas de foco (para sozinho; padrão 60 s)
set -euo pipefail

call() {
    gdbus call --session --dest org.htpc.Launcher \
        --object-path /org/htpc/Launcher \
        --method "org.htpc.Launcher.$1" "${@:2}"
}

case "${1:-listar}" in
    listar)
        call ListWindows
        echo "Em foco: $(call FocusedApp)"
        ;;
    ativar)   call Activate "$2" ;;
    rodando)  call IsRunning "$2" ;;
    fechar)   call Close "$2" ;;
    launcher) call ShowLauncher ;;
    foco)
        # Para sozinho depois de N segundos (padrão 60), para não ficar
        # esquecido rodando no servidor.
        timeout "${2:-60}" gdbus monitor --session --dest org.htpc.Launcher \
            --object-path /org/htpc/Launcher || true
        ;;
    *) echo "Comando desconhecido: $1"; exit 1 ;;
esac
