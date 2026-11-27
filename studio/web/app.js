"use strict";
const $ = id => document.getElementById(id);
const audio = $("audio");
const stamp = seconds => {
  const n = Math.max(0, Math.floor(seconds || 0));
  return String(Math.floor(n / 60)).padStart(2, "0") + ":" + String(n % 60).padStart(2, "0");
};

function element(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(cls, label, action) {
  const node = element("button", cls, label);
  node.type = "button";
  if (cls === "cite" || cls === "doc") {
    // WebKit может открыть документ по нажатию, оставив фокус на предыдущем поле.
    node.addEventListener("click", () => node.focus({preventScroll: true}));
  }
  node.addEventListener("click", action);
  return node;
}
async function api(path, data) {
  const opts = data === undefined ? {} : {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(data)
  };
  const response = await fetch(path, opts);
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Запрос не прошел. Попробуйте еще раз.");
  return value;
}
let records = [],
  active = null,
  status = {
    model: "",
    online: false
  };
const desks = new Map();

function desk() {
  return desks.get(active.id);
}

let readerVersion = 0;
function openReader(kind, title, text) {
  $("reader-kind").textContent = kind;
  $("reader-title").textContent = title;
  $("reader-text").textContent = text;
  if (!$("reader").open) $("reader").showModal();
  return ++readerVersion;
}

function read(id, record = active) {
  const doc = record.documents.find(item => item.id === id);
  if (doc) openReader(record.code + " / " + id + " · " + doc.kind, doc.title, doc.text);
}
$("close").onclick = () => $("reader").close();
$("reader").onclick = event => {
  if (event.target === $("reader")) $("reader").close();
};
// On desktop Chrome, Tab at the last control can move into the browser toolbar.
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey) return;
    const controls = Array.from(dialog.querySelectorAll("button, a[href], input, select, textarea, audio[controls], summary, [tabindex='0']"))
      .filter(node => !node.matches(":disabled") && node.checkVisibility());
    const first = controls[0], last = controls.at(-1);
    const edge = event.shiftKey ? first : last;
    if (edge && edge === document.activeElement) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  });
}
$("info").onclick = () => openReader("Учебный фоноархив", "О монтажной",
  "Три звуковые реконструкции и бумажные свидетельства созданы для лабораторной. Нажмите на метку, чтобы услышать фрагмент, или на карточку, чтобы прочитать источник.\n\nВ режиме «Диалог» локальная модель через Ollama ищет основания в документах. Позицию на копии и реплики по точной метке можно проверить и при отключенной модели. В записанном разборе хранятся ответы и вызовы инструментов настоящего прогона.");

function draw() {
  if (!active) return;
  const canvas = $("wave"),
    width = canvas.clientWidth,
    height = canvas.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, width, height);
  const top = 16,
    bottom = height - 25,
    mid = (top + bottom) / 2,
    pad = 5,
    plot = width - 2 * pad;
  const x = second => pad + second / active.duration * plot;
  g.font = "11px monospace";
  for (let s = 0; s <= active.duration; s += 1) {
    const xx = x(s);
    g.strokeStyle = s % 5 === 0 ? "#41584d" : "#2c4137";
    g.beginPath();
    g.moveTo(xx, s % 5 === 0 ? top : bottom - 3);
    g.lineTo(xx, bottom);
    g.stroke();
    if (s % 5 === 0 && (width > 410 || s % 10 === 0) && xx < width - 24) {
      g.fillStyle = "#bad0c0";
      g.fillText(stamp(s), xx, height - 6);
    }
  }
  g.strokeStyle = "#476657";
  g.beginPath();
  g.moveTo(pad, mid);
  g.lineTo(width - pad, mid);
  g.stroke();
  g.fillStyle = "#aadab8";
  g.beginPath();
  for (let i = 0; i < active.peaks.length; i++) {
    const xx = pad + i / (active.peaks.length - 1) * plot,
      h = Math.pow(active.peaks[i], .62) * (bottom - top) * .63;
    if (!i) g.moveTo(xx, mid - h);
    else g.lineTo(xx, mid - h);
  }
  for (let i = active.peaks.length - 1; i >= 0; i--) {
    const xx = pad + i / (active.peaks.length - 1) * plot,
      h = Math.pow(active.peaks[i], .62) * (bottom - top) * .63;
    g.lineTo(xx, mid + h);
  }
  g.closePath();
  g.fill();
  for (const marker of active.markers) {
    const xx = x(marker.second);
    g.fillStyle = "#d69c78";
    g.beginPath();
    g.moveTo(xx - 4, top - 7);
    g.lineTo(xx + 4, top - 7);
    g.lineTo(xx, top - 2);
    g.fill();
  }
  const pointer = x(audio.currentTime || 0);
  g.fillStyle = "#ffb180";
  g.fillRect(pointer - 1, top - 4, 2, bottom - top + 5);
}
new ResizeObserver(draw).observe($("scrub"));

