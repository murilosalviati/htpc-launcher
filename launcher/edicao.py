"""Modo de edição do launcher: adicionar, editar e remover atalhos de apps.

Entra pelo botão "Editar apps" do rodapé. Nele, Ⓐ num app abre o editor e
Ⓐ no "+ Adicionar" cria um atalho novo. O editor tem três campos:

  * Nome: digitado no teclado da tela (ou num teclado de verdade);
  * Aplicativo: escolhido entre os apps instalados (.desktop do sistema e
    do Flatpak);
  * Ícone: o do próprio app ou uma imagem da pasta de ícones
    (~/.local/share/htpc-launcher/icones-apps).

Tudo é gravado no apps.json, que o serviço do controle também lê.

Este arquivo não importa o launcher.py: o que precisa de lá vem pela
própria classe Launcher (icone_do_app, info_desktop, pasta_icones_apps...).
"""

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, Gtk, Pango  # noqa: E402

DICA_NORMAL = "Ⓐ abrir    Ⓑ voltar    Guide: volta para cá    Start + Select + L1 + R1: fecha o app"
DICA_EDICAO = "Modo de edição    Ⓐ editar ou adicionar    Ⓑ sair da edição"

# Ajustes que só valem para o aplicativo original do atalho. Se o atalho
# passar a abrir outro aplicativo, eles são descartados.
CAMPOS_DO_APP = ("outros_ids", "desktop", "fechar", "espera_fechar",
                 "janelas_preferidas", "pausar_ao_sair", "fechar_em_dois_toques")

TECLAS = ["1234567890", "qwertyuiop", "asdfghjklç", "zxcvbnm-.'&"]
EXTENSOES_ICONE = (".png", ".svg", ".jpg", ".jpeg", ".webp")


def _com_til(caminho):
    """Caminho com ~ no lugar da pasta do usuário, como no apps.json."""
    casa = str(Path.home())
    caminho = str(caminho)
    return "~" + caminho[len(casa):] if caminho.startswith(casa + os.sep) else caminho


