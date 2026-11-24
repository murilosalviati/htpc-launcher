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
    l.apertar()
    confere("abrir app já aberto chama Activate (retoma)", ("Activate", ("org.jellyfin.JellyfinDesktop",)) in falsos.estado["log"][n:])
    confere("app já aberto não é aberto de novo", "org.jellyfin.JellyfinDesktop" not in l.abrindo)

@passo(300)
def p3():
    l = L()
    l.mover(-1, 0)
    l.apertar()
    confere("abrir app fechado mostra 'abrindo…'", l.tiles[0].estado.get_label() == "abrindo…")
    n = len(falsos.estado["log"]); antes = dict(l.abrindo)
    l.apertar()
    confere("apertar de novo enquanto abre não abre outro", l.abrindo == antes)

@passo(300)
def p4():
    l = L()
    l.mover(1, 0); l.mover(1, 0); l.mover(1, 0); l.mover(1, 0)
    confere("não passa do último app", l.win.get_focus() is l.tiles[-1])
    capturar(l.win, "2-ultimo-app")
    l.mover(0, 1)
    confere("baixo vai para o rodapé (botão mais próximo)", l.win.get_focus() in (l.btn_config, l.btn_reiniciar, l.btn_desligar))
    l.mover(-1, 0)
    l.mover(1, 0); l.mover(1, 0); l.mover(1, 0)
    confere("direita no rodapé chega no Desligar", l.win.get_focus() is l.btn_desligar)

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
    l.apertar()
    confere("Desligar abre confirmação", len(l.modais) == 1)
    confere("foco padrão é Cancelar", l.win.get_focus() is l.modais[-1]["linhas"][0][0])
    l.mover(0, 1)
    confere("baixo no modal não sai do modal", l.win.get_focus() in l.modais[-1]["linhas"][0])

@passo(400)
def p6():
    l = L()
    capturar(l.win, "4-confirmar-desligar")
    l.voltar()
    confere("B fecha a confirmação", not l.modais)
    confere("foco volta ao Desligar", l.win.get_focus() is l.btn_desligar)
    l.mover(0, -1)
    confere("cima volta aos apps", l.win.get_focus() in l.tiles)
    l.mover(0, -1)
    confere("cima nos apps não sai dos apps", l.win.get_focus() in l.tiles)

@passo(300)
def p7():
    l = L()
    steam = next(t for t in l.tiles if t.app["nome"] == "Steam")
    steam.grab_focus(); l.apertar()
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

# ---------------- modo de edição ----------------
def apps_cfg(): return L().cfg["apps"]
def apps_disco(): return json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))["apps"]

@passo(300)
def e1():
    l = L()
    l.tiles[-1].grab_focus(); l.mover(0, 1)
    confere("baixo a partir do último app chega no rodapé", l.win.get_focus() in (l.btn_config, l.btn_reiniciar, l.btn_desligar))
    l.btn_config.grab_focus(); l.apertar()
    confere("engrenagem entra no modo de edição", l.editando and l.tile_novo is not None)
    confere("dica muda para o modo de edição", "Modo de edição" in l.dica.get_label())
    confere("botão vira Concluir", l.btn_config.rotulo.get_label() == "Concluir")

@passo(500)
def e2():
    l = L()
    capturar(l.win, "7-modo-edicao")
    l.tiles[2].grab_focus(); l.apertar()
    confere("Ⓐ num app abre o editor", len(l.modais) == 1 and l.edicao["indice"] == 2)
    confere("editor começa no Nome", l.win.get_focus() is l.campo_nome)

@passo(500)
def e3():
    l = L()
    capturar(l.win, "8-editor")
    l.apertar()
    m = l.modais[-1]
    confere("Nome abre o teclado da tela", "digitar" in m)
    for _ in range(20): l.outro_botao("x")
    for c in "jogos": m["digitar"](c)
    l.outro_botao("y"); m["digitar"]("2")

