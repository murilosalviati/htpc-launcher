"""Roda o launcher no Xvfb com a extensão falsa, navega, tira capturas e confere abrir/retomar."""
import os, sys, tempfile, time, json
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "launcher"))
sys.path.insert(0, os.path.dirname(__file__))

cfgdir = tempfile.mkdtemp()
os.makedirs(f"{cfgdir}/htpc-launcher")
cfg = json.load(open(os.path.join(RAIZ, "config", "apps.json")))
# comandos de abrir inofensivos para o teste
for a in cfg["apps"]:
    a["abrir"] = ["true"]
json.dump(cfg, open(f"{cfgdir}/htpc-launcher/apps.json", "w"))
os.environ["XDG_CONFIG_HOME"] = cfgdir

import falsos
falsos.estado["janelas"] = [j for j in falsos.estado["janelas"] if j["appId"] == "org.jellyfin.JellyfinDesktop"]
falsos.estado["foco"] = "htpc-launcher"
# o Steam abre três janelas; a última usada é a "Friends List"
for titulo in ("Friends List", "Special Offers", "Steam"):
    falsos.estado["janelas"].insert(0, {"appId": "com.valvesoftware.Steam", "ids": ["com.valvesoftware.steam", "steam", "steamwebhelper"],
                                        "title": titulo, "pid": 0, "minimized": False})
falsos.iniciar()
time.sleep(0.4)

import launcher
from gi.repository import GLib, Gtk

SAIDA = os.path.join(tempfile.gettempdir(), "htpc-capturas")
os.makedirs(SAIDA, exist_ok=True)
ok = True
def confere(nome, cond):
    global ok
    print(("OK   " if cond else "FALHOU ") + nome, flush=True); ok &= bool(cond)

def capturar(win, nome):
    p = Gtk.WidgetPaintable.new(win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    p.snapshot(snap, w, h)
    tex = win.get_native().get_renderer().render_texture(snap.to_node(), None)
    tex.save_to_png(f"{SAIDA}/{nome}.png")

estado = {}
orig_init = launcher.Launcher.__init__
def init(self, app):
    orig_init(self, app)
    estado["l"] = self
launcher.Launcher.__init__ = init
launcher.Launcher.atualizar_estados  # noqa

passos = []
def passo(atraso_ms):
    def dec(f):
        passos.append((atraso_ms, f)); return f
    return dec

def L(): return estado["l"]

@passo(1500)
def p1():
    l = L()
    confere("janela tem tamanho de tela", l.win.get_width() >= 1280)
    confere("foco começa no 1º app", l.win.get_focus() is l.tiles[0])
    confere("Jellyfin aparece como aberto", l.tiles[1].estado.get_label() == "aberto")
    capturar(l.win, "1-inicio")

@passo(300)
def p2():
    l = L()
    l.mover(1, 0)
    confere("direita vai para o 2º app", l.win.get_focus() is l.tiles[1])
    n = len(falsos.estado["log"])
    l.confirmar()
    confere("abrir app já aberto chama Activate (retoma)", ("Activate", ("org.jellyfin.JellyfinDesktop",)) in falsos.estado["log"][n:])
    confere("app já aberto não é aberto de novo", "org.jellyfin.JellyfinDesktop" not in l.abrindo)

@passo(300)
def p3():
    l = L()
    l.mover(-1, 0)
    l.confirmar()
    confere("abrir app fechado mostra 'abrindo…'", l.tiles[0].estado.get_label() == "abrindo…")
    n = len(falsos.estado["log"]); antes = dict(l.abrindo)
    l.confirmar()
    confere("apertar de novo enquanto abre não abre outro", l.abrindo == antes)

@passo(300)
def p4():
    l = L()
    l.mover(1, 0); l.mover(1, 0); l.mover(1, 0); l.mover(1, 0)
    confere("não passa do último app", l.win.get_focus() is l.tiles[-1])
    capturar(l.win, "2-ultimo-app")
    l.mover(0, 1)
    confere("baixo vai para os botões de energia (mais próximo)", l.win.get_focus() in (l.btn_reiniciar, l.btn_desligar))
    l.mover(-1, 0)
    l.mover(1, 0)
    confere("direita na barra chega no Desligar", l.win.get_focus() is l.btn_desligar)

@passo(400)
def p4b():
    capturar(L().win, "3-desligar-em-foco")

@passo(100)
def p5():
    l = L()
    chamados = []
    import subprocess
    orig = subprocess.Popen
    l._popen_orig = orig
    l.confirmar()
    confere("Desligar abre confirmação", l.modal is not None)
    confere("foco padrão é Cancelar", l.win.get_focus() is l.modal[1][0])
    l.mover(0, 1)
    confere("baixo no modal não sai do modal", l.win.get_focus() in l.modal[1])

@passo(400)
def p6():
    l = L()
    capturar(l.win, "4-confirmar-desligar")
    l.voltar()
    confere("B fecha a confirmação", l.modal is None)
    confere("foco volta ao Desligar", l.win.get_focus() is l.btn_desligar)
    l.mover(0, -1)
    confere("cima volta aos apps", l.win.get_focus() in l.tiles)
    l.mover(0, -1)
    confere("cima nos apps não sai dos apps", l.win.get_focus() in l.tiles)

@passo(300)
def p7():
    l = L()
    steam = next(t for t in l.tiles if t.app["nome"] == "Steam")
    steam.grab_focus(); l.confirmar()
    confere("Steam aberto: traz a janela 'Steam', não a 'Friends List'", falsos.estado.get("ativada") == "Steam")
    confere("Steam aberto não é aberto de novo", "com.valvesoftware.Steam" not in l.abrindo)

@passo(300)
def p8():
    l = L()
    from gi.repository import Gio
    class Rede:
        def __init__(self, ok, c): self.ok, self.c = ok, c
        def get_network_available(self): return self.ok
        def get_connectivity(self): return self.c
    real = l.rede
    l.rede = Rede(True, Gio.NetworkConnectivity.FULL); l._atualizar_rede()
    confere("conectado: só o ícone, sem texto", l.estado_rede == "on" and not l.rede_texto.get_visible())
    l.rede = Rede(True, Gio.NetworkConnectivity.LIMITED); l._atualizar_rede()
    confere("internet limitada mostra texto", l.estado_rede == "meio" and l.rede_texto.get_label() == "internet limitada")
    l.rede = Rede(False, Gio.NetworkConnectivity.LOCAL); l._atualizar_rede()
    confere("sem internet mostra texto", l.estado_rede == "off" and l.rede_texto.get_visible())
    estado["rede_real"] = real

@passo(500)
def p9():
    capturar(L().win, "5-sem-internet")
    L().rede = estado["rede_real"]; L()._atualizar_rede()

@passo(500)
def p10():
    capturar(L().win, "6-conectado")

@passo(200)
def fim():
    L().win.get_application().quit()

def agendar(i=0, acumulado=0):
    for atraso, f in passos:
        acumulado += atraso
        GLib.timeout_add(acumulado, lambda f=f: (f(), False)[1])

GLib.idle_add(lambda: (agendar(), False)[1])
sys.argv = ["launcher.py"]
launcher.main()
print("\nTUDO OK" if ok else "\nHOUVE FALHAS")
