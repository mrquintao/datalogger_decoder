# Datalogger Decoder

Aplicacao desktop para Windows que decodifica arquivos binarios `.bin` do datalogger STM32 e exporta os registros para CSV, XLSX ou ambos.

A logica de protocolo foi separada da interface grafica sem redesenhar o formato binario original: registros de 8 bytes, timestamp de 21 bits, identificacao de padding no ultimo slot dos blocos de 2048 bytes, packet IDs existentes, formulas e correcao de empacotamento do IMU foram preservados.

## Estrutura

```text
datalogger_decoder/
├── app.py                 # GUI Tkinter/ttk
├── cli.py                 # interface de terminal opcional
├── decoder.py             # protocolo e leitura binaria em streaming
├── converter.py           # CSV/XLSX e progresso
├── logging_config.py      # logging em arquivo
├── requirements.txt
├── build.bat
├── .gitignore
├── assets/
│   └── README.md
├── logs/
│   └── .gitkeep
└── tests/
    ├── test_decoder.py
    └── test_converter.py
```

## Requisitos

- Windows 10 ou Windows 11
- Python 3.11 ou superior
- Tkinter/ttk (normalmente incluidos no instalador oficial do Python para Windows)
- `openpyxl` para XLSX
- PyInstaller para gerar `.exe`

## Para desenvolvedor

### Criar ambiente virtual

Na pasta do projeto:

```bat
python -m venv .venv
```

### Ativar no Windows

```bat
.venv\Scripts\activate
```

### Instalar dependencias

```bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Executar a interface grafica

```bat
python app.py
```

### Executar a CLI

```bat
python cli.py data001.bin -f xlsx
```

CSV com delimitador `;`:

```bat
python cli.py data001.bin -f csv --delimiter ";"
```

CSV + XLSX em uma pasta/base especifica:

```bat
python cli.py data001.bin -f both -o C:\dados\resultado\data001_decoded --delimiter ";"
```

## Abrindo no PyCharm

1. Extraia o ZIP.
2. No PyCharm, escolha **Open** e selecione a pasta `datalogger_decoder`.
3. Abra **Settings > Project > Python Interpreter**.
4. Crie um novo ambiente virtual `.venv` ou selecione um ja existente com Python 3.11+.
5. Instale `requirements.txt` pelo PyCharm ou execute `pip install -r requirements.txt` no terminal integrado.
6. Abra `app.py` e execute-o.

A pasta `.venv` nao faz parte do ZIP e nao deve ser versionada.

## Fluxo da GUI

1. Selecione um arquivo `.bin`.
2. Escolha a pasta de destino. Por padrao, ao selecionar o `.bin`, a propria pasta do arquivo e sugerida.
3. Escolha `XLSX`, `CSV` ou `CSV + XLSX`.
4. Para CSV, selecione o delimitador. O padrao da GUI e `;`, adequado para muitos ambientes Excel/pt-BR.
5. Clique em **Converter**.
6. Acompanhe a barra, percentual e contagem de registros.
7. Ao concluir, use **Abrir pasta de destino** no Windows, se desejar.

Os arquivos recebem nomes como:

```text
data001.bin
data001_decoded.csv
data001_decoded.xlsx
```

## Processamento em background e thread safety

A conversao nao roda na thread principal do Tkinter. `app.py` cria uma `threading.Thread` dedicada para executar `convert_file()`.

A worker **nao altera widgets diretamente**. Ela publica eventos em uma `queue.Queue`. A thread principal consulta essa fila periodicamente com `root.after(...)` e somente ela atualiza `ttk.Progressbar`, labels e caixas de dialogo. Assim, a janela permanece responsiva durante arquivos grandes.

O motor de conversao chama o callback de progresso de forma limitada: por padrao a cada 10.000 registros, alem do inicio e do final. Como cada registro possui 8 bytes, o total e calculado pelo tamanho do arquivo dividido por 8.

## Streaming e uso de memoria

`decoder.iter_decoded_records()` abre o arquivo em modo `rb` e le apenas 8 bytes por vez. O arquivo inteiro nao e carregado na RAM.

CSV e gravado linha a linha. XLSX usa:

```python
Workbook(write_only=True)
```

Quando a planilha atinge o limite do Excel (`1.048.576` linhas, incluindo cabecalho), uma nova aba e criada automaticamente:

```text
records_001
records_002
records_003
```

## Validacoes e erros

Antes da conversao, o programa verifica:

- existencia do arquivo;
- arquivo vazio;
- tamanho multiplo de 8 bytes;
- formato de saida;
- delimitador CSV com exatamente um caractere;
- criacao das pastas de destino;
- disponibilidade do `openpyxl` quando XLSX e solicitado.

Falhas conhecidas sao mostradas ao usuario em `messagebox.showerror`. Detalhes tecnicos e stack traces ficam no log.

Se uma conversao falhar, o programa tenta remover arquivos de saida parciais. O `.bin` de entrada nunca e aberto para escrita e nunca e alterado.

## Logging

Em desenvolvimento, o log e criado preferencialmente em:

```text
logs\datalogger_decoder.log
```

Ao rodar como `.exe`, o programa tenta primeiro uma pasta `logs` ao lado do executavel. Se ela nao for gravavel, usa `%LOCALAPPDATA%\DataloggerDecoder\logs` e, como ultimo fallback, uma pasta no perfil do usuario.

O log registra inicio da aplicacao, selecao de arquivos/pastas, inicio e termino da conversao, quantidade de registros, tempo de processamento, saidas e excecoes.

## Testes

Os testes usam apenas `unittest` da biblioteca padrao.

Executar:

```bat
python -m unittest discover -s tests -v
```

Eles cobrem:

- `signed_16`;
- unwrap de timestamp;
- padding no ultimo slot do bloco de 2048 bytes;
- registro `VELOCITY_RPM_FUEL`;
- correcao existente do IMU para gyro negativo;
- arquivo vazio e tamanho invalido;
- caminhos automaticos de saida;
- conversao CSV em streaming e callback de progresso.

## Validacao de sintaxe

Para compilar todos os modulos Python:

```bat
python -m compileall .
```

## Gerando o EXE com PyInstaller

Com o ambiente virtual ativo e as dependencias instaladas:

```bat
python -m PyInstaller --clean --noconfirm --onefile --windowed --name DataloggerDecoder app.py
```

Ou execute:

```text
build.bat
```

O executavel sera criado em:

```text
dist\DataloggerDecoder.exe
```

O `openpyxl` possui suporte conhecido nos hooks do PyInstaller moderno, portanto nao foi necessario adicionar `hidden-import` manual neste projeto. Se futuramente forem adicionados plugins, assets ou bibliotecas carregadas dinamicamente, o comando de build pode precisar ser ajustado.

### Adicionando icone futuramente

Coloque um `.ico` em `assets` e acrescente ao comando do PyInstaller:

```bat
--icon assets\datalogger_decoder.ico
```

## Separacao de responsabilidades

- `decoder.py`: conhece somente o protocolo binario e a iteracao dos registros.
- `converter.py`: conhece os formatos de saida e o callback de progresso, mas nao conhece Tkinter.
- `app.py`: conhece Tkinter, threading e fila de eventos, mas reutiliza o motor de conversao.
- `cli.py`: reutiliza exatamente `converter.py`/`decoder.py`; nao duplica a decodificacao.
- `logging_config.py`: centraliza onde e como os logs sao gravados.