@passo(500)
def e4():
    l = L()
    capturar(l.win, "9-teclado")
    l.modais[-1]["enter"]()
    confere("teclado: maiúscula automática, X apaga, Y põe espaço", l.edicao["r"]["nome"] == "Jogos 2")
    l.mover(0, 1); l.mover(0, 1)
    confere("baixo chega no campo Ícone", l.win.get_focus() is l.campo_icone)
    l.apertar()
    linhas = l.modais[-1]["linhas"]
    confere("escolha de ícone mostra o do app e os 4 da pasta", sum(len(x) for x in linhas) == 5)

@passo(500)
def e5():
    l = L()
    capturar(l.win, "10-escolher-icone")
    l.modais[-1]["linhas"][0][1].grab_focus(); l.apertar()
    confere("ícone escolhido vai para o rascunho", l.edicao["r"].get("icone", "").endswith("icones-apps/jellyfin.png"))
    l.modais[-1]["linhas"][3][0].grab_focus(); l.apertar()  # Salvar
    a = apps_disco()[2]
    confere("salvar grava nome e ícone no apps.json", a["nome"] == "Jogos 2" and a["icone"].endswith("jellyfin.png"))
    confere("salvar mantém o app e os ajustes dele", a["id"] == "com.moonlight_stream.Moonlight" and a.get("fechar_em_dois_toques") is True)
    confere("depois de salvar, foco volta no app editado", l.win.get_focus() is l.tiles[2] and not l.modais)

@passo(300)
def e6():
    l = L()
    l.tile_novo.grab_focus(); l.apertar()
    confere("+ Adicionar abre editor de app novo, no campo Aplicativo", l.edicao["indice"] is None and l.win.get_focus() is l.campo_app)
    l.modais[-1]["linhas"][3][0].grab_focus(); l.apertar()
    confere("salvar sem escolher app mostra erro", l.edicao_erro.get_visible() and len(l.modais) == 1)
    l.campo_app.grab_focus(); l.apertar()
    botoes = [b for linha in l.modais[-1]["linhas"] for b in linha]
    nomes = [b.get_child().get_last_child().get_label() for b in botoes]
    confere("lista de apps traz os instalados (Flatpak e .desktop do usuário)", "Exemplo Player" in nomes and "rocks.shy.VacuumTube" in nomes)
    estado["botao_exemplo"] = botoes[nomes.index("Exemplo Player")]

@passo(500)
def e7():
    l = L()
    capturar(l.win, "11-escolher-app")
    estado["botao_exemplo"].grab_focus(); l.apertar()
    r = l.edicao["r"]
    confere("app escolhido preenche id, comando e nome", r["id"] == "org.exemplo.Player" and r["abrir"][:2] == ["gio", "launch"] and r["nome"] == "Exemplo Player")
    confere("app escolhido guarda o WM_CLASS como nome extra", r.get("outros_ids") == ["exemplo-player"])
    l.modais[-1]["linhas"][3][0].grab_focus(); l.apertar()
    confere("app novo entra no fim da lista", apps_disco()[-1]["id"] == "org.exemplo.Player" and len(l.tiles) == 5)
    confere("com 5 apps + Adicionar, a grade quebra em 2 linhas", len(l.linhas_grade) == 2)

@passo(500)
def e8():
    l = L()
    capturar(l.win, "12-cinco-apps")
    l.tiles[0].grab_focus(); l.apertar()
    remover = l.modais[-1]["linhas"][3][1]
    confere("editor de app existente tem Remover", remover.get_label() == "Remover")
    remover.grab_focus(); l.apertar()
    confere("Remover pede confirmação, com foco em Cancelar", len(l.modais) == 2 and l.win.get_focus() is l.modais[-1]["linhas"][0][0])
    l.mover(1, 0); l.apertar()
    ids = [a["id"] for a in apps_disco()]
    confere("app removido sai do apps.json", "rocks.shy.VacuumTube" not in ids and len(ids) == 4)
    confere("tela se reorganiza: 4 apps + Adicionar numa linha só", len(l.tiles) == 4 and len(l.linhas_grade) == 1 and not l.modais)
    confere("foco vai para o app que ficou no lugar", l.win.get_focus() is l.tiles[0])

@passo(500)
def e9():
    l = L()
    capturar(l.win, "13-depois-de-remover")
    l.voltar()
    confere("Ⓑ sai do modo de edição", not l.editando and l.tile_novo is None and l.btn_config.rotulo.get_label() == "Editar apps")

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
