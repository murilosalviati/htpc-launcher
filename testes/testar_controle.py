import os, sys, time, json, tempfile, logging
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from types import SimpleNamespace
sys.path.insert(0, os.path.join(RAIZ, "controle"))
sys.path.insert(0, os.path.dirname(__file__))

cfgdir = tempfile.mkdtemp()
os.makedirs(f"{cfgdir}/htpc-launcher")
os.system(f"cp {RAIZ}/config/apps.json {cfgdir}/htpc-launcher/")
os.environ["XDG_CONFIG_HOME"] = cfgdir

import controle
from evdev import ecodes
import falsos

logging.basicConfig(level="INFO", format="  [log] %(message)s")
controle.INTERVALO_ENTRE_ACOES = 0.3
controle.ESPERA_FECHAR_PADRAO = 1.0
mortos = []
controle.forcar_fechamento = lambda app, pid: mortos.append(app) or [falsos.estado["janelas"].remove(j) for j in falsos.achar(app)]

falsos.iniciar()
time.sleep(0.5)

c = controle.Controles(controle.Acoes())
c.apertados["pad"] = set()
def aperta(*botoes):
    for b in botoes: c.tratar("pad", SimpleNamespace(type=ecodes.EV_KEY, code=b, value=1))
    for b in botoes: c.tratar("pad", SimpleNamespace(type=ecodes.EV_KEY, code=b, value=0))
COMBO = (ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_TL, ecodes.BTN_TR)
E = falsos.estado
def abertos(): return [j["appId"] for j in E["janelas"]]
ok = True
def confere(nome, cond):
    global ok
    print(("OK   " if cond else "FALHOU ") + nome); ok &= bool(cond)

# 1. guide no Jellyfin tocando: pausa e mostra launcher, Jellyfin continua aberto
aperta(ecodes.BTN_MODE); time.sleep(0.2)
confere("guide pausa o vídeo", E["player"] == "Paused")
confere("guide mostra o launcher", E["foco"] == "htpc-launcher")
confere("Jellyfin continua aberto", "org.jellyfin.JellyfinDesktop" in abertos())

# 2. repetição do controle virtual do Steam é ignorada
n = len(E["log"]); aperta(ecodes.BTN_MODE); time.sleep(0.1)
confere("guide repetido logo em seguida é ignorado", len(E["log"]) == n)
time.sleep(0.4)

# 3. combo com o launcher em foco não faz nada
aperta(*COMBO); time.sleep(0.3)
confere("combo no launcher não fecha nada", len(abertos()) == 5)
time.sleep(0.4)

# 4. combo no YouTube fecha e volta ao launcher
E["foco"] = "rocks.shy.VacuumTube"
aperta(*COMBO); time.sleep(0.8)
confere("combo fecha o YouTube", "rocks.shy.VacuumTube" not in abertos())
confere("depois de fechar, launcher na frente", E["foco"] == "htpc-launcher")

# 5. Moonlight: 1º toque não fecha, 2º fecha
E["foco"] = "com.moonlight_stream.Moonlight"; time.sleep(0.4)
aperta(*COMBO); time.sleep(0.5)
confere("1º toque no Moonlight não fecha", "com.moonlight_stream.Moonlight" in abertos())
E["foco"] = "com.moonlight_stream.Moonlight"
aperta(*COMBO); time.sleep(0.8)
confere("2º toque fecha o Moonlight", "com.moonlight_stream.Moonlight" not in abertos())

# 6. app teimoso: força o fechamento depois da espera
E["foco"] = "jogo"; time.sleep(0.4)
aperta(*COMBO); time.sleep(1.8)
confere("app que não fecha é forçado", mortos == ["jogo"] and "jogo" not in abertos())

# 7. só três botões do combo não fecham
E["foco"] = "org.jellyfin.JellyfinDesktop"; time.sleep(0.4)
aperta(ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_TL); time.sleep(0.4)
confere("combo incompleto não fecha", "org.jellyfin.JellyfinDesktop" in abertos())

print("\nTUDO OK" if ok else "\nHOUVE FALHAS")
sys.exit(0 if ok else 1)
