// Google Apps Script: guarda as coletas do sensor numa pasta do Drive e deixa a página gerenciá-las.
// Passo a passo em LEIA-ME.md. Este arquivo roda na SUA conta do Google, não no ESP nem no PC.

const FOLDER_ID = 'COLE_AQUI_O_ID_DA_PASTA';       // trecho final da URL da pasta: drive.google.com/drive/folders/<ID>
const TOKEN = 'TROQUE_POR_UMA_SENHA_LONGA';        // a mesma senha vai no diálogo "Drive" da página
const MAX_LISTA = 200;                              // gravações mais recentes devolvidas na listagem

const ID_RE = /^[A-Za-z0-9._-]+$/;

function doGet() {                                  // só para conferir no navegador que a implantação está de pé
  return ContentService.createTextOutput('Coletor de vibração: OK');
}

function doPost(e) {
  let out;
  try {
    const req = JSON.parse(e.postData.contents);
    if (req.token !== TOKEN) throw new Error('senha (token) inválida');
    const folder = DriveApp.getFolderById(FOLDER_ID);
    switch (req.action) {
      case 'ping':   out = { ok: true, folder: folder.getName() }; break;
      case 'upload': out = upload_(folder, req); break;
      case 'list':   out = list_(folder); break;
      case 'get':    out = get_(folder, req); break;
      case 'delete': out = delete_(folder, req); break;
      default: throw new Error('ação desconhecida: ' + req.action);
    }
  } catch (err) {
    out = { ok: false, error: String(err && err.message || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function checkId_(id) {
  if (!ID_RE.test(String(id))) throw new Error('id inválido');
  return String(id);
}

function find_(folder, name) {
  const it = folder.getFilesByName(name);
  return it.hasNext() ? it.next() : null;
}

// .npy primeiro, .json por último: a presença do .json marca a gravação como completa.
function upload_(folder, req) {
  const id = checkId_(req.id);
  if (find_(folder, id + '.json')) return { ok: true, id: id, duplicada: true };   // reenvio: idempotente
  const old = find_(folder, id + '.npy');                                            // .npy órfão de um envio interrompido
  if (old) old.setTrashed(true);
  const bytes = Utilities.base64Decode(req.npy_b64);
  folder.createFile(Utilities.newBlob(bytes, 'application/octet-stream', id + '.npy'));
  folder.createFile(id + '.json', req.json_text, 'application/json');
  return { ok: true, id: id };
}

function list_(folder) {
  const cache = CacheService.getScriptCache();
  const files = [];
  const it = folder.getFiles();
  while (it.hasNext()) {
    const f = it.next();
    if (f.getName().slice(-5) === '.json') files.push({ f: f, t: f.getDateCreated().getTime() });
  }
  files.sort(function (a, b) { return b.t - a.t; });
  const items = [];
  files.slice(0, MAX_LISTA).forEach(function (x) {
    const key = 'm_' + x.f.getId();                 // o conteúdo de um .json de gravação nunca muda: cache
    let txt = cache.get(key);
    if (!txt) { txt = x.f.getBlob().getDataAsString(); cache.put(key, txt, 21600); }
    try { items.push(JSON.parse(txt)); } catch (err) { /* json de outra origem: ignora */ }
  });
  return { ok: true, items: items, total: files.length };
}

function get_(folder, req) {
  const id = checkId_(req.id);
  const ext = req.kind === 'json' ? '.json' : '.npy';
  const f = find_(folder, id + ext);
  if (!f) throw new Error('arquivo não encontrado: ' + id + ext);
  return { ok: true, b64: Utilities.base64Encode(f.getBlob().getBytes()) };
}

// Vai para a lixeira do Drive (recuperável por 30 dias), não é exclusão definitiva.
function delete_(folder, req) {
  const id = checkId_(req.id);
  let n = 0;
  ['.json', '.npy'].forEach(function (ext) {
    const it = folder.getFilesByName(id + ext);
    while (it.hasNext()) { it.next().setTrashed(true); n++; }
  });
  return { ok: true, removidos: n };
}