function refreshTime() {
  if (!active) return;
  const now = audio.currentTime || 0;
  $("now").textContent = stamp(now);
  $("sound-start").textContent = "Найти с " + stamp(now);
  $("scrub").setAttribute("aria-valuenow", now.toFixed(1));
  $("scrub").setAttribute("aria-valuetext", stamp(now) + " из " + stamp(active.duration));
  for (const node of $("markers").children) node.classList.toggle("active", Math.abs(now - Number(node.dataset.second)) < 1.4);
  draw();
}

function seek(second) {
  if (!active || !Number.isFinite(second)) return;
  const target = Math.min(Math.max(0, second), active.duration);
  if (audio.readyState >= 1) {
    audio.currentTime = target;
    refreshTime();
  } else {
    const intended = active.id;
    audio.addEventListener("loadedmetadata", () => {
      if (active.id === intended) seek(target);
    }, {
      once: true
    });
  }
}
$("scrub").onclick = event => {
  const rect = $("scrub").getBoundingClientRect();
  seek((event.clientX - rect.left - 5) / (rect.width - 10) * active.duration);
};
$("scrub").onkeydown = event => {
  const times = {
    ArrowRight: audio.currentTime + 1,
    ArrowUp: audio.currentTime + 1,
    ArrowLeft: audio.currentTime - 1,
    ArrowDown: audio.currentTime - 1,
    PageUp: audio.currentTime + 5,
    PageDown: audio.currentTime - 5,
    Home: 0,
    End: active.duration
  };
  if (event.key in times) {
    event.preventDefault();
    seek(times[event.key]);
  }
};
$("play").onclick = async () => {
  try {
    if (!audio.paused) {
      audio.pause();
      return;
    }
    if (audio.ended) seek(0);
    await audio.play();
  } catch {
    openReader("Воспроизведение", "Фонограмма недоступна", "Обновите страницу и проверьте, открывается ли WAV-файл из папки data/tapes.");
  }
};
for (const name of ["timeupdate", "seeked", "loadedmetadata", "ended"]) audio.addEventListener(name, refreshTime);
for (const name of ["play", "pause", "ended"]) audio.addEventListener(name, () => {
  $("play").setAttribute("aria-label", audio.paused ? "Воспроизвести" : "Пауза");
  $("play").firstChild.textContent = audio.paused ? "▶" : "Ⅱ";
});

