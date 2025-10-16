# ==== utilidades para teste/integracao ====

from fastapi import Query

@app.post("/seed")
def seed(
    nome: str = Query("Cliente Teste"),
    phone: str = Query("5535999999999"),
    dh: str = Query("15/10/2025 10:00"),
    ttl_horas: int = Query(24),
):
    """Cria um agendamento de teste e retorna os links prontos."""
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
    confirm_link = f"/confirm/{ag_id}?sig={sig}"
    return {
        "id": ag_id,
        "status": "aguardando",
        "confirm_page": confirm_link,
        "ok": f"/do/{ag_id}/ok?sig={sig}",
        "no": f"/do/{ag_id}/no?sig={sig}",
    }

@app.get("/status/{ag_id}")
def status(ag_id: int):
    con = db(); cur = con.cursor()
    row = cur.execute("SELECT id, cliente_nome, cliente_phone, data_hora, status FROM agenda WHERE id=?", (ag_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Agendamento não encontrado")
    keys = ["id","cliente_nome","cliente_phone","data_hora","status"]
    return dict(zip(keys, row))
