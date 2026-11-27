"use strict";

async function openTranscriptPage(row) {
  const version = openReader("Apollo 11 · NASA", "Стенограмма, стр. " + row.page, "Открываем страницу…");
  try {
    const page = await api("/api/field-transcript/pages/" + row.page + (row.id ? "?line_id=" + row.id : ""));
    if (!$("reader").open || version !== readerVersion) return;
    const text = $("reader-text");
    text.replaceChildren();
    for (const [index, paragraph] of page.paragraphs.entries()) {
      const p = element("p", "transcript-paragraph");
      if (page.focus?.paragraph !== index) p.textContent = paragraph;
      else {
        const lines = paragraph.split(/\r?\n/);
        const start = page.focus.start_line, end = page.focus.end_line;
        const marked = element("mark", "", lines.slice(start, end).join("\n"));
        marked.dataset.lineId = String(page.focus.id);
        p.append(document.createTextNode(lines.slice(0, start).join("\n") + "\n"), marked);
        if (end < lines.length) p.append(document.createTextNode("\n" + lines.slice(end).join("\n")));
      }
      text.append(p);
    }
    const original = element("a", "field-source", page.local_scan ? "Открыть полный скан страницы" : "Оригинал стенограммы NASA");
    original.href = page.local_scan || (page.source + (row.text ? "#:~:text=" + encodeURIComponent(row.text.split(/\s+/).slice(0,9).join(" ")) : ""));
    original.target = "_blank";
    original.rel = "noopener noreferrer";
    text.prepend(original);
    if (page.preview) {
      const details = element("details","source-scan");
      const img = element("img");
      img.alt = "Скан листа 491 из журнала переговоров, катушка 84/2";
      img.loading = "lazy";
      img.src = page.preview;
      details.append(element("summary","","Посмотреть скан в монтажной"),img);
      text.prepend(details);
    }
    if (page.edition_note) text.prepend(element("p","",page.edition_note));
    const selected = text.querySelector("mark");
    if (selected) selected.scrollIntoView({block:"center"});
  } catch (err) {
    if ($("reader").open && version === readerVersion) openReader("Apollo 11 · NASA", "Не удалось открыть страницу", err.message);
  }
}

function renderTranscriptMatches(matches) {
  const list = element("div", "transcript-matches");
  for (const row of matches) {
    const article = element("article", "transcript-hit");
    const name = row.speaker + (row.role ? " · " + row.role : "");
    const time = row.get ? row.get + " от старта миссии" : "Требует сверки · " + row.printed_clock;
    article.append(element("p", "", row.text), element("small", "", name + " · " + time),
      button("cite", "Открыть стр. " + row.page, () => openTranscriptPage(row)));
    if (row.edition_note) article.append(element("p", "clock-note", row.edition_note));
    if (row.clock_neighbors) article.append(element("p", "clock-note",
      "В соседних строках стоят " + row.clock_neighbors.join(" и ") + ". Время этой строки требует сверки."));
    list.append(article);
  }
  return list;
}

let transcriptRequest = 0;
function clearTranscriptResults() {
  transcriptRequest++;
  $("transcript-results").replaceChildren();
}
$("transcript-words").addEventListener("input", clearTranscriptResults);
$("transcript-page").addEventListener("input", clearTranscriptResults);
$("transcript-form").addEventListener("submit", async event => {
  event.preventDefault();
  const query = $("transcript-words").value.trim();
  const scope = $("transcript-page").value ? $("transcript-page").valueAsNumber : null;
  const request = ++transcriptRequest;
  const output = $("transcript-results");
  const page = query.match(/^(?:стр\.?\s*)?(\d{1,4})$/i);
  if (page || (!query && scope !== null)) {
    output.replaceChildren();
    await openTranscriptPage({page:page ? Number(page[1]) : scope});
    return;
  }
  if (!query) {
    output.textContent = "Введите английскую фразу или номер страницы.";
    return;
  }
  output.textContent = "Ищем в стенограмме…";
  try {
    const result = await api("/api/field-transcript", {query,page:scope,exact:scope!==null});
    if (request !== transcriptRequest) return;
    output.replaceChildren();
    if (result.mode === "mission_time" || result.mode === "invalid_mission_time") {
      output.append(element("p", "", result.detail));
      if (result.matches.length) output.append(renderTranscriptMatches(result.matches));
    } else if (result.matches.length) output.append(renderTranscriptMatches(result.matches));
    else output.textContent = result.mode === "no_terms" ? "Введите отличительные слова на английском." :
      scope!==null ? "На странице " + scope + " такой фразы среди размеченных реплик нет." : "Среди размеченных реплик совпадений нет.";
  } catch (err) {
    if (request === transcriptRequest) output.textContent = err.message;
  }
});
