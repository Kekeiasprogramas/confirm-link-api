# confirm_api.py — SQLite + Webhook callback
import os, time, hmac, hashlib, json, sqlite3, requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

# ── Config ────────────────────────────────────────────────────────────────────
SECRET = (os.getenv("CONFIRM_SECRET") or "troque-esta-chave-super-secreta").encode()

# Banco local do seu app (ajuste se o caminho for diferente)
DBPATH = os.getenv("DBPATH", "app/bluepink/app.db")

# Webhook (se preencher, o clique CONFIRMAR/NAO vai chamar essa URL)
CALLBACK_URL = os.getenv("CALLBACK_URL")  # ex.: https://seu-tunel.trycloudflare.com/callback/confirm
CALLBACK_SECRET = (os.getenv("CALLBACK_SECRET") or "troque-esta-chave").encode()

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI()

def db():
    """Abre o SQLite e garante a tabela/colunas necessárias."""
    os.makedirs(os.path.dirname(DBPATH), exist_ok=True)
    con = sqlite3.connect(DBPATH, check_same_thread=False)
    con.execute("""
        CREATE TABLE IF NOT EXISTS agenda(
            id INTEGER PRIMARY KEY,
            cliente_nome TEXT,
            cliente_phone TEXT,
            data_hora TEXT,
            status TEXT DEFAULT 'aguardando',
            sig_salt TEXT,
            expires_at INTEGER
        )
    """)
    # garante colunas se a tabela já existia
    for col, typ, default in [
        ("status", "TEXT", "'aguardando'"),
        ("sig_salt", "TEXT", "NULL"),
        ("expires_at", "INTEGER", "NULL"),
    ]:
        try:
            con.execute(f"ALTER TABLE agenda ADD COLUMN {col} {typ} DEFAULT {default}")
        except Exception:
            pass
    return con

def sign(ag_id: int, salt: str) -> str:
    msg = f"{ag_id}:{salt}".encode()
    return hmac.new(SECRET, msg, hashlib.sha256).hexdigest()[:16]

HTML = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Confirmação</title>
<style>
body{{font-family:sans-serif;max-width:520px;margin:40px auto;padding:0 16px}}
a.btn{{display:block;padding:14px 16px;margin:12px 0;text-align:center;text-decoration:none;border-radius:10px}}
.btn-ok{{background:#16a34a;color:#fff}}
.btn-no{{background:#ef4444;color:#fff}}
.box{{background:#f1f5f9;border-radius:12px;padding:14px}}
small{{color:#64748b}}
</style></head><body>
<h2>Confirmar agendamento</h2>
<div class="box"><p>Olá {nome}, confirme sua consulta em {dh}.</p></div>
<a class="btn btn-ok" href="/do/{ag_id}/ok?sig={sig}">✅ Confirmar</a>
<a class="btn btn-no" href="/do/{ag_id}/no?sig={sig}">❌ Não confirmar</a>
<p><small>Você pode fechar esta página após escolher.</small></p>
</body></html>
"""

# ── Rotas ─────────────────────────────────────────────────────────────────────
@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"

@app.get("/confirm/{ag_id}", response_class=HTMLResponse)
def show(ag_id: int, sig: str):
    con = db(); cur = con.cursor()
    row = cur.execute(
        "SELECT cliente_nome, data_hora, IFNULL(sig_salt,''), IFNULL(expires_at,0) "
        "FROM agenda WHERE id=?", (ag_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Agendamento não encontrado")
    nome, dh, salt, exp = row
    if exp and time.time() > exp:
        raise HTTPException(400, "Link expirado")
    if sig != sign(ag_id, salt):
        raise HTTPException(403, "Assinatura inválida")
    return HTML.format(nome=nome, dh=dh, ag_id=ag_id, sig=sig)

@app.get("/do/{ag_id}/{action}", response_class=HTMLResponse)
def decide(ag_id: int, action: str, sig: str):
    if action not in ("ok", "no"):
        raise HTTPException(400, "Ação inválida")

    con = db(); cur = con.cursor()
    row = cur.execute(
        "SELECT IFNULL(sig_salt,''), IFNULL(expires_at,0) FROM agenda WHERE id=?", (ag_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Agendamento não encontrado")
    salt, exp = row
    if exp and time.time() > exp:
        raise HTTPException(400, "Link expirado")
    if sig != sign(ag_id, salt):
        raise HTTPException(403, "Assinatura inválida")

    novo = "confirmado" if action == "ok" else "nao_confirmado"
    cur.execute("UPDATE agenda SET status=? WHERE id=?", (novo, ag_id))
    con.commit()

    # ── Notifica seu sistema (webhook) ──
    if CALLBACK_URL:
        payload = {"id": ag_id, "status": novo, "ts": int(time.time())}
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        sig2 = hmac.new(CALLBACK_SECRET, raw, hashlib.sha256).hexdigest()
        try:
            requests.post(CALLBACK_URL, json={**payload, "sig": sig2}, timeout=8)
        except Exception:
            # não quebra a confirmação se o callback falhar
            pass

    return HTMLResponse("<h2>Pronto! Obrigado. Pode fechar esta página.</h2>")

# ── Utilidades (seed/status) ──────────────────────────────────────────────────
@app.post("/seed")
@app.get("/seed")
def seed(
    nome: str = Query("Cliente Teste"),
    phone: str = Query("5535999999999"),
    dh: str = Query("15/10/2025 10:00"),
    ttl_horas: int = Query(24),
):
    """Cria 1 agendamento e devolve links prontos."""
    import secrets
    con = db(); cur = con.cursor()
    cur.execute(
        "INSERT INTO agenda(cliente_nome, cliente_phone, data_hora, status) VALUES (?,?,?,?)",
        (nome, phone, dh, "aguardando"),
    )
    ag_id = cur.lastrowid
    salt = secrets.token_hex(4)
    exp = int(time.time() + ttl_horas * 3600)
    cur.execute("UPDATE agenda SET sig_salt=?, expires_at=? WHERE id=?", (salt, exp, ag_id))
    con.commit()

    sig = sign(ag_id, salt)
    confirm_page = f"/confirm/{ag_id}?sig={sig}"
    return {
        "id": ag_id,
        "status": "aguardando",
        "confirm_page": confirm_page,
        "ok": f"/do/{ag_id}/ok?sig={sig}",
        "no": f"/do/{ag_id}/no?sig={sig}",
    }

@app.get("/status/{ag_id}")
def status(ag_id: int):
    con = db(); cur = con.cursor()
    row = cur.execute(
        "SELECT id, cliente_nome, cliente_phone, data_hora, status FROM agenda WHERE id=?", (ag_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Agendamento não encontrado")
    keys = ["id", "cliente_nome", "cliente_phone", "data_hora", "status"]
    return dict(zip(keys, row))
