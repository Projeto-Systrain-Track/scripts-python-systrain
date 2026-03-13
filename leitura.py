import csv
import os
import json

nome_arquivo = 'registros.csv'

if not os.path.isfile(nome_arquivo):
    print("Arquivo registros.csv não encontrado.")
    exit()

dados = []
with open(nome_arquivo, mode='r') as arquivo:
    leitor = csv.DictReader(arquivo, delimiter=';')
    
    for linha in leitor:
        dados.append(linha)

print("\n REGISTROS ENCONTRADOS \n")

for registro in dados:
    print(
        f"CPU: {registro['USO_CPU']} | "
        f"RAM: {registro['MEMORIA_RAM(total, usado)']} | "
        f"DISCO: {registro['DISK(troughput)']}% | "
        f"DATAHORA: {registro['DATAHORA']}"
    )
print(f"\nTotal de registros: {len(dados)}")