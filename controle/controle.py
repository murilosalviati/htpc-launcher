#!/usr/bin/env python3
"""Serviço do controle do HTPC.

Lê todos os controles conectados (Xbox, 8BitDo, PS4...) sem tirar os botões
dos apps e faz duas coisas:

  * Guide (Xbox / Home / PS): pausa o vídeo, se o app em foco for de vídeo,
    e mostra o launcher. O app continua aberto por trás.
  * Start + Select + L1 + R1: fecha o app em foco e volta ao launcher.
    No Moonlight, o 1º toque é dele (encerra o stream) e um 2º toque em até
    15 s fecha o Moonlight.

Depende da extensão "HTPC Launcher Bridge" do GNOME (D-Bus org.htpc.Launcher)
e de ~/.config/htpc-launcher/apps.json.

Pacotes: sudo apt install python3-evdev python3-jeepney
"""

import json
import logging
import os
import select
import signal
import subprocess
import threading
import time
from pathlib import Path

import evdev
from evdev import ecodes
from jeepney import DBusAddress, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

CONFIG = (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
          / "htpc-launcher" / "apps.json")

COMBO_FECHAR = {ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_TL, ecodes.BTN_TR}
BOTAO_GUIDE = ecodes.BTN_MODE

# O Steam cria um controle virtual que repete os eventos do controle real;
# uma ação dentro desse intervalo é tratada como repetição e ignorada.
INTERVALO_ENTRE_ACOES = 1.0
JANELA_SEGUNDO_TOQUE = 15.0   # Moonlight: tempo para o 2º toque fechar o app
ESPERA_FECHAR_PADRAO = 3.0    # quanto esperar o app fechar sozinho antes de forçar
REVARREDURA = 2.0             # de quanto em quanto tempo procurar controles novos

log = logging.getLogger("htpc-controle")


# ---------------------------------------------------------------------------
# Configuração

def carregar_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def ids_do_app(app):
    return [i.lower() for i in [app["id"], *app.get("outros_ids", [])] if i]


def app_da_janela(cfg, janela):
    """Acha no apps.json o app dono da janela (pelos nomes que a extensão deu)."""
    nomes = set(janela.get("ids", [])) | {janela.get("appId", "").lower()}
    for app in cfg.get("apps", []):
        if nomes & set(ids_do_app(app)):
            return app
    return None


def eh_launcher(cfg, janela):
    lid = cfg.get("launcher", {}).get("id", "htpc-launcher").lower()
    return lid in janela.get("ids", []) or janela.get("appId", "").lower() == lid


# ---------------------------------------------------------------------------
# D-Bus: extensão do GNOME e players de mídia (MPRIS)

class Shell:
    """Conversa com a extensão HTPC Launcher Bridge. Uma por thread."""

    def __init__(self):
        self.conn = open_dbus_connection(bus="SESSION")
        self.addr = DBusAddress("/org/htpc/Launcher", bus_name="org.htpc.Launcher",
                                interface="org.htpc.Launcher")

    def _chamar(self, metodo, assinatura=None, args=()):
        msg = new_method_call(self.addr, metodo, assinatura, args)
        return unwrap_msg(self.conn.send_and_get_reply(msg, timeout=2))

    def janelas(self):
        return json.loads(self._chamar("ListWindows")[0])

    def janela_em_foco(self):
        return next((j for j in self.janelas() if j.get("focused")), None)

    def mostrar_launcher(self):
        return self._chamar("ShowLauncher")[0]

    def fechar(self, app_id):
        return self._chamar("Close", "s", (app_id,))[0]

    def rodando(self, app_id):
        return self._chamar("IsRunning", "s", (app_id,))[0]

    def pausar_midia(self):
        """Pausa todo player MPRIS que estiver tocando. Devolve os nomes pausados."""
        nomes = unwrap_msg(self.conn.send_and_get_reply(message_bus.ListNames(), timeout=2))[0]
        pausados = []
        for nome in nomes:
            if not nome.startswith("org.mpris.MediaPlayer2."):
                continue
            player = DBusAddress("/org/mpris/MediaPlayer2", bus_name=nome,
                                 interface="org.mpris.MediaPlayer2.Player")
            try:
                estado = unwrap_msg(self.conn.send_and_get_reply(
                    Properties(player).get("PlaybackStatus"), timeout=1))[0][1]
                if estado == "Playing":
                    unwrap_msg(self.conn.send_and_get_reply(
                        new_method_call(player, "Pause"), timeout=1))
                    pausados.append(nome)
            except Exception as e:  # um player com defeito não pode travar o resto
                log.debug("não deu para pausar %s: %s", nome, e)
        return pausados


