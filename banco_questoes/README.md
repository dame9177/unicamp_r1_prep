# Banco de questões – UNICAMP R1 Acesso Direto (processos 2022 → 2026)

Este diretório tem as provas de Acesso Direto da Residência Médica da Unicamp, com o gabarito oficial e as imagens, prontas para o app usar. Nada aqui é escrito pelo app: trate como dados somente leitura.

São **11 provas, 650 questões e 118 imagens**. A fonte é o site oficial da Comvest/FCM Unicamp. Cada questão guarda o link do PDF original e a página de onde saiu.

## Arquivos

| Caminho | Para quê |
|---|---|
| `data/questoes.jsonl` | **Fonte principal para o app.** Uma questão por linha, já com os dados da prova. |
| `data/index.json` | Lista das provas: ano, turno, formato, data, contagens e anuladas. |
| `data/<prova>.json` | Uma prova inteira. Inclui `valores_referencia`, a tabela de exames laboratoriais do caderno em Markdown. |
| `images/<prova>/qNN.png` | Imagens. O campo `imagens[].arquivo` traz o caminho **relativo a este diretório**. |
| `markdown/<prova>.md` | Cada prova em texto legível, com o gabarito escondido em `<details>`. Bom para leitura humana ou por LLM. |
| `schema.json` | JSON Schema de `data/<prova>.json`. As questões do `.jsonl` seguem `$defs.questao` e têm 4 campos a mais. |

As provas (`id` e `prova_id`):

| Prova | Processo | Turno | Formato | Questões |
|---|---|---|---|---|
| `unicamp-2026-ad-p1` | 2026 | manhã (16/11/2025) | resposta curta | 1–50 |
| `unicamp-2026-ad-p2` | 2026 | tarde (16/11/2025) | resposta curta | 51–100 |
| `unicamp-2026-ad-remanescentes` | 2026 | vagas remanescentes | resposta curta | 1–50 |
| `unicamp-2025-ad-p1` | 2025 | manhã (17/11/2024) | resposta curta | 1–50 |
| `unicamp-2025-ad-p2` | 2025 | tarde (17/11/2024) | resposta curta | 51–100 |
| `unicamp-2024-ad-p1` | 2024 | manhã (20/11/2023) | resposta curta | 1–60 |
| `unicamp-2024-ad-p2` | 2024 | tarde (20/11/2023) | resposta curta | 61–120 |
| `unicamp-2023-ad-p1` | 2023 | manhã (20/12/2022) | múltipla escolha a–d | 1–80 (anulada: 27) |
| `unicamp-2023-ad-p2` | 2023 | tarde (20/12/2022) | resposta curta | 1–60 |
| `unicamp-2022-ad-p1` | 2022 | manhã (20/12/2021) | múltipla escolha a–d | 1–80 (anuladas: 27, 63) |
| `unicamp-2022-ad-p2` | 2022 | tarde (20/12/2021) | resposta curta | 1–60 |

O "processo" é o ano em que a residência começa; a prova é aplicada no fim do ano anterior.

## Formato de uma linha de `questoes.jsonl`

```jsonc
{
  "prova_id": "unicamp-2024-ad-p2",
  "processo_seletivo": 2024,
  "turno": "Prova 2 (tarde)",
  "tipo": "regular",                          // ou "vagas_remanescentes"
  "id": "unicamp-2024-ad-p2-q102",            // único e estável: use como chave do progresso
  "numero": 102,
  "area": "Ginecologia e Obstetrícia",        // Clínica Médica | Cirurgia | Pediatria | Ginecologia e Obstetrícia | Saúde Coletiva
  "formato": "resposta_curta",                // ou "multipla_escolha"
  "enunciado_compartilhado": "Mulher, 32a…",  // OPCIONAL: caso clínico comum a 2–4 questões
  "enunciado": "Parturiente evoluiu … A CONDUTA INDICADA É:",
  "alternativas": null,                       // múltipla escolha: {"a": "…", "b": "…", "c": "…", "d": "…"}
  "imagens": [
    {"arquivo": "images/2024-ad-p2/q101.png", "rotulo": null, "legenda": "…", "pagina": 18}
  ],
  "gabarito": {
    "letra": null,                            // múltipla escolha: "A".."D"
    "resposta_esperada": "Fórcipe de Kielland ou fórcipe de rotação",
    "ampliado": false                         // true = gabarito ampliado após recursos
  },
  "anulada": false,
  "fonte": {"pdf": "https://www.comvest.unicamp.br/…/dAD2.pdf", "pagina": 18}
}
```

