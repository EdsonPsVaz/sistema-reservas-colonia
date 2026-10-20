"""
servidor.py - Sistema da Colônia de Férias
Uso:  python servidor.py
Versão de demonstração (dados fictícios).
Antes da primeira vez:  python criar_dados_ficticios.py
Precisa estar na mesma pasta de: associados.db, index.html, logo.png e masters.json (ou masters.exemplo.json)
Não precisa instalar nada.
"""
import csv
import io
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PASTA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(PASTA, "associados.db")
PORTA = 5000
SESSAO_MAX = 2 * 3600  # sessão expira após 2h sem uso

CONFIG_INICIAL = {
    "temporada": "2026/2027",
    "entidade": "Colônia de Férias (demonstração)",
    "pix": "pix@exemplo.com",
    "banco": "Banco Exemplo",
    "agencia": "0000-0",
    "conta": "00000-0",
    "whatsapp": "(00) 0 0000-0000",
    "regras_pagamento": "Todos os pagamentos devem ser feitos exclusivamente pela chave Pix acima.\nTodo comprovante deve ser encaminhado pelo nosso WhatsApp.\nOs pagamentos devem ser quitados antes da estadia (obrigatório).",
}
MES_DE = {"Dez": "DEZEMBRO", "Jan": "JANEIRO", "Fev": "FEVEREIRO", "Mar": "MARÇO"}
# nome, valor/diária (semanas de 100%), pernoite (valor único por pessoa), categoria do pernoite
TIPOS_INICIAIS = [
    ("Associado", 155, 30, "Associado e Dependente"), ("Dependente", 155, 30, "Associado e Dependente"),
    ("Parente", 185, 40, "Parente"), ("Convidado", 220, 45, "Convidado"),
    ("Filho do Associado", 115, 30, "Associado e Dependente"), ("Filho de Parente", 145, 40, "Parente"),
    ("Filho de Convidado", 185, 45, "Convidado"),
]
# nome, inicio, fim, diárias, % do valor, observação
SEMANAS_INICIAIS = [
    ("Dez/26 · 1ª semana", "2026-12-01", "2026-12-06", 6, 50, ""),
    ("Dez/26 · 2ª semana", "2026-12-08", "2026-12-13", 6, 50, ""),
    ("Dez/26 · 3ª semana", "2026-12-15", "2026-12-20", 6, 100, ""),
    ("Dez/26 · 4ª semana", "2026-12-22", "2026-12-27", 6, 100, "NATAL"),
    ("Jan/27 · 1ª semana", "2026-12-29", "2027-01-03", 6, 100, "ANO NOVO"),
    ("Jan/27 · 2ª semana", "2027-01-05", "2027-01-10", 6, 100, ""),
    ("Jan/27 · 3ª semana", "2027-01-12", "2027-01-17", 6, 100, ""),
    ("Jan/27 · 4ª semana", "2027-01-19", "2027-01-24", 6, 100, ""),
    ("Jan/27 · 5ª semana", "2027-01-26", "2027-01-31", 6, 100, ""),
    ("Fev/27 · 1ª semana", "2027-02-02", "2027-02-09", 8, 100, "CARNAVAL"),
    ("Fev/27 · 2ª semana", "2027-02-11", "2027-02-14", 4, 100, "PÓS CARNAVAL - EXCURSÕES"),
    ("Fev/27 · 3ª semana", "2027-02-16", "2027-02-21", 6, 50, ""),
    ("Fev/27 · 4ª semana", "2027-02-23", "2027-02-28", 6, 50, ""),
]

MASTERS = {}   # cpf -> nome (lido de masters.json)
SESSOES = {}   # token -> {role, nome, assoc_id, t}
FALHAS = {}    # ip -> [horários de tentativas de login erradas]


class NaoLogado(Exception):
    pass


class Negado(Exception):
    pass


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def j(rows):
    return [dict(r) for r in rows]


def tem(con, tab, col):
    return col in [r[1] for r in con.execute("PRAGMA table_info(" + tab + ")")]


