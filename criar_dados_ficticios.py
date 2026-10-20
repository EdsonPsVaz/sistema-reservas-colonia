"""
criar_dados_ficticios.py - Cria o banco associados.db com pessoas INVENTADAS.

Uso:  python criar_dados_ficticios.py
      python criar_dados_ficticios.py --recriar   (apaga o banco atual e cria de novo)

Os CPFs gerados são propositalmente inválidos (dígitos verificadores errados),
então não pertencem a ninguém de verdade. Todos os outros dados também são inventados.
"""
import os
import random
import sqlite3
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(PASTA, "associados.db")
QUANTIDADE = 60

NOMES = ["Ana", "Bruno", "Carla", "Daniel", "Elisa", "Fábio", "Gabriela", "Hugo", "Isabela", "João",
         "Karina", "Lucas", "Mariana", "Nelson", "Olívia", "Paulo", "Renata", "Sérgio", "Tatiana", "Vítor"]
SOBRENOMES = ["Almeida", "Barbosa", "Cardoso", "Dias", "Esteves", "Ferraz", "Gomes", "Henrique", "Lima",
              "Moreira", "Nogueira", "Oliveira", "Pereira", "Queiroz", "Ribeiro", "Santos", "Teixeira"]
RUAS = ["Rua das Flores", "Rua do Exemplo", "Avenida Modelo", "Rua Fictícia", "Travessa da Demonstração"]
BAIRROS = ["Centro", "Jardim Exemplo", "Vila Modelo", "Bairro Teste"]


def cpf_invalido(base9):
    """Calcula os dois dígitos verificadores e depois estraga o último, de propósito."""
    nums = [int(c) for c in base9]
    for tamanho in (9, 10):
        soma = sum(n * (tamanho + 1 - i) for i, n in enumerate(nums))
        d = (soma * 10 % 11) % 10
        nums.append(d)
    nums[-1] = (nums[-1] + 1) % 10
    return "".join(str(n) for n in nums)


def main():
    recriar = "--recriar" in sys.argv
    if os.path.exists(DB):
        if not recriar:
            print("O arquivo associados.db já existe. Para não perder dados, nada foi feito.")
            print("Se este banco for de teste mesmo, rode:  python criar_dados_ficticios.py --recriar")
            sys.exit(1)
        os.remove(DB)

    random.seed(2026)  # mesma sequência sempre: o resultado é previsível
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE associados (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cpf TEXT, rg TEXT, nascimento TEXT,
        telefone TEXT, celular TEXT, email TEXT, endereco TEXT, bairro TEXT, cep TEXT, uf TEXT)""")

    usados = set()
    exemplos = []
    for i in range(QUANTIDADE):
        nome = f"{random.choice(NOMES)} {random.choice(SOBRENOMES)} {random.choice(SOBRENOMES)}"
        if nome in usados:
            continue
        usados.add(nome)
        cpf = cpf_invalido(f"{random.randint(100000000, 999999999)}")
        rg = str(random.randint(10000000, 99999999))
        # deixa alguns sem data de nascimento, como acontece em bases antigas
        nasc = None if i % 7 == 0 else f"{random.randint(1950, 1995)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        con.execute(
            "INSERT INTO associados (nome,cpf,rg,nascimento,telefone,celular,email,endereco,bairro,cep,uf) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nome.upper(), cpf, rg, nasc, "", f"(00) 9 0000-{random.randint(1000, 9999)}",
             f"associado{i + 1}@exemplo.com", f"{random.choice(RUAS)}, {random.randint(1, 999)}",
             random.choice(BAIRROS), "00000-000", "PR"))
        if len(exemplos) < 3:
            exemplos.append((nome.upper(), cpf))
    con.commit()
    con.close()

    print(f"Pronto: {len(usados)} associados fictícios criados em associados.db")
    print("Para testar como associado comum, entre com um destes CPFs:")
    for nome, cpf in exemplos:
        print(f"  {cpf}  ({nome})")
    print("Para testar como administrador, use um CPF do arquivo masters.exemplo.json")


if __name__ == "__main__":
    main()
