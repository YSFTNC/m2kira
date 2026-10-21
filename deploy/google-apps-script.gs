// m2kira — GitHub taramasını 30 dakikada bir başlatır (PC kapalıyken de).
// GitHub'ın kendi zamanlayıcısı çalıştırmaları sık düşürüyor; bu betik Google'ın sunucularında çalışır.
//
// Kurulum (bir kez, ~3 dakika):
//  1. https://script.google.com -> "Yeni proje". İçindeki kodu silip bu dosyanın tamamını yapıştır.
//  2. Aşağıdaki TOKEN satırına GitHub anahtarını yapıştır (yalnız YSFTNC/m2kira, izin: Actions Read and write).
//  3. Üstteki işlev listesinden "kur" seç -> Çalıştır. Google izin ister: hesabını seç ->
//     "Gelişmiş" -> "m2kira'ya git (güvenli değil)" -> İzin ver. (Betik senin; uyarı yayınlanmamış betikler için.)
//  4. Alttaki "Yürütme günlüğü"nde "Tamam: 30 dakikada bir tetiklenecek" görünmeli.
// Durdurmak için: "durdur" işlevini çalıştır.

const TOKEN = "BURAYA_GITHUB_ANAHTARI";
const REPO = "YSFTNC/m2kira";
const WORKFLOW = "scan.yml";

function tetikle() {
  const r = UrlFetchApp.fetch("https://api.github.com/repos/" + REPO + "/actions/workflows/" + WORKFLOW + "/dispatches", {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: "Bearer " + TOKEN,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    payload: JSON.stringify({ ref: "main" }),
    muteHttpExceptions: true,
  });
  if (r.getResponseCode() !== 204) {
    throw new Error("GitHub " + r.getResponseCode() + ": " + r.getContentText().slice(0, 300));
  }
}

function kur() {
  if (TOKEN.indexOf("BURAYA") === 0) throw new Error("Önce TOKEN satırına GitHub anahtarını yapıştır.");
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger("tetikle").timeBased().everyMinutes(30).create();
  tetikle();
  Logger.log("Tamam: 30 dakikada bir tetiklenecek. İlk tarama şimdi başladı.");
}

function durdur() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  Logger.log("Durduruldu.");
}
