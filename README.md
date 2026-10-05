# Datalogger Decoder

O módulo de aquisição de dados (MDA) do carro do Baja UFMG grava tudo o que os sensores leem em um cartão SD, em arquivos binários `dataNNN.bin`. Esses arquivos são compactos e rápidos de gravar, mas ninguém consegue abri-los direto no Excel ou no MATLAB.

O Datalogger Decoder resolve isso: você escolhe o `.bin`, clica em **Converter** e recebe uma planilha CSV ou XLSX pronta para plotar velocidade, RPM, combustível, acelerômetro e giroscópio.

## Como usar (sem instalar nada)

1. Baixe o `DataloggerDecoder.exe` e abra com dois cliques. Funciona em Windows 10 e 11.
2. Selecione o arquivo `.bin` tirado do cartão SD.
3. Escolha a pasta onde a planilha será salva. Por padrão é a mesma pasta do `.bin`.
4. Escolha o formato: `XLSX`, `CSV` ou os dois.
5. Se for CSV, escolha o separador. O padrão `;` é o que o Excel em português espera.
6. Clique em **Converter** e acompanhe a barra de progresso.

O arquivo original nunca é alterado. A planilha sai com o mesmo nome do `.bin` mais um sufixo:

```text
data001.bin
data001_decoded.csv
data001_decoded.xlsx
```

## O que vem na planilha

Cada linha da planilha é uma medida de um sensor em um instante:

| Coluna | O que é |
| --- | --- |
| `source_file` | arquivo `.bin` de origem |
| `byte_offset` | posição do registro dentro do `.bin` |
| `timestamp_raw_ms` | tempo gravado pelo carro, em milissegundos |
| `time_s` | tempo em segundos, já corrigido quando o contador do carro dá a volta |
| `record_type` | tipo do pacote gravado |
| `signal` | nome da grandeza medida |
| `value` | valor da medida |
| `unit` | unidade do valor |
| `source_axis` | eixo físico do sensor (só na IMU) |
| `raw_value` | valor exatamente como estava no binário |
| `flags` | `OK` ou um aviso sobre aquele registro |

Para plotar um sensor, filtre a coluna `signal` pelo nome dele e use `time_s` no eixo X e `value` no eixo Y.

### Sinais disponíveis

| `signal` | `unit` | Descrição | Taxa |
| --- | --- | --- | --- |
| `velocity` | `m/s` | velocidade do carro | 100 Hz |
| `rpm` | `rpm` | rotação do motor | 100 Hz |
| `fuel` | `raw_10bit` | nível de combustível que o carro gravou (1 = vazio, 7 = cheio) | 100 Hz |
| `fuel_adc_raw` | `adc_12bit` | leitura bruta do sensor de combustível, com o balanço do tanque | 100 Hz |
| `fuel_adc_filtered` | `adc_12bit` | a mesma leitura depois do filtro de Kalman | 100 Hz |
| `fuel_level_raw` | `level_1_7` | nível que a leitura bruta indicaria | 100 Hz |
| `fuel_level_filtered` | `level_1_7` | nível da leitura filtrada | 100 Hz |
| `AX`, `AY`, `AZ` | `LSB` | acelerômetro | 250 Hz |
| `GX`, `GY`, `GZ` | `LSB` | giroscópio | 250 Hz |

### Sobre os sinais de combustível

Com o carro em movimento o combustível balança dentro do tanque (sloshing) e a leitura do sensor oscila muito. O firmware `MDA_R26_KALMAN` passa essa leitura por um filtro de Kalman antes de decidir o nível mostrado ao piloto, e grava no SD tanto a leitura bruta quanto a filtrada.

Plotando `fuel_adc_raw` contra `fuel_adc_filtered` você vê o efeito do filtro. Plotando `fuel_level_raw` contra `fuel_level_filtered` você vê o nível pulando sem o filtro e descendo em degraus com ele. No ADC, valor menor significa tanque mais cheio.

Os níveis `fuel_level_*` são calculados aqui no decoder, com os mesmos limites que o firmware usa em `Read_COMB()`:

| Nível | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ADC menor que | 390 | 1010 | 1630 | 2280 | 2900 | 3500 | (acima) |

