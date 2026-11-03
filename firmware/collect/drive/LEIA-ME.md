# Enviar as coletas para uma pasta do Google Drive

A página do sensor (HTTP, servida pelo ESP) não consegue usar o "Entrar com Google": o OAuth exige HTTPS.
Por isso o envio passa por um **Google Apps Script** que roda na sua conta e mexe na pasta que você escolher.
A página só conhece a URL do script e uma senha.

## Configurar (uma vez, ~5 min)

1. No Drive, crie (ou escolha) a pasta das coletas e copie o **ID** dela: é o final da URL,
   `drive.google.com/drive/folders/`**`<ID>`**.
2. Abra <https://script.google.com> → **Novo projeto**. Apague o conteúdo e cole o de [`Code.gs`](Code.gs).
3. No topo do arquivo, troque `FOLDER_ID` pelo ID da pasta e `TOKEN` por uma senha longa (só você sabe).
4. **Implantar → Nova implantação → tipo "Aplicativo da Web"**:
   - *Executar como*: **Eu**.
   - *Quem tem acesso*: **Qualquer pessoa** (a senha `TOKEN` é o que protege; sem ela o script recusa tudo).
5. Autorize quando o Google pedir (aviso "app não verificado" → *Avançado* → *Acessar*; é o seu próprio script).
6. Copie a **URL do aplicativo da Web** (termina em `/exec`).
7. Na página do sensor: o popup do **Drive** abre sozinho enquanto não houver senha (a URL já vem preenchida com a padrão,
   definida em `DRIVE_URL_PADRAO` no `data/app.js`). Digite a senha → **Testar conexão** (o resultado aparece dentro do
   popup, abaixo dos botões; deve mostrar o nome da pasta) → **Salvar**. O Drive só liga depois de salvar a senha.
   **Não usar o Drive** desativa e não pergunta mais; o botão **Drive** do cabeçalho reabre quando quiser.

O Drive é opcional: sem senha (ou com "Não usar"), as gravações ficam guardadas neste aparelho (IndexedDB, sobrevivem a recarregar a página) e você baixa o `.npy`/`.json` pelos botões da lista. **Nada é baixado automaticamente ao terminar.**

Se você mudar o `Code.gs` depois, use **Implantar → Gerenciar implantações → editar → Nova versão**; senão a URL continua
rodando a versão antiga.

## Como funciona

- Ao terminar cada gravação (se o Drive estiver ligado), a página envia `<id>.npy` + `<id>.json` (mesmo formato do coletor) para a pasta.
  Reenviar a mesma gravação não duplica.
- **Sem internet** (por exemplo, celular no Wi-Fi do sensor): a gravação fica na fila (guardada no aparelho, sobrevive a
  recarregar a página) e sobe sozinha quando houver conexão. O selo na lista mostra *na fila* / *enviando* / *no Drive*.
- A lista de gravações junta o que está nesta página com o que já está no Drive (inclusive de outro aparelho).
  **Ver** e **.npy** de uma gravação que só está no Drive baixam o arquivo na hora.
- **Excluir** manda os dois arquivos para a **lixeira do Drive** (recuperável).
- Depois de enviada, a gravação sai da memória do celular; ela volta a ser baixada do Drive quando você abre.

## Sem internet no Wi-Fi do sensor

Conectado ao `sensor-coleta`, o celular normalmente **não tem internet**, então o envio não acontece durante a coleta.
A página avisa ("Drive · sem internet · N na fila") e a gravação fica guardada. Atenção: o armazenamento do navegador é
**por endereço** (`192.168.4.1`, `sensor.local` e o IP do roteador são lugares diferentes), então a fila feita num endereço
só sobe quando você abrir a página **naquele mesmo endereço** com internet. Formas de ter internet e sensor juntos:

1. **Mesmo roteador** (botão **Rede** grava o Wi-Fi no ESP): celular e sensor na mesma rede, com internet. Recomendado.
2. **Hotspot do celular**: ligue o hotspot, coloque o SSID/senha dele no botão **Rede** e abra a página pelo IP que o ESP
   receber (aparece no diálogo **Rede** e na serial). O celular usa dados móveis para a internet. Não testado; costuma
   funcionar no Android, no iPhone depende do modelo.
3. Sem rede com internet: use só o salvamento local e baixe os arquivos pelos botões da lista.

## Limites e cuidados

- **Para ter internet e falar com o sensor ao mesmo tempo**, conecte celular e sensor no **mesmo roteador**
  (botão **Rede** da página grava o Wi-Fi no ESP). No Wi-Fi do próprio sensor (`sensor-coleta`) o celular costuma
  ficar sem internet; a fila resolve, mas o envio só acontece depois.
- A URL + senha ficam no `localStorage` do navegador daquele aparelho, em texto. Quem tiver os dois grava e apaga
  na pasta. Troque o `TOKEN` (e reimplante) se vazar.
- O Apps Script tem cota diária de execuções e de leitura/escrita do Drive; uso normal de coleta não chega perto.
  A listagem lê um `.json` por gravação (com cache de 6 h), então com centenas de gravações a primeira abertura demora;
  ela devolve só as 200 mais recentes.
- Gravações muito longas aumentam o envio: ~0,9 MB por 90 s (≈1,2 MB em base64).
