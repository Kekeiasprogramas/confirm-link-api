import hmac, hashlib, sqlite3, time, os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

SECRET = (os.getenv("CONFIRM_SECRET") or "troque-esta-chave-super-secreta").encode()
DBPATH = os.getenv("DBPATH", "app/bluepink/app.db")

app = FastAPI()

def db():
    os.makedirs(os.path.dirname(DBPATH), exist_ok=True)
    con = sqlite3.connect(DBPATH, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS agenda(
        id INTEGER PRIMARY KEY,
        cliente_nome TEXT,
        cliente_phone TEXT,
        data_hora TEXT,
        status TEXT DEFAULT 'aguardando',
        sig_salt TEXT,
        expires_at INTEGER
    )""")
    # Garante colunas (se já existir tabela antiga)
    for coldef in [
        ("status","TEXT","'aguardando'"),
        ("sig_salt","TEXT","NULL"),
        ("expires_at","INTEGER","NULL"),
    ]:
        try: con.execute(f"ALTER TABLE agenda ADD COLUMN {coldef[0]} {coldef[1]} DEFAULT {coldef[2]}")
        except Exception: pass
    return con

def sign(ag_id: int, salt: str) -> str:
    msg = f\"{ag_id}:{salt}\".encode()
    return hmac.new(SECRET, msg, hashlib.sha256).hexdigest()[:16]

HTML = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Confirmação</title>
<style>body{font-family:sans-serif;max-width:520px;margin:40px auto;padding:0 16px}
a.btn{display:block;padding:14px 16px;margin:12px 0;text-align:center;text-decoration:none;border-radius:10px}
.btn-ok{background:#16a34a;color:#fff}.btn-no{background:#ef4444;color:#fff}.box{background:#f1f5f9;border-radius:12px;padding:14px}
small{color:#64748b}</style></head><body>
<h2>Confirmar agendamento</h2>
<div class="box"><p>Olá {nome}, confirme sua consulta em {dh}.</p></div>
<a class="btn btn-ok" href="/do/{ag_id}/ok?sig={sig}">✅ Confirmar</a>
<a class="btn btn-no" href="/do/{ag_id}/no?sig={sig}">❌ Não confirmar</a>
<p><small>Você pode fechar esta página após escolher.</small></p>
</body></html>"""

@app.get("/confirm/{ag_id}", response_class=HTMLResponse)
def show(ag_id: int, sig: str):
    con = db(); cur = con.cursor()
    row = cur.execute("SELECT cliente_nome, data_hora, IFNULL(sig_salt,''), IFNULL(expires_at,0) FROM agenda WHERE id=?", (ag_id,)).fetchone()
    if not row: raise HTTPException(404, "Agendamento não encontrado")
    nome, dh, salt, exp = row
    if exp and time.time() > exp: raise HTTPException(400, "Link expirado")
    if sig != sign(ag_id, salt): raise HTTPException(403, "Assinatura inválida")
    return HTML.format(nome=nome, dh=dh, ag_id=ag_id, sig=sig)

@app.get("/do/{ag_id}/{action}")
def decide(ag_id: int, action: str, sig: str):
    if action not in ("ok","no"): raise HTTPException(400, "Ação inválida")
    con = db(); cur = con.cursor()
    row = cur.execute("SELECT IFNULL(sig_salt,''), IFNULL(expires_at,0) FROM agenda WHERE id=?", (ag_id,)).fetchone()
    if not row: raise HTTPException(404, "Agendamento não encontrado")
    salt, exp = row
    if exp and time.time() > exp: raise HTTPException(400, "Link expirado")
    if sig != sign(ag_id, salt): raise HTTPException(403, "Assinatura inválida")
    novo = "confirmado" if action=="ok" else "nao_confirmado"
    cur.execute("UPDATE agenda SET status=? WHERE id=?", (novo, ag_id))
    con.commit()
    return HTMLResponse("<h2>Pronto! Obrigado. Pode fechar esta página.</h2>")
