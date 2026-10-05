"""Aplicação FastAPI da Lâmina. Rode com: uv run uvicorn lamina.main:app --host 127.0.0.1 --port 8765"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lamina import config, db, importer
from lamina.api import biblioteca, curadoria, estudo, ia, orquestra, questoes
from lamina.claude.runner import sanitizar_ambiente
from lamina.orquestra.maestro import maestro

log = logging.getLogger("lamina")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    removidas = sanitizar_ambiente()
    if removidas:
        log.info("variáveis de ambiente do Claude ignoradas: %s", ", ".join(sorted(removidas)))
    db.inicializar()
    with db.conectar() as conn:
        log.info("banco importado: %s", importer.importar(conn))
    if config.MAESTRO_ATIVO:
        maestro.iniciar()
    yield
    await maestro.parar()


app = FastAPI(title="Lâmina", lifespan=ciclo_de_vida)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

for modulo in (questoes, estudo, ia, curadoria, biblioteca, orquestra):
    app.include_router(modulo.router)

app.mount("/imagens", StaticFiles(directory=config.BANCO_DIR / "images"), name="imagens")


@app.get("/api/saude")
def saude():
    return {"ok": True, "dias_ate_prova": config.dias_ate_prova()}


if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def spa(caminho: str):
        raiz = config.FRONTEND_DIST.resolve()
        alvo = (raiz / caminho).resolve()
        if caminho and alvo.is_relative_to(raiz) and alvo.is_file():
            return FileResponse(alvo)
        return FileResponse(config.FRONTEND_DIST / "index.html")