function showCase(id) {
  stopExcerpt();
  soundRequest++;
  $("sound-search").open = false;
  $("sound-results").replaceChildren();
  $("sound-start").disabled = false;
  $("sound-start").textContent = "Найти с 00:00";
  active = records.find(c => c.id === id) || records[0];
  if (!desks.has(active.id)) desks.set(active.id, {
    mode: status.online ? "live" : "sample",
    turns: [],
    session: null,
    draft: "",
    example: null,
    pending: false,
    error: ""
  });
  for (const node of $("catalog").children) node.setAttribute("aria-current", String(node.dataset.case === active.id));
  $("case-code").textContent = active.code;
  $("case-title").textContent = active.title;
  $("case-date").textContent = active.place + " · " + active.date;
  $("brief").textContent = active.brief;
  audio.pause();
  audio.src = active.audio;
  audio.load();
  $("duration").textContent = "/ " + stamp(active.duration);
  $("now").textContent = "00:00";
  $("scrub").setAttribute("aria-valuemax", active.duration);
  $("scrub").setAttribute("aria-valuenow", "0");
  $("scrub").setAttribute("aria-valuetext", "00:00 из " + stamp(active.duration));
  $("markers").replaceChildren(...active.markers.map(m => {
    const b = button("marker", "", () => seek(m.second));
    b.dataset.second = String(m.second);
    b.append(element("b", "", stamp(m.second)), element("span", "", m.label));
    return b;
  }));
  $("doc-count").textContent = active.documents.length + " источника";
  $("documents").replaceChildren(...active.documents.map(d => {
    const b = button("doc", "", () => read(d.id));
    const line = element("div", "doc-top");
    line.append(element("span", "doc-id", d.id), element("span", "", d.kind));
    b.append(line, element("strong", "", d.title));
    return b;
  }));
  $("question").value = desk().draft;
  renderDesk();
  draw();
  if (desk().mode === "sample" && !desk().example) openSample();
}
const tools = {
  search: "Поиск в документах",
  read: "Чтение источника",
  check_excerpt: "Проверка оговорки в документе",
  skill: "Методика архивиста",
  locate_marker: "MCP · время метки",
  compare_span: "MCP · длительность",
  tape_span: "MCP · интервал на ленте",
  compare_repeat_clocks: "MCP · сверка часов двух фрагментов",
  compare_public: "MCP · сверка записей NASA",
  field_catalog: "Каталог записей NASA",
  search_transcript: "MCP · поиск по стенограмме",
  read_transcript: "MCP · соседняя реплика",
  read_transcript_page: "MCP · печатная страница",
  transcript_terms: "Модель подобрала английские слова для поиска",
  movement_request: "Действие в запросе",
  movement_check: "Сверка направления действия",
  argos_terms: "Локальный перевод Argos",
  rank_transcript: "MCP · отбор близких реплик",
  select_transcript: "Модель проверила цитату по источнику",
  verify_transcript: "Сверка вопроса с выбранной репликой",
  clock_reference: "Точки отсчета WAV и времени миссии",
  match_sound: "MCP · поиск по звуку"
};

let soundRequest = 0;
let excerptPlayer = null;

function stopExcerpt() {
  if (!excerptPlayer) return;
  const {player, control, label, timer} = excerptPlayer;
  excerptPlayer = null;
  clearTimeout(timer);
  player.pause();
  control.textContent = label;
  control.setAttribute("aria-pressed", "false");
}
audio.addEventListener("play", stopExcerpt);

function listenButton(url, second, duration, label) {
  const control = button("listen", label, async () => {
    const alreadyPlaying = excerptPlayer?.control === control;
    stopExcerpt();
    if (alreadyPlaying) return;
    audio.pause();
    $("field-reference").pause();
    const end = second + duration;
    const player = new Audio(url + "#t=" + second + "," + end);
    const playback = {player, control, label, timer:null};
    excerptPlayer = playback;
    const finish = () => { if (excerptPlayer === playback) stopExcerpt(); };
    player.addEventListener("ended", finish, {once:true});
    player.addEventListener("error", finish, {once:true});
    player.addEventListener("playing", () => {
      if (excerptPlayer !== playback) return;
      clearTimeout(playback.timer);
      playback.timer = setTimeout(finish, 1000 * Math.max(0,end - Math.max(second,player.currentTime)));
    });
    player.addEventListener("waiting", () => clearTimeout(playback.timer));
    control.setAttribute("aria-pressed", "true");
    control.textContent = "Остановить · " + label;
    try { await player.play(); } catch { finish(); }
  });
  control.setAttribute("aria-pressed","false");
  return control;
}

