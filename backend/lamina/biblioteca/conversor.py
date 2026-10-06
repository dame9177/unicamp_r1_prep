"""Conversor local de documentos na GPU (Marker): PDF ou imagem → Markdown com títulos, tabelas e OCR.

Não gasta tokens. É opcional e fica isolado do app (instalação: scripts/instalar_conversor.sh, que roda
`uv tool install marker-pdf`). Sem ele, a biblioteca usa a extração simples do pypdfium2 e os agentes
transcrevem PDFs escaneados lendo as páginas como imagem.

A fila converte um documento por vez (memória da GPU):
- PDFs com texto: o Markdown do Marker substitui o texto extraído (tabelas e títulos preservados), se
  não perder conteúdo; o texto simples fica guardado em texto_simples.md;
- PDFs escaneados e imagens: OCR (força OCR), e o documento sai de "aguardando transcrição".
As marcas de página do Marker viram [[página N]], as mesmas usadas nas citações.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from lamina import config
from lamina.db import conectar, linha, linhas

log = logging.getLogger("lamina.conversor")

TEMPO_MAX = 3600
INTERVALO = 20
# Lotes para caber em GPUs de 8 GB (os padrões do Marker supõem 24 GB+): pico medido de ~6,4 GB numa
# RTX 5070 Laptop, ~2,6 s/página num PCDT de 107 páginas com tabelas.
LOTES = ["--layout_batch_size", "8", "--detection_batch_size", "8", "--recognition_batch_size", "24",
         "--table_rec_batch_size", "8", "--ocr_error_batch_size", "16", "--equation_batch_size", "8"]
_RE_SEPARADOR = re.compile(r"^\{(\d+)\}-{20,}[ \t]*$", re.MULTILINE)


class ErroConversao(RuntimeError):
    pass


def cli() -> str | None:
    caminho = os.environ.get("LAMINA_MARKER_CLI") or str(Path.home() / ".local" / "bin" / "marker_single")
    return caminho if Path(caminho).exists() else shutil.which("marker_single")


def disponivel() -> bool:
    return cli() is not None


def marcas_de_pagina(md: str) -> str:
    """Separadores do Marker ("{0}-----…", páginas a partir de 0) → [[página N]] (a partir de 1)."""
    if not _RE_SEPARADOR.search(md):
        return md
    return _RE_SEPARADOR.sub(lambda m: f"[[página {int(m.group(1)) + 1}]]", md).strip() + "\n"


def limpar_markdown(md: str) -> str:
    """Tira o alinhamento visual das tabelas (espaços e traços de enchimento, que quase dobram o texto) e
    troca o HTML que o Marker emite (<sup>, <sub>, <br>) por texto simples."""
    md = re.sub(r"<sup>(.*?)</sup>", r"^\1", md)
    md = re.sub(r"<sub>(.*?)</sub>", r"_\1", md)
    md = re.sub(r"\s*<br\s*/?>\s*", " ", md)

    def linha(ln: str) -> str:
        if not ln.startswith("|"):
            return ln
        ln = re.sub(r" {2,}", " ", ln)
        return re.sub(r"-{4,}", "---", ln)
    return "\n".join(linha(ln) for ln in md.split("\n"))


async def converter(origem: Path, forcar_ocr: bool = False, tempo_max: int = TEMPO_MAX) -> str:
    executavel = cli()
    if not executavel:
        raise ErroConversao("conversor local não instalado")
    with tempfile.TemporaryDirectory(prefix="lamina-conv-") as tmp:
        cmd = [executavel, str(origem), "--output_dir", tmp, "--output_format", "markdown",
               "--paginate_output", "--disable_image_extraction", *LOTES]
        if forcar_ocr:
            cmd.append("--force_ocr")
        # PyTorch ≥ 2.14 compila alguns kernels com Triton em tempo de execução, o que exige um compilador C;
        # desligado, as operações usam as implementações nativas (mesmo resultado).
        env = {**os.environ, "TORCH_DISABLE_NATIVE_JIT": "1", "FOUNDATION_CHUNK_SIZE": "8192",
               "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT, env=env)
        try:
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=tempo_max)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ErroConversao(f"tempo esgotado ({tempo_max}s)") from None
        if proc.returncode != 0:
            raise ErroConversao(saida.decode("utf-8", errors="replace")[-1500:])
        arquivos = sorted(Path(tmp).rglob("*.md"))
        if not arquivos:
            raise ErroConversao("o conversor não gerou Markdown")
        return limpar_markdown(marcas_de_pagina(arquivos[0].read_text(encoding="utf-8")))


# ------------------------------------------------------------------------------------------------
# Fila de conversão
# ------------------------------------------------------------------------------------------------


def marcar_pendente(conn, doc_id: str) -> None:
    conn.execute("UPDATE biblioteca SET conversao = 'pendente', conversao_erro = NULL WHERE id = ?", (doc_id,))


def enfileirar_pdfs_sem_conversao(conn) -> int:
    """Documentos PDF/imagem guardados antes do conversor existir entram na fila (uma vez)."""
    cur = conn.execute("UPDATE biblioteca SET conversao = 'pendente' WHERE tipo = 'documento' "
                       "AND formato IN ('pdf', 'imagem') AND conversao IS NULL")
    return cur.rowcount


async def converter_documento(doc_id: str) -> str:
    """Converte um documento da biblioteca e atualiza texto, índice e status. Devolve o resultado."""
    from lamina.biblioteca import armazem

    with conectar() as conn:
        doc = armazem.obter(conn, doc_id)
        conn.execute("UPDATE biblioteca SET conversao = 'executando' WHERE id = ?", (doc_id,))
    pasta = config.BIBLIOTECA_DIR / "docs" / doc_id
    original = next(iter(sorted(pasta.glob("original.*"))), None)
    if not original:
        raise ErroConversao("arquivo original ausente")
    escaneado = doc["status_motivo"] == armazem.AGUARDANDO_TRANSCRICAO
    md = await converter(original, forcar_ocr=escaneado)
    texto_atual = (pasta / "texto.md").read_text(encoding="utf-8")
    util_novo = len(re.sub(r"\[\[página \d+\]\]|\s", "", md))
    util_atual = len(re.sub(r"\[\[página \d+\]\]|\s", "", texto_atual))
    if not escaneado and util_novo < 0.6 * util_atual:
        with conectar() as conn:
            conn.execute("UPDATE biblioteca SET conversao = 'descartada', conversao_erro = ? WHERE id = ?",
                         (f"Markdown com {util_novo} caracteres úteis contra {util_atual} do texto simples", doc_id))
        return "descartada (perderia conteúdo)"
    if util_novo < 30:
        raise ErroConversao("OCR não encontrou texto")
    if texto_atual.strip() and not (pasta / "texto_simples.md").exists():
        (pasta / "texto_simples.md").write_text(texto_atual, encoding="utf-8")
    (pasta / "texto.md").write_text(md, encoding="utf-8")
    with conectar() as conn:
        conn.execute("UPDATE biblioteca SET caracteres = ?, conversao = 'feita', conversao_erro = NULL WHERE id = ?",
                     (len(md), doc_id))
        if escaneado:
            conn.execute("UPDATE biblioteca SET status = 'vigente', status_motivo = NULL WHERE id = ?", (doc_id,))
        armazem.indexar(conn, doc_id, doc["titulo"], md)
        armazem.regenerar_catalogo(conn)
    return "feita"


class FilaConversao:
    def __init__(self, intervalo: int = INTERVALO):
        self.intervalo = intervalo
        self.atual: str | None = None
        self.ultimo_erro: str | None = None
        self._task: asyncio.Task | None = None

    def iniciar(self) -> None:
        if not disponivel():
            log.info("conversor local ausente: biblioteca usa a extração simples")
            return
        with conectar() as conn:
            conn.execute("UPDATE biblioteca SET conversao = 'pendente' WHERE conversao = 'executando'")
            n = enfileirar_pdfs_sem_conversao(conn)
        if n:
            log.info("%d documento(s) na fila do conversor local", n)
        self._task = asyncio.create_task(self._ciclo())

    async def parar(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _ciclo(self) -> None:
        while True:
            try:
                await self.processar_proximo()
            except Exception:  # noqa: BLE001 — a fila não pode morrer
                log.exception("falha na fila de conversão")
            await asyncio.sleep(self.intervalo)

    async def processar_proximo(self) -> str | None:
        with conectar() as conn:
            prox = linha(conn, "SELECT id FROM biblioteca WHERE conversao = 'pendente' ORDER BY atualizado_em LIMIT 1")
        if not prox:
            return None
        self.atual = prox["id"]
        try:
            resultado = await converter_documento(prox["id"])
            self.ultimo_erro = None
        except Exception as exc:  # noqa: BLE001
            resultado = "erro"
            self.ultimo_erro = f"{prox['id']}: {exc}"
            with conectar() as conn:
                conn.execute("UPDATE biblioteca SET conversao = 'erro', conversao_erro = ? WHERE id = ?",
                             (str(exc)[:1500], prox["id"]))
        finally:
            self.atual = None
        self._liberar_tarefas(prox["id"])
        return resultado

    @staticmethod
    def _liberar_tarefas(doc_id: str) -> None:
        """Tarefas do aluno que esperavam esta conversão rodam já (fora do orçamento de segundo plano)."""
        from lamina.orquestra.maestro import maestro

        with conectar() as conn:
            esperando = linhas(conn, "SELECT id FROM tarefas WHERE status = 'pendente' AND aguarda_doc = ? "
                                     "AND criado_por = 'aluno' ORDER BY id", (doc_id,))
        for t in esperando:
            if not maestro.disparar_tarefa(t["id"], fundo=False):
                break  # o maestro está ocupado; a tarefa segue na fila normal

    def estado(self) -> dict:
        with conectar() as conn:
            fila = linha(conn, "SELECT COUNT(*) AS n FROM biblioteca WHERE conversao = 'pendente'")["n"]
        return {"disponivel": disponivel(), "ativo": bool(self._task and not self._task.done()),
                "convertendo": self.atual, "na_fila": fila, "ultimo_erro": self.ultimo_erro}


fila = FilaConversao()
