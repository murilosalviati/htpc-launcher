# HTPC Launcher Bridge (extensão do GNOME)

Esta é a base do launcher. No Wayland, só o próprio GNOME pode trazer janelas para a frente.
A extensão oferece isso pelo D-Bus (`org.htpc.Launcher`, `/org/htpc/Launcher`):

| Método | O que faz |
|---|---|
| `IsRunning(appId)` | diz se o app tem janela aberta |
| `Activate(appId)` | traz a janela que já existe para a frente, retomando a sessão; devolve `false` se o app não está aberto |
| `ShowLauncher()` | traz o launcher para a frente (botão guide) |
| `FocusedApp()` | diz qual app está na frente |
| `Close(appId)` | pede para o app fechar, como clicar no X |
| `ListWindows()` | lista as janelas, em JSON, para diagnóstico |
| sinal `FocusChanged(appId)` | avisa toda vez que o foco muda |

## Instalar

```bash
chmod +x install.sh testar.sh
./install.sh
```
Na primeira instalação, saia da sessão e entre de novo. Depois rode `gnome-extensions enable htpc-launcher@htpc`.

No servidor, sair da sessão não faz o login automático entrar de novo. Para recarregar a extensão, rode `sudo systemctl restart gdm`. **Isso fecha tudo o que estiver aberto.**

## Testar pelo SSH

O SSH não enxerga a sessão gráfica. Exporte isto antes:

```bash
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export WAYLAND_DISPLAY=wayland-0
```

## Testar

Abra o Jellyfin Desktop e o VacuumTube e rode:

```bash
./testar.sh                                    # mostra os appIds que cada app recebeu
./testar.sh ativar org.jellyfin.JellyfinDesktop
./testar.sh ativar rocks.shy.VacuumTube
./testar.sh fechar rocks.shy.VacuumTube
```

O `./testar.sh` sem argumentos mostra os nomes que cada janela recebeu. Use essa saída para conferir os appIds do Artemis e do Steam.

## Erros

```bash
journalctl --user -f -o cat /usr/bin/gnome-shell
```
