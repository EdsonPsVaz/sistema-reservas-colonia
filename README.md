# Sistema de reservas para colônia de férias

Sistema web simples para organizar as fichas de reserva de uma colônia de férias: busca do associado responsável, escolha da semana, cadastro das pessoas da reserva e cálculo automático dos valores. Nasceu de um problema real de trabalho e substitui uma planilha desorganizada.

> **Versão de demonstração.** Todos os dados deste repositório (associados, CPFs, chave Pix, conta bancária, telefones) são **fictícios**. Os CPFs gerados são inválidos de propósito.

## O que o sistema faz

- Login por CPF, com dois perfis:
  - **Administrador:** busca qualquer associado, vê todas as fichas, edita valores e semanas, exporta tudo em CSV.
  - **Associado comum:** só preenche a ficha dele, sem ver dados de outras pessoas e sem alterar preços.
- Escolha da semana por mês, com número de diárias e percentual do valor (semanas de 100% ou de 50%).
- Cadastro das pessoas da reserva (nome, idade, tipo de reserva), com valor por diária e pernoite opcional (cobrado uma vez por pessoa).
- Pagamento em 1x ou 2x no Pix, com o valor de cada parcela calculado.
- Ficha pronta para imprimir, com as informações de pagamento.
- Aba de configuração (somente administradores) para mudar temporada, datas, tipos de reserva, valores e dados de pagamento.
- Backup diário automático do banco, mantendo os 30 mais recentes.

## Tecnologias

Python (somente biblioteca padrão, **sem instalar nada**), SQLite e uma página HTML com CSS e JavaScript puros.

## Como rodar

1. Instale o [Python 3.8 ou mais novo](https://www.python.org/downloads/).
2. Baixe os arquivos deste repositório e coloque todos na mesma pasta.
3. Crie o banco com associados fictícios:

   ```
   python criar_dados_ficticios.py
   ```

   O comando mostra alguns CPFs fictícios para você testar como associado comum.
4. Inicie o sistema:

   ```
   python servidor.py
   ```
5. Abra `http://localhost:5000` no navegador.

Para entrar como **administrador**, use um dos CPFs de `masters.exemplo.json`. Para entrar como **associado comum**, use um dos CPFs mostrados no passo 3.

Se quiser usar administradores próprios, copie `masters.exemplo.json` para `masters.json` e edite o arquivo. O `masters.json` não vai para o repositório.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `servidor.py` | Servidor e regras de negócio: login, cálculo de valores, banco de dados e backup |
| `index.html` | Telas do sistema (login, busca, ficha, configuração) |
| `criar_dados_ficticios.py` | Cria o banco de demonstração com associados inventados |
| `masters.exemplo.json` | Exemplo de administradores (CPFs e nomes fictícios) |
| `logo.png` | Logo genérico de demonstração |

## Limites desta versão

É um protótipo pensado para uso interno em rede local, em até duas máquinas. Antes de expor para a internet seria preciso, no mínimo: HTTPS, uma segunda forma de autenticação além do CPF e uma revisão de segurança e de LGPD.

## Autor

Edson Vaz, Curitiba. [GitHub](https://github.com/EdsonPsVaz) · [LinkedIn](https://www.linkedin.com/in/edson-vaz-b67425375)