function clipStamp(second) {
  const ticks = Math.round(second * 100);
  const fraction = ticks % 100;
  return stamp(Math.floor(ticks / 100)) + (fraction ? "," + String(fraction).padStart(2, "0") : "");
}

function repeatClocksResult(data) {
  const panel = element("section","measurement repeat-clocks");
  panel.append(element("b","",data.label));
  if (data.status !== "compared") {
    panel.append(element("p","",data.detail));
    return panel;
  }
  for (const [name,pos] of [["Найденный повтор",data.target],["Исходный образец",data.source]]) {
    const record = records.find(item => item.id === pos.case_id);
    const item = element("div","repeat-position");
    item.append(element("strong","",name + " · " + pos.code));
    item.append(element("span","",pos.clock.status === "verified" ? "В эфире " + pos.clock.value : pos.clock.value));
    if (record) {
      const refs = element("div","refs");
      refs.append(listenButton(record.audio,pos.second,data.window_seconds,"На копии " + clipStamp(pos.second)));
      for (const id of pos.clock.sources) refs.append(button("cite",id,() => read(id,record)));
      item.append(refs);
    }
    panel.append(item);
  }
  return panel;
}

function soundResult(measurement) {
  const box = element("div","measurement sound-result");
  box.append(element("b","",measurement.value), element("span","",measurement.detail));
  if (measurement.status === "invalid_window") return box;
  const reference = records.find(item => item.id === measurement.case_id);
  if (reference) box.append(listenButton(reference.audio, measurement.reference_second, measurement.window_seconds,
    "Образец · " + reference.code + " · " + clipStamp(measurement.reference_second)));
  for (const hit of measurement.matches) {
    const row = element("div","sound-hit");
    const record = records.find(item => item.id === hit.case_id);
    if (!record) continue;
    row.append(listenButton(record.audio, hit.second, measurement.window_seconds, hit.code + " · " + clipStamp(hit.second)));
    const score = element("small","","r = " + hit.score.toLocaleString("ru-RU",{minimumFractionDigits:3, maximumFractionDigits:4}));
    score.title = "Коэффициент сходства формы сигнала";
    row.append(score);
    const evidence = element("div","repeat-evidence");
    const compare = button("cite","Сверить эфирные часы",async () => {
      compare.disabled = true;
      evidence.textContent = "Проверяем метки обеих записей…";
      try {
        const result = await api("/api/repeat-clocks",{case_id:measurement.case_id,start_seconds:measurement.reference_second,
          scope:measurement.scope,candidate_case:hit.case_id,candidate_second:hit.second});
        evidence.replaceChildren(repeatClocksResult(result));
      } catch (err) { evidence.textContent = err.message; }
      finally { compare.disabled = false; }
    });
    row.append(compare);
    box.append(row,evidence);
  }
  return box;
}