## O que o app precisa considerar

- **Dois formatos de questão.**
  - Em `multipla_escolha`, compare com `gabarito.letra` (maiúscula); as chaves de `alternativas` são minúsculas.
  - Em `resposta_curta` não existe uma resposta única: `resposta_esperada` é o texto oficial de correção, com os sinônimos aceitos, o que "não pontua" e as ampliações. Para corrigir automaticamente, compare a sua resposta com esse texto (um LLM faz isso bem) ou marque você mesmo certo ou errado.
- **Ordem de exibição:** mostre primeiro o `enunciado_compartilhado`, quando existir, e depois o `enunciado`. O caso clínico se repete em cada questão do grupo, então cada uma funciona sozinha. Para agrupar as questões que dividem o mesmo caso, compare o texto do `enunciado_compartilhado`.
- **Imagens:** sirva este diretório como estático e use `src` = `arquivo`. Uma mesma imagem pode aparecer em mais de uma questão (casos compartilhados). `legenda` traz a legenda do caderno ou o texto que estava escrito por cima da imagem.
- **Texto:** o texto é Markdown simples. Pode haver tabelas no formato pipe dentro do enunciado e quebras `\n`. Renderize com um parser de Markdown que suporte tabelas (GFM).
- **Anuladas:** existem nas provas de 2022 e 2023 (`anulada: true`). Elas mantêm a letra do gabarito original, mas o ideal é excluí-las das estatísticas.
- **Numeração:** as provas da tarde de 2024, 2025 e 2026 continuam a numeração da manhã (2024: 61–120; 2025 e 2026: 51–100). Para identificar uma questão, use sempre `id`, e não `numero`.
- **Área:** cada prova é dividida em 5 blocos iguais e sempre na mesma ordem: Clínica Médica, Cirurgia, Pediatria, GO e Saúde Coletiva.
- **Valores de referência:** a tabela de exames que vem no caderno está em `data/<prova>.json`, no campo `valores_referencia`, e não está no `.jsonl`. Vale mostrá-la como consulta durante a resolução.

## Exemplos de carregamento

```ts
// TypeScript (navegador ou Node com fetch)
const txt = await (await fetch("/banco_questoes/data/questoes.jsonl")).text();
const questoes = txt.trim().split("\n").map((l) => JSON.parse(l));
const pedNaoAnuladas = questoes.filter((q) => q.area === "Pediatria" && !q.anulada);
```

```python
import json
qs = [json.loads(l) for l in open("banco_questoes/data/questoes.jsonl", encoding="utf-8")]
```

## Origem e limitações

- Não incluído:
  - as provas de R+ e de outras especialidades com pré-requisito;
  - a prova de vagas remanescentes de 2025, cujo link oficial está fora do ar;
  - a prova do processo 2027, que ainda não foi aplicada.
- Na prova de vagas remanescentes de 2026 só foi publicada a prova 2.
- Dois erros de digitação do PDF oficial foram corrigidos: "VI DA" virou "VIDA" (2024-p2 Q116), e "COMO:4" virou "COMO:" (remanescentes Q48).
- Os scripts que geraram estes dados, e os PDFs originais, ficam em `../vanilla_tmp_workspace/unicamp-acesso-direto/` (fora deste repositório).
- O conteúdo das provas pertence à Unicamp (Comvest/FCM). Aqui ele foi apenas convertido de formato, para estudo pessoal.