class EdicaoMixin:
    # --- entrar e sair do modo de edição -----------------------------------------

    def alternar_edicao(self):
        self.editando = not self.editando
        self.dica.set_label(DICA_EDICAO if self.editando else DICA_NORMAL)
        if self.editando:
            self.dica.add_css_class("edicao")
            self.btn_config.rotulo.set_label("Concluir")
        else:
            self.dica.remove_css_class("edicao")
            self.btn_config.rotulo.set_label("Editar apps")
        self.montar_grade(focar=0 if self.cfg.get("apps") else -1)

    def novo_app(self):
        self.editar_app(None)

    # --- editor ----------------------------------------------------------------------

    def editar_app(self, indice):
        original = dict(self.cfg["apps"][indice]) if indice is not None else {}
        r = {"nome": original.get("nome", "")}
        for k in ("id", "abrir", "icone", *CAMPOS_DO_APP):
            if k in original:
                r[k] = original[k]
        self.edicao = {"indice": indice, "original": original, "r": r}

        caixa = self.caixa_modal("Editar app" if indice is not None else "Novo app")
        caixa.add_css_class("editor")
        self.edicao_preview = Gtk.Image()
        self.edicao_preview.set_pixel_size(112)
        caixa.append(self.edicao_preview)

        self.campo_nome = self._campo("Nome", self._editar_nome)
        self.campo_app = self._campo("Aplicativo", self._escolher_app)
        self.campo_icone = self._campo("Ícone", self._escolher_icone)
        for c in (self.campo_nome, self.campo_app, self.campo_icone):
            caixa.append(c)

        self.edicao_erro = Gtk.Label(label="")
        self.edicao_erro.add_css_class("erro")
        self.edicao_erro.set_visible(False)
        caixa.append(self.edicao_erro)

        botoes = [self.botao_modal("Salvar", self._salvar_app)]
        if indice is not None:
            botoes.append(self.botao_modal("Remover", self._remover_app, perigo=True))
        botoes.append(self.botao_modal("Cancelar", self.fechar_modal))
        caixa_botoes = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        caixa_botoes.add_css_class("editor-botoes")
        for b in botoes:
            caixa_botoes.append(b)
        caixa.append(caixa_botoes)

        self._atualizar_editor()
        linhas = [[self.campo_nome], [self.campo_app], [self.campo_icone], botoes]
        # Num atalho novo, o natural é escolher o app primeiro (o nome vem dele).
        self.abrir_modal(caixa, linhas, foco=self.campo_app if indice is None else self.campo_nome)

    def _campo(self, titulo, acao):
        b = Gtk.Button()
        b.add_css_class("campo")
        b.set_focus_on_click(False)
        caixa = Gtk.Box(spacing=24)
        t = Gtk.Label(label=titulo, xalign=0)
        t.add_css_class("campo-titulo")
        t.set_size_request(190, -1)
        b.valor = Gtk.Label(label="", xalign=0, hexpand=True,
                            ellipsize=Pango.EllipsizeMode.END, max_width_chars=36)
        b.valor.add_css_class("campo-valor")
        seta = Gtk.Label(label="›")
        seta.add_css_class("campo-seta")
        for w in (t, b.valor, seta):
            caixa.append(w)
        b.set_child(caixa)
        b.connect("clicked", lambda _b: acao())
        return b

    def _descricao_app(self, r):
        for nome in (r.get("desktop"), f"{r['id']}.desktop" if r.get("id") else None):
            if nome:
                info = self.info_desktop(nome)
                if info:
                    return info.get_display_name()
        if r.get("abrir"):
            return " ".join(r["abrir"])
        return "Escolher…"

    def _atualizar_editor(self):
        r = self.edicao["r"]
        self.campo_nome.valor.set_label(r["nome"] or "Sem nome")
        self.campo_app.valor.set_label(self._descricao_app(r))
        icone = r.get("icone")
        self.campo_icone.valor.set_label(Path(os.path.expanduser(icone)).name if icone
                                         else "Ícone do próprio app")
        self.edicao_preview.set_from_gicon(self.icone_do_app(r))
        self.edicao_preview.set_pixel_size(112)
        self.edicao_erro.set_visible(False)

    def _erro(self, texto):
        self.edicao_erro.set_label(texto)
        self.edicao_erro.set_visible(True)

    def _salvar_app(self):
        r = self.edicao["r"]
        if not r.get("id") or not r.get("abrir"):
            self._erro("Escolha o aplicativo que o atalho abre.")
            return
        if not r["nome"].strip():
            self._erro("Dê um nome ao atalho.")
            return
        original, indice = self.edicao["original"], self.edicao["indice"]

        # Mesmo app: preserva os ajustes que existiam. App novo: começa do zero.
        base = dict(original) if r["id"] == original.get("id") else {}
        for k in CAMPOS_DO_APP:
            base.pop(k, None)
        novo = {"nome": r["nome"].strip(), "id": r["id"]}
        if r.get("icone"):
            novo["icone"] = r["icone"]
        novo["abrir"] = r["abrir"]
        for k, v in base.items():
            if k != "icone":  # o ícone já veio do rascunho (ou foi tirado)
                novo.setdefault(k, v)
        for k in CAMPOS_DO_APP:
            if k in r:
                novo[k] = r[k]

        apps = self.cfg.setdefault("apps", [])
        if indice is None:
            apps.append(novo)
            indice = len(apps) - 1
        else:
            apps[indice] = novo
        self.salvar_config()
        self.fechar_modal()
        self.montar_grade(focar=indice)

    def _remover_app(self):
        indice = self.edicao["indice"]
        nome = self.cfg["apps"][indice].get("nome", "este app")
        self.confirmar(f"Remover {nome}?",
                       "O aplicativo continua instalado. Só o atalho sai da tela.",
                       "Remover", lambda: self._remover_confirmado(indice))

    def _remover_confirmado(self, indice):
        apps = self.cfg["apps"]
        del apps[indice]
        self.salvar_config()
        self.fechar_modal()  # fecha o editor (a confirmação já fechou)
        self.montar_grade(focar=min(indice, len(apps) - 1) if apps else -1)

    # --- nome: teclado na tela ------------------------------------------------------------

    def _editar_nome(self):
        self.teclado("Nome do atalho", self.edicao["r"]["nome"], self._nome_digitado)

    def _nome_digitado(self, texto):
        self.edicao["r"]["nome"] = texto
        self._atualizar_editor()

    def teclado(self, titulo, valor, ao_confirmar):
        # Maiúscula automática na primeira letra, como num celular.
        estado = {"texto": valor, "maiusc": not valor}
        caixa = self.caixa_modal(titulo)
        caixa.add_css_class("teclado")
        visor = Gtk.Label(label="", xalign=0)
        visor.add_css_class("teclado-visor")
        caixa.append(visor)

        teclas_letra = []

        def atualizar():
            visor.set_label(estado["texto"] + "▏")
            for b in teclas_letra:
                b.set_label(b.letra.upper() if estado["maiusc"] else b.letra)

        def digitar(c):
            if estado["maiusc"] and c.isalpha():
                c = c.upper()
                estado["maiusc"] = False
            estado["texto"] += c
            atualizar()

        def apagar():
            estado["texto"] = estado["texto"][:-1]
            if not estado["texto"]:
                estado["maiusc"] = True  # apagou tudo: recomeça com maiúscula
            atualizar()

        def alternar_maiusc():
            estado["maiusc"] = not estado["maiusc"]
            atualizar()

        def ok():
            self.fechar_modal()
            ao_confirmar(estado["texto"].strip())

        linhas = []
        for texto_linha in TECLAS:
            caixa_linha = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
            linha = []
            for c in texto_linha:
                b = Gtk.Button(label=c)
                b.letra = c
                b.add_css_class("tecla")
                b.set_focus_on_click(False)
                b.connect("clicked", lambda _b: digitar(_b.get_label()))
                teclas_letra.append(b)
                caixa_linha.append(b)
                linha.append(b)
            caixa.append(caixa_linha)
            linhas.append(linha)

        especiais = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        linha = []
        for rotulo, acao, classe in (("⇧ Maiúsc", alternar_maiusc, "tecla-larga"),
                                     ("Espaço", lambda: digitar(" "), "tecla-espaco"),
                                     ("⌫ Apagar", apagar, "tecla-larga"),
                                     ("OK", ok, "tecla-ok")):
            b = Gtk.Button(label=rotulo)
            b.add_css_class("tecla")
            b.add_css_class(classe)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, a=acao: a())
            especiais.append(b)
            linha.append(b)
        caixa.append(especiais)
        linhas.append(linha)

        dica = Gtk.Label(label="Ⓧ apagar    Ⓨ espaço    Ⓑ cancelar")
        dica.add_css_class("modal-aviso")
        caixa.append(dica)

        atualizar()
        self.abrir_modal(caixa, linhas, foco=linhas[1][0],
                         digitar=digitar, apagar=apagar, espaco=lambda: digitar(" "), enter=ok)

    # --- aplicativo: lista dos instalados ----------------------------------------------------

    def _apps_instalados(self):
        vistos = {}
        for info in Gio.AppInfo.get_all():
            if isinstance(info, Gio.DesktopAppInfo) and info.should_show():
                vistos[info.get_id()] = info
        # Apps do Flatpak, caso a sessão não esteja olhando a pasta deles.
        for base in self.exports_flatpak:
            pasta = base / "applications"
            if not pasta.is_dir():
                continue
            for arquivo in pasta.glob("*.desktop"):
                if arquivo.name in vistos:
                    continue
                info = Gio.DesktopAppInfo.new_from_filename(str(arquivo))
                if info and info.should_show():
                    vistos[arquivo.name] = info
        vistos.pop(f"{self.launcher_id}.desktop", None)
        return sorted(vistos.values(), key=lambda i: i.get_display_name().casefold())

    def _escolher_app(self):
        infos = self._apps_instalados()
        caixa = self.caixa_modal("Escolha o aplicativo")
        caixa.add_css_class("lista")

        grade = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        linhas, foco = [], None
        atual = self.edicao["r"].get("id")
        for i in range(0, len(infos), 4):
            caixa_linha = Gtk.Box(spacing=12, halign=Gtk.Align.START)
            linha = []
            for info in infos[i:i + 4]:
                b = Gtk.Button()
                b.add_css_class("item-app")
                b.set_focus_on_click(False)
                b.set_size_request(280, -1)
                b.set_hexpand(False)
                dentro = Gtk.Box(spacing=16)
                img = Gtk.Image.new_from_gicon(info.get_icon() or Gio.ThemedIcon.new("application-x-executable"))
                img.set_pixel_size(48)
                nome = Gtk.Label(label=info.get_display_name(), xalign=0, hexpand=True,
                                 ellipsize=Pango.EllipsizeMode.END, width_chars=14, max_width_chars=14)
                dentro.append(img)
                dentro.append(nome)
                b.set_child(dentro)
                b.connect("clicked", lambda _b, info=info: self._app_escolhido(info))
                if atual and info.get_id() == f"{atual}.desktop":
                    foco = b
                caixa_linha.append(b)
                linha.append(b)
            grade.append(caixa_linha)
            linhas.append(linha)

        if not infos:
            vazio = Gtk.Label(label="Nenhum aplicativo instalado foi encontrado.")
            vazio.add_css_class("modal-aviso")
            caixa.append(vazio)
            voltar = self.botao_modal("Voltar", self.fechar_modal)
            caixa.append(voltar)
            linhas = [[voltar]]
        else:
            rolagem = Gtk.ScrolledWindow()
            rolagem.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            rolagem.set_size_request(1180, 560)
            rolagem.set_child(grade)
            caixa.append(rolagem)
        self.abrir_modal(caixa, linhas, foco=foco)

    def _app_escolhido(self, info):
        r, original = self.edicao["r"], self.edicao["original"]
        desktop_id = info.get_id()
        app_id = desktop_id[:-len(".desktop")] if desktop_id.endswith(".desktop") else desktop_id
        for k in ("abrir", *CAMPOS_DO_APP):
            r.pop(k, None)
        if app_id == original.get("id"):
            # Voltou para o app de antes: mantém o comando e os ajustes dele.
            for k in ("abrir", *CAMPOS_DO_APP):
                if k in original:
                    r[k] = original[k]
        else:
            r["abrir"] = ["gio", "launch", info.get_filename()]
            r["desktop"] = desktop_id
            wm_class = info.get_startup_wm_class()
            if wm_class:
                r["outros_ids"] = [wm_class]
        r["id"] = app_id
        if not r["nome"].strip():
            r["nome"] = info.get_display_name()
        self.fechar_modal()
        self._atualizar_editor()

    # --- ícone ---------------------------------------------------------------------------------

    def _escolher_icone(self):
        r = self.edicao["r"]
        sem_icone = {k: v for k, v in r.items() if k != "icone"}
        opcoes = [(None, "Ícone do app", self.icone_do_app(sem_icone))]
        pasta = self.pasta_icones_apps
        if pasta.is_dir():
            for arquivo in sorted(pasta.iterdir()):
                if arquivo.suffix.lower() in EXTENSOES_ICONE:
                    opcoes.append((_com_til(arquivo), arquivo.stem,
                                   Gio.FileIcon.new(Gio.File.new_for_path(str(arquivo)))))

        caixa = self.caixa_modal("Escolha o ícone",
                                 f"Para ter mais opções, ponha imagens PNG em {_com_til(pasta)}")
        grade = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, halign=Gtk.Align.CENTER)
        linhas, foco = [], None
        for i in range(0, len(opcoes), 5):
            caixa_linha = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
            linha = []
            for valor, rotulo, gicon in opcoes[i:i + 5]:
                b = Gtk.Button()
                b.add_css_class("item-icone")
                b.set_focus_on_click(False)
                dentro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                img = Gtk.Image.new_from_gicon(gicon)
                img.set_pixel_size(96)
                nome = Gtk.Label(label=rotulo, ellipsize=Pango.EllipsizeMode.END, max_width_chars=12)
                dentro.append(img)
                dentro.append(nome)
                b.set_child(dentro)
                b.connect("clicked", lambda _b, v=valor: self._icone_escolhido(v))
                if valor == r.get("icone"):
                    foco = b
                caixa_linha.append(b)
                linha.append(b)
            grade.append(caixa_linha)
            linhas.append(linha)
        caixa.append(grade)
        self.abrir_modal(caixa, linhas, foco=foco)

    def _icone_escolhido(self, valor):
        r = self.edicao["r"]
        if valor:
            r["icone"] = valor
        else:
            r.pop("icone", None)
        self.fechar_modal()
        self._atualizar_editor()