const field = $("field-dialog");
const fieldSource = $("field-reference");
let fieldRequest = 0;
$("field-open").onclick = () => {
  audio.pause();
  stopExcerpt();
  field.showModal();
};
$("field-close").onclick = () => field.close();
field.onclick = event => { if (event.target === field) field.close(); };
field.addEventListener("close", () => {
  fieldRequest++;
  fieldSource.pause();
  stopExcerpt();
  $("field-run").disabled = false;
  $("field-result").replaceChildren();
});
fieldSource.addEventListener("play", stopExcerpt);
function clearFieldResult() {
  ++fieldRequest;
  $("field-result").replaceChildren();
  $("field-run").disabled = false;
  stopExcerpt();
}
$("field-candidate").addEventListener("change", () => {
  if ($("field-candidate").value === "calibration") $("field-speed").checked = true;
  clearFieldResult();
});
$("field-speed").addEventListener("change", clearFieldResult);
$("field-at").addEventListener("input", clearFieldResult);
function seekFieldSource() {
  const at = $("field-at").valueAsNumber;
  if (Number.isFinite(at) && at >= 0 && at <= fieldSource.duration) fieldSource.currentTime = at;
}
fieldSource.addEventListener("loadedmetadata",seekFieldSource);
$("field-at").addEventListener("change",seekFieldSource);
fieldSource.addEventListener("seeked", () => {
  if (Math.abs(fieldSource.currentTime-$("field-at").valueAsNumber) < .005) return;
  $("field-at").value = fieldSource.currentTime.toFixed(2);
  clearFieldResult();
});
function renderFieldResult(data, candidate, at) {
  const box = element("section","field-matches");
  if (data.status !== "compared") {
    box.textContent = data.detail || (data.status === "quiet" ? "В этом окне слишком мало звука. Сдвиньте начало образца." : "Вторая запись слишком коротка.");
    return box;
  }
  box.append(listenButton("/field-audio/eagle-short.wav", at, data.window_seconds, "Образец · " + clipStamp(at)));
  const methods = [["waveform","По форме волны"],["spectrum","По спектру"]];
  if ("speed_scan" in data) methods.push(["speed_scan","С поправкой на скорость"]);
  for (const [method,name] of methods) {
    const result = data[method];
    const row = element("div","field-method");
    row.append(element("b","",name));
    if (result) {
      const score = result.score.toLocaleString("ru-RU",{minimumFractionDigits:3, maximumFractionDigits:3});
      const threshold = data.thresholds[method].toLocaleString("ru-RU");
      row.append(element("span","", "r = " + score + " · порог " + threshold));
      if (result.rate_ratio != null) row.append(element("span","", "Скорость копии " + ((result.rate_ratio-1)*100).toLocaleString("ru-RU",{signDisplay:"always",maximumFractionDigits:2}) + " %"));
      if (result.passes) row.append(listenButton("/field-audio/" + candidate + ".wav", result.second, result.window_seconds ?? data.window_seconds,
        "Кандидат · " + clipStamp(result.second)));
      else row.append(element("span","","Ниже порога"));
    } else row.append(element("span","","Нет подходящего окна"));
    box.append(row);
  }
  return box;
}
$("field-form").onsubmit = async event => {
  event.preventDefault();
  stopExcerpt();
  fieldSource.pause();
  const request = ++fieldRequest;
  const candidate = $("field-candidate").value, at = $("field-at").valueAsNumber;
  const scanSpeed = $("field-speed").checked;
  const output = $("field-result");
  $("field-run").disabled = true;
  output.textContent = "Сравниваем записи…";
  try {
    const data = await api("/api/field-compare",{candidate,at,scan_speed:scanSpeed});
    if (request === fieldRequest) {
      output.replaceChildren(renderFieldResult(data, candidate, at));
      if (status.online) output.append(button("listen","Спросить архивиста об этом образце", () => {
        field.close();
        desk().mode = "live";
        renderDesk();
        $("desk-title").scrollIntoView({block:"nearest"});
        const edition = {"small-step":"другой репликой о первом шаге",calibration:"учебной копией","eagle-extended":"расширенной версией"}[candidate];
        submit("Образец NASA начинается с " + at.toLocaleString("ru-RU") + " с. Сравни его по волне и спектру с " + edition + (scanSpeed ? " с учетом скорости." : "."));
      }));
    }
  } catch (err) {
    if (request === fieldRequest) output.textContent = err.message;
  } finally {
    if (request === fieldRequest) $("field-run").disabled = false;
  }
};