# ---------------------------------------------------------------------------
# Ações

def ambiente_grafico():
    """Ambiente para os programas que o serviço abre (launcher, Steam -shutdown).

    O serviço roda no systemd do usuário, que nem sempre recebe as variáveis
    da sessão gráfica. Completa só as que faltarem, sem trocar as que existem.
    """
    env = dict(os.environ)
    runtime = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("DISPLAY", ":0")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    env.setdefault("XDG_SESSION_TYPE", "wayland")
    return env


def abrir(comando):
    return subprocess.Popen(comando, start_new_session=True, env=ambiente_grafico(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def forcar_fechamento(app_id, pid):
    """Último recurso quando o app não fecha sozinho."""
    if app_id and subprocess.run(["flatpak", "info", app_id],
                                 capture_output=True).returncode == 0:
        log.info("forçando: flatpak kill %s", app_id)
        subprocess.run(["flatpak", "kill", app_id], capture_output=True)
        return
    if not pid or pid <= 1 or pid == os.getpid():
        log.warning("não sei como forçar o fechamento de %r", app_id)
        return
    log.info("forçando: SIGTERM no pid %d", pid)
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        os.kill(pid, signal.SIGKILL)
        log.info("SIGKILL no pid %d", pid)
    except ProcessLookupError:
        pass


class Acoes:
    def __init__(self, shell_factory=Shell):
        self.shell_factory = shell_factory
        self._shell = None
        self.ultima_acao = 0.0
        self.primeiro_toque_artemis = 0.0

    @property
    def shell(self):
        if self._shell is None:
            self._shell = self.shell_factory()
        return self._shell

    def _livre(self):
        agora = time.monotonic()
        if agora - self.ultima_acao < INTERVALO_ENTRE_ACOES:
            return False
        self.ultima_acao = agora
        return True

    def _contexto(self):
        """(config, janela em foco) ou None se não há nada a fazer."""
        cfg = carregar_config()
        try:
            janela = self.shell.janela_em_foco()
        except Exception as e:
            log.error("extensão do GNOME não respondeu: %s", e)
            self._shell = None  # reconecta na próxima
            return cfg, None
        return cfg, janela

    def _mostrar_launcher(self, cfg, shell):
        if shell.mostrar_launcher():
            return
        comando_launcher = cfg.get("launcher", {}).get("abrir")
        if comando_launcher:
            log.info("launcher não estava aberto; abrindo")
            abrir(comando_launcher)
        else:
            log.warning("launcher não está aberto e não há comando para abri-lo")

    def guide(self):
        if not self._livre():
            return
        cfg, janela = self._contexto()
        if janela is not None and eh_launcher(cfg, janela):
            return
        app = app_da_janela(cfg, janela) if janela else None
        try:
            if app and app.get("pausar_ao_sair"):
                pausados = self.shell.pausar_midia()
                log.info("guide em %s: pausado %s", app["nome"], pausados or "nada (nenhum player tocando)")
            self._mostrar_launcher(cfg, self.shell)
        except Exception as e:
            log.error("guide falhou: %s", e)
            self._shell = None

    def fechar(self):
        if not self._livre():
            return
        cfg, janela = self._contexto()
        if janela is None or eh_launcher(cfg, janela):
            return
        app = app_da_janela(cfg, janela)

        if app and app.get("fechar_em_dois_toques"):
            agora = time.monotonic()
            if agora - self.primeiro_toque_artemis > JANELA_SEGUNDO_TOQUE:
                self.primeiro_toque_artemis = agora
                log.info("%s: 1º toque (o próprio app encerra o stream)", app["nome"])
                return
            self.primeiro_toque_artemis = 0.0

        # Fechar pode levar alguns segundos; faz numa thread para o guide
        # continuar respondendo enquanto isso.
        threading.Thread(target=self._fechar, args=(cfg, janela, app), daemon=True).start()

    def _fechar(self, cfg, janela, app):
        try:
            shell = self.shell_factory()
            alvo = app["id"] if app else janela.get("appId", "")
            nome = app["nome"] if app else (alvo or janela.get("title", "?"))
            espera = (app or {}).get("espera_fechar", ESPERA_FECHAR_PADRAO)

            comando = (app or {}).get("fechar")
            if comando:
                log.info("fechando %s com %s", nome, comando)
                abrir(comando)
            else:
                log.info("fechando %s (%d janela(s))", nome, shell.fechar(alvo))

            prazo = time.monotonic() + espera
            while time.monotonic() < prazo:
                time.sleep(0.25)
                if not shell.rodando(alvo):
                    break
            else:
                forcar_fechamento(alvo, janela.get("pid"))

            self._mostrar_launcher(cfg, shell)
        except Exception as e:
            log.error("fechar falhou: %s", e)


# ---------------------------------------------------------------------------
# Leitura dos controles

def eh_controle(dev):
    teclas = dev.capabilities().get(ecodes.EV_KEY, [])
    return ecodes.BTN_SOUTH in teclas and ecodes.BTN_START in teclas


class Controles:
    def __init__(self, acoes):
        self.acoes = acoes
        self.devs = {}        # caminho -> InputDevice
        self.apertados = {}   # caminho -> botões apertados agora
        self.ignorados = set()

    def revarrer(self):
        caminhos = set(evdev.list_devices())
        self.ignorados &= caminhos  # aparelho que sumiu pode voltar como outro
        for caminho in caminhos - self.devs.keys() - self.ignorados:
            try:
                dev = evdev.InputDevice(caminho)
            except OSError:
                self.ignorados.add(caminho)  # sem permissão: teclado, mouse...
                continue
            if eh_controle(dev):
                self.devs[caminho] = dev
                self.apertados[caminho] = set()
                log.info("controle conectado: %s (%s)", dev.name, caminho)
            else:
                dev.close()
                self.ignorados.add(caminho)

    def remover(self, caminho):
        dev = self.devs.pop(caminho, None)
        self.apertados.pop(caminho, None)
        if dev:
            log.info("controle desconectado: %s", dev.name)
            try:
                dev.close()
            except OSError:
                pass

    def tratar(self, caminho, evento):
        if evento.type != ecodes.EV_KEY:
            return
        apertados = self.apertados[caminho]
        if evento.value == 1:
            apertados.add(evento.code)
            if evento.code == BOTAO_GUIDE:
                self.acoes.guide()
            elif evento.code in COMBO_FECHAR and COMBO_FECHAR <= apertados:
                self.acoes.fechar()
        elif evento.value == 0:
            apertados.discard(evento.code)

    def rodar(self):
        proxima_varredura = 0.0
        while True:
            if time.monotonic() >= proxima_varredura:
                self.revarrer()
                proxima_varredura = time.monotonic() + REVARREDURA
            por_fd = {dev.fd: caminho for caminho, dev in self.devs.items()}
            prontos, _, _ = select.select(list(por_fd), [], [], REVARREDURA)
            for fd in prontos:
                caminho = por_fd[fd]
                try:
                    for evento in self.devs[caminho].read():
                        self.tratar(caminho, evento)
                except OSError:
                    self.remover(caminho)


def main():
    logging.basicConfig(level=os.environ.get("HTPC_LOG", "INFO"),
                        format="%(levelname)s %(message)s")
    if not CONFIG.exists():
        raise SystemExit(f"Falta o arquivo de configuração: {CONFIG}")
    Controles(Acoes()).rodar()


if __name__ == "__main__":
    main()