def carregar_masters():
    arq = os.path.join(PASTA, "masters.json")
    if not os.path.exists(arq):  # na demonstração usa o arquivo de exemplo
        arq = os.path.join(PASTA, "masters.exemplo.json")
    if not os.path.exists(arq):
        return False
    with open(arq, encoding="utf-8-sig") as f:
        for m in json.load(f):
            MASTERS[re.sub(r"\D", "", m["cpf"]).zfill(11)] = m["nome"]
    return bool(MASTERS)


def iniciar():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
    CREATE TABLE IF NOT EXISTS semanas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ordem INTEGER, nome TEXT, inicio TEXT,
        fim TEXT, diarias INTEGER, percentual REAL, obs TEXT, mes TEXT);
    CREATE TABLE IF NOT EXISTS tipos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ordem INTEGER, nome TEXT, valor REAL,
        pernoite REAL DEFAULT 0, pernoite_nome TEXT);
    CREATE TABLE IF NOT EXISTS fichas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, associado_id INTEGER, assoc_nome TEXT,
        assoc_rg TEXT, semana_nome TEXT, inicio TEXT, fim TEXT, diarias INTEGER,
        percentual REAL, obs_semana TEXT, ajuste REAL DEFAULT 0, ajuste_motivo TEXT,
        observacao TEXT, total REAL, parcelas INTEGER DEFAULT 1, criado_por TEXT, criado_em TEXT);
    CREATE TABLE IF NOT EXISTS pessoas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ficha_id INTEGER, ordem INTEGER,
        nome TEXT, idade TEXT, parentesco TEXT, categoria TEXT,
        valor_diaria REAL, manual INTEGER, total REAL,
        pernoite INTEGER DEFAULT 0, valor_pernoite REAL DEFAULT 0);
    """)
    # --- atualiza bancos criados por versões anteriores ---
    if not tem(con, "semanas", "mes"):
        con.execute("ALTER TABLE semanas ADD COLUMN mes TEXT")
        for pref, mes in MES_DE.items():
            con.execute("UPDATE semanas SET mes=? WHERE nome LIKE ?", (mes, pref + "%"))
    if not tem(con, "tipos", "pernoite"):
        con.execute("ALTER TABLE tipos ADD COLUMN pernoite REAL DEFAULT 0")
        con.execute("ALTER TABLE tipos ADD COLUMN pernoite_nome TEXT")
        for nome, _, pn, pnn in TIPOS_INICIAIS:
            con.execute("UPDATE tipos SET pernoite=?, pernoite_nome=? WHERE nome=?", (pn, pnn, nome))
    for tab, col, tipo in (("fichas", "parcelas", "INTEGER DEFAULT 1"), ("fichas", "criado_por", "TEXT"),
                           ("pessoas", "pernoite", "INTEGER DEFAULT 0"),
                           ("pessoas", "valor_pernoite", "REAL DEFAULT 0")):
        if not tem(con, tab, col):
            con.execute("ALTER TABLE " + tab + " ADD COLUMN " + col + " " + tipo)
    # --- dados iniciais ---
    for k, v in CONFIG_INICIAL.items():
        con.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (k, v))
    con.execute("DELETE FROM config WHERE chave='senha_hash'")  # senha antiga não é mais usada
    if con.execute("SELECT 1 FROM config WHERE chave='migr_regras1'").fetchone() is None:
        r = con.execute("SELECT valor FROM config WHERE chave='regras_pagamento'").fetchone()
        if r:
            novo = "\n".join(l for l in r["valor"].split("\n") if "2x no Pix" not in l)
            con.execute("UPDATE config SET valor=? WHERE chave='regras_pagamento'", (novo,))
        con.execute("INSERT INTO config VALUES ('migr_regras1','1')")
    if con.execute("SELECT COUNT(*) FROM semanas").fetchone()[0] == 0:
        for i, s in enumerate(SEMANAS_INICIAIS):
            con.execute("INSERT INTO semanas (ordem,nome,inicio,fim,diarias,percentual,obs,mes) "
                        "VALUES (?,?,?,?,?,?,?,?)", (i,) + s + (MES_DE.get(s[0][:3], ""),))
    if con.execute("SELECT COUNT(*) FROM tipos").fetchone()[0] == 0:
        for i, t in enumerate(TIPOS_INICIAIS):
            con.execute("INSERT INTO tipos (ordem,nome,valor,pernoite,pernoite_nome) VALUES (?,?,?,?,?)", (i,) + t)
    con.commit()
    con.close()


def backup_diario():
    """Copia o banco para backups/associados_AAAA-MM-DD.db (guarda os 30 últimos)."""
    try:
        pasta = os.path.join(PASTA, "backups")
        os.makedirs(pasta, exist_ok=True)
        destino = os.path.join(pasta, "associados_" + datetime.now().strftime("%Y-%m-%d") + ".db")
        src, dst = db(), sqlite3.connect(destino)
        src.backup(dst)
        dst.close()
        src.close()
        for f in sorted(x for x in os.listdir(pasta) if x.endswith(".db"))[:-30]:
            os.remove(os.path.join(pasta, f))
    except Exception as e:
        print("Aviso: não consegui fazer o backup:", e)


# ---------------- autenticação ----------------
def sessao(headers):
    t = headers.get("X-Token")
    s = SESSOES.get(t)
    if not s:
        return None
    if time.time() - s["t"] > SESSAO_MAX:
        SESSOES.pop(t, None)
        return None
    s["t"] = time.time()
    return s


def exige(s, master=False):
    if not s:
        raise NaoLogado("Sua sessão expirou. Entre novamente com o CPF.")
    if master and s["role"] != "master":
        raise Negado("Acesso restrito aos administradores.")


def login(b, ip):
    agora = time.time()
    f = [x for x in FALHAS.get(ip, []) if agora - x < 600]
    if len(f) >= 8:
        raise Negado("Muitas tentativas incorretas. Aguarde alguns minutos.")
    digitos = re.sub(r"\D", "", str(b.get("cpf", "")))
    cpf = digitos.zfill(11)
    sess = None
    if digitos and cpf in MASTERS:
        sess = {"role": "master", "nome": MASTERS[cpf], "assoc_id": None}
    elif digitos:
        con = db()
        rows = con.execute("SELECT id,nome FROM associados WHERE cpf=?", (cpf,)).fetchall()
        con.close()
        if len(rows) > 1:
            raise ValueError("Este CPF possui cadastro duplicado. Procure a secretaria.")
        if rows:
            sess = {"role": "comum", "nome": rows[0]["nome"], "assoc_id": rows[0]["id"]}
    if not sess:
        FALHAS[ip] = f + [agora]
        time.sleep(0.5)
        raise ValueError("CPF não encontrado. Verifique se digitou corretamente.")
    FALHAS.pop(ip, None)
    token = secrets.token_hex(24)
    SESSOES[token] = {**sess, "t": time.time()}
    return {"token": token, "role": sess["role"], "nome": sess["nome"], "assoc_id": sess["assoc_id"]}


# ---------------- consultas ----------------
def idade_de(iso):
    try:
        n = date.fromisoformat(iso)
    except Exception:
        return ""
    h = date.today()
    return h.year - n.year - ((h.month, h.day) < (n.month, n.day))


def buscar(q):
    q = q.strip()
    d = re.sub(r"\D", "", q)
    con = db()
    if d and not re.search(r"[A-Za-zÀ-ÿ]", q):
        rows = con.execute("SELECT * FROM associados WHERE rg=? OR cpf=? OR cpf=? LIMIT 20",
                           (d, d, d.zfill(11))).fetchall()
    elif len(q) >= 3:
        rows = con.execute("SELECT * FROM associados WHERE nome LIKE ? ORDER BY nome LIMIT 30",
                           ("%" + q.upper() + "%",)).fetchall()
    else:
        rows = []
    con.close()
    return j(rows)


def associado(i, master):
    con = db()
    a = con.execute("SELECT * FROM associados WHERE id=?", (i,)).fetchone()
    if not a:
        raise ValueError("Associado não encontrado")
    f = con.execute("SELECT id,semana_nome,total FROM fichas WHERE associado_id=? ORDER BY id DESC", (i,)).fetchall()
    con.close()
    a = dict(a)
    idade = idade_de(a.get("nascimento") or "")
    if not master:  # associado comum só vê o mínimo sobre si mesmo
        a = {"id": a["id"], "nome": a["nome"], "cpf": "***.***.***-" + (a["cpf"] or "")[-2:]}
    a["idade"] = idade
    return {"associado": a, "fichas": j(f)}


def get_config():
    con = db()
    c = {r["chave"]: r["valor"] for r in con.execute("SELECT * FROM config") if r["chave"] in CONFIG_INICIAL}
    s = j(con.execute("SELECT * FROM semanas ORDER BY ordem,id"))
    t = j(con.execute("SELECT * FROM tipos ORDER BY ordem,id"))
    con.close()
    return {"config": c, "semanas": s, "tipos": t}


def set_config(b):
    con = db()
    for k, v in b["config"].items():
        if k in CONFIG_INICIAL:
            con.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (k, str(v)))
    con.execute("DELETE FROM semanas")
    for i, s in enumerate(b["semanas"]):
        if s["nome"].strip():
            con.execute("INSERT INTO semanas (ordem,nome,inicio,fim,diarias,percentual,obs,mes) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (i, s["nome"], s["inicio"], s["fim"], int(s["diarias"] or 0),
                         float(s["percentual"] or 100), s.get("obs", ""), s.get("mes", "")))
    con.execute("DELETE FROM tipos")
    for i, t in enumerate(b.get("tipos", [])):
        if t["nome"].strip():
            con.execute("INSERT INTO tipos (ordem,nome,valor,pernoite,pernoite_nome) VALUES (?,?,?,?,?)",
                        (i, t["nome"].strip(), float(t["valor"] or 0), float(t.get("pernoite") or 0),
                         t.get("pernoite_nome", "")))
    con.commit()
    con.close()
    return {"ok": True}


def salvar_ficha(b, s):
    exige(s)
    master = s["role"] == "master"
    con = db()
    if master:
        aid = b["associado_id"]
    else:
        if b.get("id"):
            raise Negado("Uma ficha já salva só pode ser alterada pela secretaria.")
        aid = s["assoc_id"]
    a = con.execute("SELECT nome,rg FROM associados WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ValueError("Associado não encontrado")
    sem = b["semana"]
    if not master:  # associado comum: semana e preços vêm sempre do banco
        r = con.execute("SELECT * FROM semanas WHERE nome=? AND inicio=?", (sem["nome"], sem["inicio"])).fetchone()
        if not r:
            raise ValueError("Semana inválida.")
        sem = dict(r)
    d, pct = int(sem["diarias"]), float(sem["percentual"])
    tipos = {t["nome"]: t for t in con.execute("SELECT * FROM tipos")}
    if not b.get("pessoas"):
        raise ValueError("Adicione pelo menos uma pessoa.")
    soma, linhas = 0.0, []
    for i, p in enumerate(b["pessoas"]):
        pern = bool(p.get("pernoite"))
        if master:
            v = float(p["valor_diaria"])
            vp = float(p.get("valor_pernoite") or 0) if pern else 0.0
            manual = 1 if p.get("manual") else 0
        else:
            t = tipos.get(p["tipo"])
            if not t:
                raise ValueError("Tipo de reserva inválido.")
            v = round(t["valor"] * pct / 100, 2)
            vp = float(t["pernoite"] or 0) if pern else 0.0
            manual = 0
        tot = round(v * d + vp, 2)  # pernoite entra uma única vez por pessoa
        soma += tot
        linhas.append((i, p["nome"].strip(), str(p.get("idade", "")), "", p["tipo"], v, manual, tot,
                       1 if pern else 0, vp))
    total = round(soma, 2)
    parcelas = 2 if b.get("parcelas") == 2 else 1
    campos = (aid, a["nome"], a["rg"], sem["nome"], sem["inicio"], sem["fim"], d, pct, sem.get("obs", ""),
              b.get("observacao", ""), total, parcelas)
    if b.get("id"):
        fid = b["id"]
        con.execute("UPDATE fichas SET associado_id=?,assoc_nome=?,assoc_rg=?,semana_nome=?,inicio=?,fim=?,"
                    "diarias=?,percentual=?,obs_semana=?,observacao=?,total=?,parcelas=? WHERE id=?",
                    campos + (fid,))
        con.execute("DELETE FROM pessoas WHERE ficha_id=?", (fid,))
    else:
        cur = con.execute("INSERT INTO fichas (associado_id,assoc_nome,assoc_rg,semana_nome,inicio,fim,diarias,"
                          "percentual,obs_semana,observacao,total,parcelas,criado_por,criado_em) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          campos + (s["nome"] if master else "Associado",
                                    datetime.now().isoformat(timespec="seconds")))
        fid = cur.lastrowid
    con.executemany("INSERT INTO pessoas (ficha_id,ordem,nome,idade,parentesco,categoria,valor_diaria,manual,"
                    "total,pernoite,valor_pernoite) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(fid,) + l for l in linhas])
    con.commit()
    con.close()
    backup_diario()
    return {"id": fid, "total": total}


def get_ficha(i, s):
    exige(s)
    con = db()
    f = con.execute("SELECT * FROM fichas WHERE id=?", (i,)).fetchone()
    if not f:
        raise ValueError("Ficha não encontrada")
    if s["role"] != "master" and f["associado_id"] != s["assoc_id"]:
        raise Negado("Acesso negado.")
    p = con.execute("SELECT nome,idade,categoria AS tipo,valor_diaria,manual,pernoite,valor_pernoite "
                    "FROM pessoas WHERE ficha_id=? ORDER BY ordem", (i,)).fetchall()
    con.close()
    f = dict(f)
    return {"id": f["id"], "associado_id": f["associado_id"],
            "semana": {"nome": f["semana_nome"], "inicio": f["inicio"], "fim": f["fim"],
                       "diarias": f["diarias"], "percentual": f["percentual"], "obs": f["obs_semana"]},
            "parcelas": f["parcelas"] or 1, "observacao": f["observacao"],
            "pessoas": [{**dict(x), "manual": bool(x["manual"]), "pernoite": bool(x["pernoite"])} for x in p]}


def lista_fichas():
    con = db()
    r = con.execute("SELECT f.id, f.assoc_nome AS nome, f.semana_nome, f.total, f.criado_em, f.criado_por, "
                    "(SELECT COUNT(*) FROM pessoas p WHERE p.ficha_id=f.id) AS pessoas "
                    "FROM fichas f ORDER BY f.id DESC LIMIT 3000").fetchall()
    con.close()
    return j(r)


def excluir(b):
    con = db()
    con.execute("DELETE FROM pessoas WHERE ficha_id=?", (b["id"],))
    con.execute("DELETE FROM fichas WHERE id=?", (b["id"],))
    con.commit()
    con.close()
    backup_diario()
    return {"ok": True}


def exportar():
    con = db()
    rows = con.execute("SELECT f.id, f.criado_em, f.criado_por, f.assoc_nome, f.assoc_rg, a.cpf, f.semana_nome, "
                       "f.inicio, f.fim, f.diarias, f.parcelas, f.total AS total_ficha, p.nome, p.idade, "
                       "p.categoria, p.pernoite, p.valor_diaria, p.valor_pernoite, p.total AS total_pessoa "
                       "FROM fichas f JOIN pessoas p ON p.ficha_id=f.id "
                       "LEFT JOIN associados a ON a.id=f.associado_id ORDER BY f.id, p.ordem").fetchall()
    con.close()
    m = lambda x: ("%.2f" % (x or 0)).replace(".", ",")
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Ficha", "Criada em", "Criada por", "Responsável", "RG", "CPF", "Semana", "Início", "Fim",
                "Diárias", "Parcelas", "Total da ficha", "Pessoa", "Idade", "Tipo de reserva", "Pernoite",
                "Valor/diária", "Valor do pernoite", "Total da pessoa"])
    for r in rows:
        w.writerow([r["id"], r["criado_em"], r["criado_por"], r["assoc_nome"], r["assoc_rg"], r["cpf"],
                    r["semana_nome"], r["inicio"], r["fim"], r["diarias"], r["parcelas"] or 1,
                    m(r["total_ficha"]), r["nome"], r["idade"], r["categoria"], "Sim" if r["pernoite"] else "Não",
                    m(r["valor_diaria"]), m(r["valor_pernoite"]), m(r["total_pessoa"])])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


# ---------------- rotas ----------------
def r_config(s, q):
    exige(s)
    return get_config()


def r_buscar(s, q):
    exige(s, True)
    return buscar(q.get("q", ""))


def r_associado(s, q):
    exige(s)
    i = int(q.get("id", 0))
    if s["role"] != "master" and i != s["assoc_id"]:
        raise Negado("Acesso negado.")
    return associado(i, s["role"] == "master")


def r_ficha(s, q):
    return get_ficha(int(q.get("id", 0)), s)


def r_fichas(s, q):
    exige(s, True)
    return lista_fichas()


GET_ROTAS = {"/api/config": r_config, "/api/buscar": r_buscar, "/api/associado": r_associado,
             "/api/ficha": r_ficha, "/api/fichas": r_fichas}


class H(BaseHTTPRequestHandler):
    def _enviar(self, codigo, corpo, tipo="application/json; charset=utf-8", extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _rodar(self, fn):
        try:
            self._enviar(200, json.dumps(fn(), ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            codigo = 401 if isinstance(e, NaoLogado) else 403 if isinstance(e, Negado) else \
                400 if isinstance(e, ValueError) else 500
            self._enviar(codigo, json.dumps({"erro": str(e)}, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        s = sessao(self.headers)
        if u.path == "/":
            with open(os.path.join(PASTA, "index.html"), "rb") as f:
                return self._enviar(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/logo.png":
            with open(os.path.join(PASTA, "logo.png"), "rb") as f:
                return self._enviar(200, f.read(), "image/png")
        if u.path == "/api/exportar":
            try:
                exige(s, True)
                return self._enviar(200, exportar(), "text/csv; charset=utf-8",
                                    {"Content-Disposition": "attachment; filename=fichas.csv"})
            except Exception as e:
                return self._rodar(lambda: (_ for _ in ()).throw(e))
        if u.path in GET_ROTAS:
            return self._rodar(lambda: GET_ROTAS[u.path](s, q))
        self._enviar(404, b"nao encontrado", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(n) or b"{}")
        s = sessao(self.headers)
        if self.path == "/api/login":
            return self._rodar(lambda: login(b, self.client_address[0]))
        if self.path == "/api/logout":
            SESSOES.pop(self.headers.get("X-Token"), None)
            return self._enviar(200, b"{}")
        if self.path == "/api/ficha":
            return self._rodar(lambda: salvar_ficha(b, s))
        if self.path == "/api/ficha/excluir":
            return self._rodar(lambda: (exige(s, True), excluir(b))[1])
        if self.path == "/api/config":
            return self._rodar(lambda: (exige(s, True), set_config(b))[1])
        self._enviar(404, b"{}")

    def log_message(self, *a):
        pass


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    if not carregar_masters():
        print("Não achei o arquivo masters.json (com os administradores). Coloque-o nesta pasta.")
        sys.exit(1)
    try:
        c = db()
        c.execute("SELECT COUNT(*) FROM associados")
        c.close()
    except sqlite3.Error:
        print("Não achei os associados. Rode antes: python criar_dados_ficticios.py")
        sys.exit(1)
    iniciar()
    backup_diario()
    print("Sistema rodando.")
    print(f"  Neste computador:    http://localhost:{PORTA}")
    print(f"  No outro computador: http://{ip_local()}:{PORTA}")
    print("Deixe esta janela aberta. Para parar: Ctrl+C")
    ThreadingHTTPServer(("0.0.0.0", PORTA), H).serve_forever()
