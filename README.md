# DATASUS SIH v2

Painel Streamlit para procedimentos hospitalares do SIH/SUS, com foco em cirurgias cardíacas e transplantes.

## O que mudou na v2

- Banco novo, criado automaticamente e não versionado no Git.
- Chave de deduplicação inclui UF, ano e mês da competência.
- Enriquecimento CNES consulta primeiro o código exato e valida o CNES retornado.
- Consulta por município é apenas fallback.
- Um nome válido no cache não é apagado antes de existir substituto válido.
- Pendências de CNES são registradas em `auditoria_qualidade`.
- Novo comando `diagnostico` para medir CNES, municípios, catálogo e competências problemáticas.
- Testes locais sem rede.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python cli.py importar-procedimentos
python -m pytest tests/ -q
```

## Primeira carga limpa

```bash
python cli.py atualizar-municipios
python cli.py coletar --ufs RS --meses 1
python cli.py corrigir-nomes
python cli.py diagnostico
python cli.py integridade
```

Depois da validação de uma amostra:

```bash
python cli.py coletar
python cli.py retentar-falhas
python cli.py atualizar-municipios
python cli.py corrigir-nomes
python cli.py diagnostico
streamlit run app.py
```

## Publicação no GitHub

O arquivo `data/sih.db` não é incluído no repositório. O workflow pode gerar e atualizar o banco conforme sua estratégia de publicação. Se optar por persistir o SQLite via GitHub Actions, revise conscientemente o `.gitignore` e o volume do repositório.

## Observação de qualidade

O painel usa competência de processamento da AIH. Nomes de estabelecimentos são enriquecidos pelo código CNES exato e não devem ser inferidos apenas pelo município.