Se esses limites mudarem no firmware, atualize `FUEL_LEVEL_ADC_THRESHOLDS` em `decoder.py`. O sinal `fuel` é o que o carro realmente gravou e serve de referência. Arquivos gravados por firmwares anteriores, que não têm a leitura do ADC, continuam sendo convertidos normalmente.

### Avisos na coluna `flags`

| Aviso | Significado |
| --- | --- |
| `OK` | nada de especial |
| `TIMESTAMP_WRAP` | o contador de tempo do carro deu a volta neste registro; `time_s` já está corrigido |
| `PACKING_CORRECTED` | o valor do acelerômetro foi corrigido de um efeito conhecido do empacotamento no firmware |
| `PADDING` | espaço vazio no fim de um bloco do SD, sem medida |
| `INVALID_PACKET` | pacote que o decoder não reconhece |

## Versão estendida para debug

Marcando **Opção avançada: versão estendida para debug dos pacotes**, a planilha traz uma linha por pacote com todos os campos internos: bytes em hexadecimal, cabeçalho, payload, posição no bloco do SD e cada valor decodificado. Ela é útil para investigar o firmware, não para plotar.

Essa versão recebe o sufixo `_decoded_debug`, então nunca sobrescreve a planilha normal.

## Para quem vai mexer no código

Você precisa de Python 3.11 ou superior no Windows. Na pasta do projeto:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Abrir a interface gráfica:

```bat
python app.py
```

Converter pelo terminal:

```bat
python cli.py data001.bin -f csv --delimiter ";"
python cli.py data001.bin -f both -o C:\dados\resultado\data001_decoded
python cli.py data001.bin -f xlsx --extended-debug
```

Rodar os testes:

```bat
python -m unittest discover -s tests -v
```

Gerar o executável, que sai em `dist\DataloggerDecoder.exe`:

```bat
build.bat
```

### Como o código está organizado

| Arquivo | Papel |
| --- | --- |
| `decoder.py` | entende o formato binário e lê o arquivo registro por registro |
| `converter.py` | monta as linhas da planilha e grava CSV e XLSX |
| `app.py` | interface gráfica (Tkinter) |
| `cli.py` | interface de terminal, usando o mesmo motor da interface gráfica |
| `logging_config.py` | define onde os logs são gravados |
| `tests/` | testes automáticos do decoder e do conversor |

### O formato binário

Cada registro tem 8 bytes, em little-endian:

| Bits | Campo |
| --- | --- |
| 21 | tempo em milissegundos |
| 3 | controle |
| 8 | ID do pacote |
| 32 | dados |

| ID | Tipo | Conteúdo dos 32 bits de dados |
| --- | --- | --- |
| `0x00` | `SESSION_MARKER` | marca o início de uma gravação |
| `0x01` | `VELOCITY_RPM_FUEL` | velocidade (10 bits), RPM (12 bits), nível de combustível (10 bits) |
| `0x02` | `FUEL_ADC` | ADC bruto (16 bits), ADC filtrado (16 bits) |
| `0x10` | `IMU_AX_GX` | acelerômetro X (16 bits), giroscópio X (16 bits) |
| `0x14` | `IMU_AY_LOGICAL_GY` | acelerômetro Y lógico (16 bits), giroscópio Y (16 bits) |
| `0x18` | `IMU_AZ_LOGICAL_GZ` | acelerômetro Z lógico (16 bits), giroscópio Z (16 bits) |

O firmware troca os eixos Y e Z do acelerômetro ao gravar. A coluna `source_axis` mostra o eixo físico de cada medida.

### Detalhes de funcionamento

- **Arquivos grandes:** o `.bin` é lido 8 bytes por vez e a planilha é gravada linha a linha, então o programa não carrega o arquivo inteiro na memória. Quando o XLSX chega ao limite de 1.048.576 linhas do Excel, uma nova aba é criada (`records_001`, `records_002`, ...).
- **Janela sempre responsiva:** a conversão roda em uma thread separada e avisa o progresso por uma fila; só a thread principal mexe na tela.
- **Validações:** o programa recusa arquivo inexistente, vazio ou com tamanho que não seja múltiplo de 8 bytes. Se a conversão falhar no meio, a planilha incompleta é apagada.
- **Logs:** ficam em `logs\datalogger_decoder.log`. No `.exe`, o programa tenta a pasta `logs` ao lado do executável e, se não puder gravar ali, usa `%LOCALAPPDATA%\DataloggerDecoder\logs`.