$("sound-form").onsubmit = async event => {
  event.preventDefault();
  const request = ++soundRequest;
  const output = $("sound-results");
  const params = {case_id:active.id, start_seconds:audio.currentTime || 0, scope:$("sound-scope").value};
  stopExcerpt();
  $("sound-start").disabled = true;
  output.textContent = "Сравниваем фонограммы…";
  try {
    const measurement = await api("/api/sound-search", params);
    if (request === soundRequest) output.replaceChildren(soundResult(measurement));
  } catch (error) {
    if (request === soundRequest) output.textContent = error.message;
  } finally {
    if (request === soundRequest) $("sound-start").disabled = false;
  }
};

function turnCard(turn) {
  const card = element("article", "turn");
  card.append(element("p", "asked", turn.question), element("p", "answer", turn.answer));
  const refs = element("div", "refs");
  if (turn.transcript) {
    if (turn.transcript.page) refs.append(button("cite", "Открыть стр. " + turn.transcript.page, () => openTranscriptPage({page:turn.transcript.page})));
    const [first, ...others] = turn.transcript.matches;
    const timedList = turn.transcript.mode === "mission_time" && others.length > 0;
    if (timedList) refs.append(renderTranscriptMatches(turn.transcript.matches));
    else if (first) refs.append(button("cite", "Открыть стр. " + first.page, () => openTranscriptPage(first)));
    if (turn.transcript.counterexample) {
      const cited = turn.transcript.counterexample;
      const action = cited.movement_difference ? "Сверить действие на стр. " : "Сверить количество на стр. ";
      refs.append(button("cite", action + cited.page, () => openTranscriptPage(cited)));
    }
    if (others.length && !timedList) {
      const more = element("details", "transcript-alternatives");
      more.append(element("summary", "", "Другие совпадения"), renderTranscriptMatches(others));
      refs.append(more);
    }
    if (turn.transcript.review_candidates?.length) {
      const review = element("details", "transcript-alternatives");
      review.append(element("summary", "", "Похожие строки для самостоятельной сверки"), renderTranscriptMatches(turn.transcript.review_candidates));
      refs.append(review);
    }
  } else if (!turn.measurements.some(m => m.kind === "repeat_clocks")) {
    for (const id of turn.sources) refs.append(button("cite", id, () => read(id)));
  }
  card.append(refs);
  for (const m of turn.measurements) {
    if (m.kind === "repeat_clocks") {
      card.append(repeatClocksResult(m));
      continue;
    }
    if (m.kind === "public_audio") {
      card.append(renderFieldResult(m,m.candidate,m.reference_second));
      const source = element("a", "field-source", "Исходные записи NASA");
      source.href = "https://www.nasa.gov/historical-sounds/";
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      card.append(source);
      continue;
    }
    if (m.kind === "audio") {
      card.append(soundResult(m));
      continue;
    }
    const box = element("div", "measurement");
    box.append(element("span", "", m.label || "Сравнение интервалов"), element("b", "", m.value), element("span", "", m.detail));
    if (m.kind === "tape_position") {
      const record = records.find(r => r.id === m.case_id);
      if (record && m.second < record.duration) box.append(listenButton(record.audio, m.second,
        Math.min(1.6, record.duration - m.second), "Прослушать с " + m.tape));
    }
    card.append(box);
  }
  const log = element("details", "trace");
  log.append(element("summary", "", "Ход проверки · " + turn.steps.length));
  const list = element("ol");
  for (const step of turn.steps) {
    const item = element("li"),
      out = step.output;
    item.append(element("b", "", tools[step.tool] || step.tool));
    if (step.argument) item.append(element("p", "", step.argument));
    if (out.documents) item.append(element("p", "", out.documents.map(d => d.id + " · " + d.title).join("\n") || "Совпадений нет."));
    else if (out.line) item.append(element("p", "", "Стр. " + out.line.page + " · " + out.line.get + " · " + out.line.speaker));
    else if (out.detail || out.text || out.error) item.append(element("p", "", out.detail || out.text || out.error));
    list.append(item);
  }
  log.append(list);
  card.append(log);
  return card;
}

