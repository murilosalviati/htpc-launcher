#!/usr/bin/env python3
"""Launcher do HTPC.

Tela cheia controlada pelo controle (ou pelo teclado):
  * no centro, um botão por app do apps.json; se o app já está aberto,
    o botão traz a janela dele de volta (retoma), nunca abre outro;
  * no canto superior direito: internet, relógio, reiniciar e desligar
    (os dois últimos pedem confirmação).

A janela usa o app id "htpc-launcher", que é o que a extensão do GNOME
procura quando o botão guide pede para mostrar o launcher.

Controle: direcional ou analógico esquerdo move, A abre, B cancela.
Teclado:  setas movem, Enter abre, Esc cancela.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from gi.repository import GLib

# Tem que vir antes do GTK: no Wayland o app id da janela vem daqui.
GLib.set_prgname("htpc-launcher")
GLib.set_application_name("HTPC Launcher")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

try:
    import evdev
    from evdev import ecodes
except ImportError:  # sem evdev o launcher ainda funciona pelo teclado
    evdev = None

CONFIG = (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
          / "htpc-launcher" / "apps.json")
CSS = Path(__file__).with_name("launcher.css")
LAUNCHER_ID = "htpc-launcher"
TEMPO_ABRINDO = 20  # segundos em que um app "está abrindo" e não é aberto de novo


def log(*args):
    print("[launcher]", *args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Extensão do GNOME (D-Bus org.htpc.Launcher)

class Ponte:
    def __init__(self):
        self.proxy = None
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.DO_NOT_AUTO_START | Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None, "org.htpc.Launcher", "/org/htpc/Launcher", "org.htpc.Launcher", None)
        except GLib.Error as e:
            log("sem D-Bus:", e.message)

    def chamar(self, metodo, assinatura=None, *args):
        if self.proxy is None:
            return None
        params = GLib.Variant(assinatura, args) if assinatura else None
        try:
            r = self.proxy.call_sync(metodo, params, Gio.DBusCallFlags.NONE, 2000, None)
            return r.unpack()[0] if r is not None else None
        except GLib.Error as e:
            log(f"extensão não respondeu a {metodo}:", e.message)
            return None

    def ativar(self, app_id, titulos=None):
        if titulos:
            r = self.chamar("ActivatePreferring", "(sas)", app_id, list(titulos))
            if r is not None:
                return bool(r)
            # extensão antiga, sem esse método: traz qualquer janela do app
        return bool(self.chamar("Activate", "(s)", app_id))

    def rodando(self, app_id):
        return bool(self.chamar("IsRunning", "(s)", app_id))

    def ao_mudar_foco(self, callback):
        if self.proxy is not None:
            self.proxy.connect("g-signal", lambda _p, _s, sinal, _a:
                               sinal == "FocusChanged" and callback())


# ---------------------------------------------------------------------------
# Controle (evdev). O launcher lê os botões só enquanto está na frente.

class Controle:
    ZONA_MORTA = 0.55     # quanto do analógico conta como "apertado"
    REPETIR_APOS = 0.40   # segurar uma direção repete depois disso...
    REPETIR_CADA = 0.14   # ...nesse ritmo

    def __init__(self, ativo, mover, confirmar, voltar):
        self.ativo, self.mover, self.confirmar, self.voltar = ativo, mover, confirmar, voltar
        self.devs, self.ignorados, self.watches = {}, set(), {}
        self.eixos = {}         # (caminho, eixo) -> direção atual (-1, 0, 1)
        self.direcao = None     # (dx, dy) sendo segurada
        self.repeticao = 0
        if evdev is None:
            log("python3-evdev não instalado: só teclado")
            return
        self.revarrer()
        GLib.timeout_add_seconds(2, self.revarrer)

    def revarrer(self):
        caminhos = set(evdev.list_devices())
        self.ignorados &= caminhos
        for caminho in caminhos - self.devs.keys() - self.ignorados:
            try:
                dev = evdev.InputDevice(caminho)
            except OSError:
                self.ignorados.add(caminho)
                continue
            teclas = dev.capabilities().get(ecodes.EV_KEY, [])
            if ecodes.BTN_SOUTH in teclas and ecodes.BTN_START in teclas:
                self.devs[caminho] = dev
                self.watches[caminho] = GLib.io_add_watch(
                    dev.fd, GLib.PRIORITY_DEFAULT,
                    GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                    self._ler, caminho)
                log("controle:", dev.name)
            else:
                dev.close()
                self.ignorados.add(caminho)
        return True

    def _remover(self, caminho):
        dev = self.devs.pop(caminho, None)
        self.watches.pop(caminho, None)
        for chave in [k for k in self.eixos if k[0] == caminho]:
            del self.eixos[chave]
        if dev:
            try:
                dev.close()
            except OSError:
                pass

    def _ler(self, _fd, _cond, caminho):
        dev = self.devs.get(caminho)
        if dev is None:
            return False
        try:
            eventos = list(dev.read())
        except (OSError, BlockingIOError) as e:
            if isinstance(e, BlockingIOError):
                return True
            self._remover(caminho)
            return False
        for ev in eventos:
            self._evento(caminho, dev, ev)
        return True

    def _evento(self, caminho, dev, ev):
        if ev.type == ecodes.EV_KEY and ev.value in (0, 1):
            dpad = {ecodes.BTN_DPAD_LEFT: (-1, 0), ecodes.BTN_DPAD_RIGHT: (1, 0),
                    ecodes.BTN_DPAD_UP: (0, -1), ecodes.BTN_DPAD_DOWN: (0, 1)}
            if ev.code in dpad:
                self._segurar(dpad[ev.code] if ev.value else None)
            elif ev.value == 1 and self.ativo():
                if ev.code == ecodes.BTN_SOUTH:
                    self.confirmar()
                elif ev.code == ecodes.BTN_EAST:
                    self.voltar()
        elif ev.type == ecodes.EV_ABS:
            if ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                valor = max(-1, min(1, ev.value))
            elif ev.code in (ecodes.ABS_X, ecodes.ABS_Y):
                info = dev.absinfo(ev.code)
                meio = (info.max + info.min) / 2
                metade = (info.max - info.min) / 2 or 1
                frac = (ev.value - meio) / metade
                valor = 1 if frac > self.ZONA_MORTA else -1 if frac < -self.ZONA_MORTA else 0
            else:
                return
            chave = (caminho, ev.code)
            if self.eixos.get(chave, 0) == valor:
                return
            self.eixos[chave] = valor
            horizontal = ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_X)
            if valor:
                self._segurar((valor, 0) if horizontal else (0, valor))
            elif self.direcao and ((horizontal and self.direcao[0]) or (not horizontal and self.direcao[1])):
                self._segurar(None)

    def _segurar(self, direcao):
        if self.repeticao:
            GLib.source_remove(self.repeticao)
            self.repeticao = 0
        self.direcao = direcao
        if direcao is None or not self.ativo():
            return
        self.mover(*direcao)
        self.repeticao = GLib.timeout_add(int(self.REPETIR_APOS * 1000), self._repetir_inicio)

    def _repetir_inicio(self):
        self.repeticao = GLib.timeout_add(int(self.REPETIR_CADA * 1000), self._repetir)
        return False

    def _repetir(self):
        if self.direcao is None or not self.ativo():
            self.repeticao = 0
            return False
        self.mover(*self.direcao)
        return True


# ---------------------------------------------------------------------------
# Interface

ICONES = Path(__file__).with_name("icones")

# Onde o Flatpak publica os .desktop e os ícones dos apps instalados. Normalmente
# já estão no XDG_DATA_DIRS da sessão; procurar aqui também cobre quando não estão.
EXPORTS_FLATPAK = [Path.home() / ".local/share/flatpak/exports/share",
                   Path("/var/lib/flatpak/exports/share")]


def _info_desktop(nome):
    try:
        info = Gio.DesktopAppInfo.new(nome)
    except TypeError:
        info = None
    if info:
        return info
    for base in EXPORTS_FLATPAK:
        arquivo = base / "applications" / nome
        if arquivo.exists():
            return Gio.DesktopAppInfo.new_from_filename(str(arquivo))
    return None


def icone_do_app(app):
    """O ícone que o próprio app instalou (pelo .desktop dele), ou um genérico.

    "icone" no apps.json troca por outro: nome de ícone do tema ou caminho de arquivo.
    """
    if app.get("icone"):
        icone = os.path.expanduser(app["icone"])
        if not os.path.isabs(icone):
            return Gio.ThemedIcon.new(icone)
        if os.path.exists(icone):
            return Gio.FileIcon.new(Gio.File.new_for_path(icone))
        log("ícone não encontrado:", icone, "- usando o do app")
    for desktop in (app.get("desktop"), f"{app['id']}.desktop"):
        if not desktop:
            continue
        info = _info_desktop(desktop)
        if info and info.get_icon():
            return info.get_icon()
    # O Flatpak também publica o ícone com o nome do próprio id.
    tema = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if tema.has_icon(app["id"]):
        return Gio.ThemedIcon.new(app["id"])
    log("sem ícone para", app["nome"], "- o app está instalado?")
    return Gio.ThemedIcon.new("application-x-executable")


class Tile(Gtk.Button):
    def __init__(self, app, ao_ativar):
        super().__init__()
        self.app = app
        self.add_css_class("tile")
        self.set_focus_on_click(False)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        caixa.set_valign(Gtk.Align.CENTER)
        imagem = Gtk.Image.new_from_gicon(icone_do_app(app))
        imagem.set_pixel_size(128)
        imagem.add_css_class("tile-icone")
        nome = Gtk.Label(label=app["nome"])
        nome.add_css_class("tile-nome")
        self.estado = Gtk.Label(label="")
        self.estado.add_css_class("tile-estado")
        for w in (imagem, nome, self.estado):
            caixa.append(w)
        self.set_child(caixa)
        self.connect("clicked", lambda _b: ao_ativar(self))

    def mostrar_estado(self, texto):
        self.estado.set_label(texto)
        if texto:
            self.add_css_class("aberto")
        else:
            self.remove_css_class("aberto")


class Launcher:
    def __init__(self, app):
        self.gtk_app = app
        self.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.ponte = Ponte()

        tema = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for base in EXPORTS_FLATPAK:
            if (base / "icons").is_dir():
                tema.add_search_path(str(base / "icons"))
        self.abrindo = {}           # app id -> momento em que mandou abrir
        self.modal = None           # (caixa, botões) da confirmação aberta
        self.foco_antes_do_modal = None

        self.win = Gtk.Window(application=app, title="HTPC")
        self.win.add_css_class("htpc")
        self.win.set_default_size(1920, 1080)

        sobrepor = Gtk.Overlay()
        self.win.set_child(sobrepor)

        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        raiz.add_css_class("raiz")
        sobrepor.set_child(raiz)

        raiz.append(self._barra_superior())

        self.grade = Gtk.Box(spacing=48, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True)
        self.tiles = [Tile(a, self.abrir_app) for a in self.cfg.get("apps", [])]
        for t in self.tiles:
            self.grade.append(t)
        raiz.append(self.grade)

        raiz.append(self._barra_inferior())

        self.sobrepor = sobrepor
        self.linhas = [self.tiles, [self.btn_reiniciar, self.btn_desligar]]

        teclas = Gtk.EventControllerKey()
        teclas.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        teclas.connect("key-pressed", self._tecla)
        self.win.add_controller(teclas)

        self.win.connect("notify::is-active", lambda *_: self.win.is_active() and self.atualizar_estados())
        self.ponte.ao_mudar_foco(self.atualizar_estados)

        self.controle = Controle(self.win.is_active, self.mover, self.confirmar, self.voltar)

        self._atualizar_relogio()
        GLib.timeout_add_seconds(1, self._atualizar_relogio)
        self.rede = Gio.NetworkMonitor.get_default()
        self.rede.connect("notify::connectivity", lambda *_: self._atualizar_rede())
        self.rede.connect("network-changed", lambda *_: self._atualizar_rede())
        self._atualizar_rede()
        GLib.timeout_add_seconds(3, self._a_cada_3s)

        self.win.set_cursor(Gdk.Cursor.new_from_name("none", None))
        self.win.fullscreen()
        self.win.present()
        if self.tiles:
            self.tiles[0].grab_focus()
        self.atualizar_estados()

    # --- topo ---------------------------------------------------------------

    def _barra_superior(self):
        barra = Gtk.Box(spacing=28, halign=Gtk.Align.END)
        barra.add_css_class("barra")

        self.rede_ponto = Gtk.Label(label="●")
        self.rede_texto = Gtk.Label(label="")
        rede = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
        rede.add_css_class("rede")
        rede.append(self.rede_ponto)
        rede.append(self.rede_texto)

        relogio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.hora = Gtk.Label(label="", xalign=1)
        self.hora.add_css_class("hora")
        self.data = Gtk.Label(label="", xalign=1)
        self.data.add_css_class("data")
        relogio.append(self.hora)
        relogio.append(self.data)

        for w in (rede, relogio):
            barra.append(w)
        return barra

    # --- rodapé -------------------------------------------------------------------

    def _barra_inferior(self):
        barra = Gtk.Box(spacing=14)
        barra.add_css_class("rodape")

        dica = Gtk.Label(label="Ⓐ abrir    Ⓑ voltar    Guide: volta para cá    Start + Select + L1 + R1: fecha o app",
                         hexpand=True, xalign=0)
        dica.add_css_class("dica")
        barra.append(dica)

        self.btn_reiniciar = self._botao_energia("reiniciar.svg", "Reiniciar",
                                                 lambda: self.confirmar_energia("reiniciar"))
        self.btn_desligar = self._botao_energia("desligar.svg", "Desligar",
                                                lambda: self.confirmar_energia("desligar"))
        barra.append(self.btn_reiniciar)
        barra.append(self.btn_desligar)
        return barra

    def _botao_energia(self, icone, texto, acao):
        b = Gtk.Button()
        b.add_css_class("energia")
        b.set_focus_on_click(False)
        caixa = Gtk.Box(spacing=8)
        img = Gtk.Image.new_from_file(str(ICONES / icone))
        img.set_pixel_size(20)
        rotulo = Gtk.Label(label=texto)
        rotulo.add_css_class("energia-texto")
        caixa.append(img)
        caixa.append(rotulo)
        b.set_child(caixa)
        b.connect("clicked", lambda _b: acao())
        return b

    def _atualizar_relogio(self):
        agora = GLib.DateTime.new_now_local()
        self.hora.set_label(agora.format("%H:%M"))
        dias = ["", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        meses = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
        self.data.set_label(f"{dias[agora.get_day_of_week()]}, {agora.get_day_of_month()} {meses[agora.get_month()]}")
        return True

    def _atualizar_rede(self):
        c = self.rede.get_connectivity()
        if not self.rede.get_network_available() or c == Gio.NetworkConnectivity.LOCAL:
            texto, classe = "Sem internet", "off"
        elif c == Gio.NetworkConnectivity.FULL:
            texto, classe = "Internet", "on"
        else:  # LIMITED ou PORTAL
            texto, classe = "Internet limitada", "meio"
        self.rede_texto.set_label(texto)
        for cl in ("on", "off", "meio"):
            self.rede_ponto.remove_css_class(cl)
        self.rede_ponto.add_css_class(classe)

    def _a_cada_3s(self):
        if self.win.is_active():
            self.atualizar_estados()
        return True

    # --- apps ----------------------------------------------------------------

    def atualizar_estados(self):
        agora = time.monotonic()
        for t in self.tiles:
            app_id = t.app["id"]
            if self.ponte.rodando(app_id):
                self.abrindo.pop(app_id, None)
                t.mostrar_estado("aberto")
            elif agora - self.abrindo.get(app_id, -1e9) < TEMPO_ABRINDO:
                t.mostrar_estado("abrindo…")
            else:
                self.abrindo.pop(app_id, None)
                t.mostrar_estado("")
        return False

    def abrir_app(self, tile):
        app = tile.app
        app_id = app["id"]
        if self.ponte.ativar(app_id, app.get("janelas_preferidas")):
            log("retomando", app["nome"])
            return
        if time.monotonic() - self.abrindo.get(app_id, -1e9) < TEMPO_ABRINDO:
            log(app["nome"], "ainda está abrindo")
            return
        comando = app.get("abrir")
        if not comando:
            log("sem comando para abrir", app["nome"])
            return
        log("abrindo", app["nome"], comando)
        try:
            subprocess.Popen(comando, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log("não abriu:", e)
            return
        self.abrindo[app_id] = time.monotonic()
        tile.mostrar_estado("abrindo…")

    # --- reiniciar / desligar --------------------------------------------------

    def confirmar_energia(self, acao):
        titulo = "Reiniciar o HTPC?" if acao == "reiniciar" else "Desligar o HTPC?"
        fundo = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        fundo.add_css_class("modal-fundo")
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True)
        caixa.add_css_class("modal")
        rotulo = Gtk.Label(label=titulo)
        rotulo.add_css_class("modal-titulo")
        aviso = Gtk.Label(label="O Jellyfin e os outros serviços deste servidor também param.")
        aviso.add_css_class("modal-aviso")
        botoes = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        cancelar = Gtk.Button(label="Cancelar")
        sim = Gtk.Button(label=acao.capitalize())
        sim.add_css_class("perigo")
        for b in (cancelar, sim):
            b.add_css_class("modal-botao")
            b.set_focus_on_click(False)
            botoes.append(b)
        cancelar.connect("clicked", lambda _b: self.fechar_modal())
        sim.connect("clicked", lambda _b: self._executar_energia(acao))
        for w in (rotulo, aviso, botoes):
            caixa.append(w)
        fundo.append(caixa)
        self.sobrepor.add_overlay(fundo)
        self.foco_antes_do_modal = self.win.get_focus()
        self.modal = (fundo, [cancelar, sim])
        cancelar.grab_focus()  # o padrão é não fazer nada

    def fechar_modal(self):
        if not self.modal:
            return
        self.sobrepor.remove_overlay(self.modal[0])
        self.modal = None
        if self.foco_antes_do_modal:
            self.foco_antes_do_modal.grab_focus()

    def _executar_energia(self, acao):
        self.fechar_modal()
        comando = ["systemctl", "reboot" if acao == "reiniciar" else "poweroff"]
        log("executando", comando)
        subprocess.Popen(comando, start_new_session=True)

    # --- navegação ---------------------------------------------------------------

    def _linhas_atuais(self):
        return [self.modal[1]] if self.modal else self.linhas

    def _centro_x(self, w):
        ok, r = w.compute_bounds(self.win)
        return r.get_x() + r.get_width() / 2 if ok else 0

    def mover(self, dx, dy):
        linhas = self._linhas_atuais()
        foco = self.win.get_focus()
        pos = next(((i, j) for i, linha in enumerate(linhas)
                    for j, w in enumerate(linha) if w is foco), None)
        if pos is None:
            alvo = linhas[-1][0] if linhas[-1] else None
        elif dx:
            i, j = pos
            alvo = linhas[i][max(0, min(len(linhas[i]) - 1, j + dx))]
        else:
            i = max(0, min(len(linhas) - 1, pos[0] + dy))
            if i == pos[0] or not linhas[i]:
                return
            x = self._centro_x(foco)
            alvo = min(linhas[i], key=lambda w: abs(self._centro_x(w) - x))
        if alvo is not None:
            alvo.grab_focus()

    def confirmar(self):
        foco = self.win.get_focus()
        if isinstance(foco, Gtk.Button):
            foco.emit("clicked")

    def voltar(self):
        self.fechar_modal()

    def _tecla(self, _ctl, tecla, _cod, _mod):
        direcoes = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0),
                    Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if tecla in direcoes:
            self.mover(*direcoes[tecla])
        elif tecla in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.confirmar()
        elif tecla == Gdk.KEY_Escape:
            self.voltar()
        else:
            return False
        return True


def main():
    if not CONFIG.exists():
        raise SystemExit(f"Falta o arquivo de configuração: {CONFIG}")

    # Já existe um launcher aberto? Então só traz ele para a frente.
    if Ponte().ativar(LAUNCHER_ID):
        log("já estava aberto")
        return

    app = Gtk.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)
    estado = {}

    def ativar(a):
        if "launcher" in estado:
            return
        provedor = Gtk.CssProvider()
        provedor.load_from_path(str(CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        estado["launcher"] = Launcher(a)

    app.connect("activate", ativar)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
