# Locks Python

Os arquivos `api.in`, `operations.in` e `dev.in` declaram apenas dependências
diretas. Os respectivos `.lock` fixam a árvore transitiva inteira com hashes
para CPython 3.12 em Linux amd64 (glibc 2.28 ou superior). Os Dockerfiles
instalam com `pip --require-hashes` e usam bases fixadas por digest.

Para atualizar um lock, use `uv` e mantenha a plataforma explícita:

```bash
uv pip compile requirements/api.in \
  --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --generate-hashes --no-build -o requirements/api.lock
uv pip compile requirements/operations.in \
  --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --generate-hashes --no-build -o requirements/operations.lock
uv pip compile requirements/dev.in \
  --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --generate-hashes --no-build -o requirements/dev.lock
```

Revise o diff inteiro depois de atualizar. `pytest` e `uvicorn` pertencem apenas
ao lock de desenvolvimento. `httpx` não é dependência direta de produção nem
faz parte do lock da API; ele aparece no lock operacional porque é dependência
de runtime obrigatória do SDK Anthropic.