function renderDesk(scroll = false) {
  const d = desk(),
    live = d.mode === "live",
    box = $("conversation");
  $("live").setAttribute("aria-pressed", live);
  $("sample").setAttribute("aria-pressed", !live);
  $("ask").hidden = !live;
  $("send").disabled = d.pending;
  $("question").disabled = d.pending;
  const liveMode = status.online ? status.model + " · локальная модель" : "Опись и стенограмма · без LLM";
  $("model").textContent = live ? liveMode : (d.example?.model || status.model) + " · сохраненный прогон";
  box.replaceChildren();
  const turns = live ? d.turns : (d.example?.turns || []);
  if (!turns.length && live) {
    const suggestions = status.online ? active.questions : [
      "Где на копии находится метка «" + active.markers[0].label + "»?",
      "Что в стенограмме NASA на отметке 102:46:04?",
    ];
    const hint = status.online ? "Начните с вопроса по этому делу" :
      "Без модели можно проверить метку на копии или найти реплику в стенограмме по точному времени.";
    box.append(element("p", "", hint));
    for (const query of suggestions) {
      const b = button("question-btn", query, () => submit(query));
      b.disabled = d.pending;
      box.append(b);
    }
  } else if (!turns.length && !d.error && !live) box.append(element("p", "", "Открываем разбор…"));
  for (const turn of turns) box.append(turnCard(turn));
  if (live && d.pending) box.append(element("p", "pending", "Архивист проверяет документы и метки…"));
  if (d.error) box.append(element("p", "error", d.error));
  if (scroll) box.scrollTop = box.scrollHeight;
  else box.scrollTop = 0;
}
$("live").onclick = () => {
  desk().mode = "live";
  desk().error = "";
  renderDesk();
};
async function openSample() {
  const current = active.id,
    d = desk();
  d.mode = "sample";
  d.error = "";
  renderDesk();
  if (!d.example) {
    try {
      d.example = await api("/api/examples/" + current);
    } catch (err) {
      d.error = err.message;
    }
    if (active.id === current && d.mode === "sample") renderDesk();
  }
}
$("sample").onclick = openSample;
async function submit(query, fromEditor = false) {
  const current = active.id,
    d = desk();
  query = query.trim();
  if (!query || d.pending) return;
  d.pending = true;
  d.error = "";
  if (fromEditor) {
    d.draft = "";
    $("question").value = "";
  }
  renderDesk(true);
  try {
    if (!d.session) d.session = (await api("/api/sessions", {
      case_id: current
    })).session;
    const result = await api("/api/ask", {
      session: d.session,
      question: query
    });
    d.turns.push(result);
  } catch (err) {
    d.error = err.message;
    if (d.error.includes("Сессия закончилась")) d.session = null;
    if (!d.draft) d.draft = query;
    if (active.id === current) $("question").value = d.draft;
  } finally {
    d.pending = false;
    if (active.id === current) renderDesk(true);
  }
}
$("ask").onsubmit = event => {
  event.preventDefault();
  submit($("question").value, true);
};
$("question").addEventListener("input", () => {
  if (active) desk().draft = $("question").value;
});
$("question").onkeydown = event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit($("question").value, true);
  }
};
async function start() {
  const [cases, health] = await Promise.all([api("/api/cases"), api("/api/status")]);
  records = cases;
  status = health;
  $("online").classList.toggle("yes", health.online);
  $("online").textContent = health.online ? "Модель на связи" : "Модель офлайн";
  $("case-count").textContent = String(cases.length).padStart(2, "0");
  $("catalog").replaceChildren(...cases.map(c => {
    const b = button("case-button", "", () => showCase(c.id));
    b.dataset.case = c.id;
    b.append(element("span", "", c.code), element("strong", "", c.title));
    return b;
  }));
  showCase(cases[0].id);
}
start().catch(err => {
  $("case-title").textContent = "Не удалось открыть архив";
  $("brief").textContent = err.message;
});
