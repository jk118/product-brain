import { CAST, SPOTS, createOffice } from "./office.js";

const TEAMS = [
  { key: "brain", label: "Product Brain", short: "Brain", color: "var(--brain)" },
  { key: "naive", label: "Naive memory", short: "Naive", color: "var(--naive)" },
  { key: "no_memory", label: "No memory", short: "None", color: "var(--nomem)" },
];
const ROLES = ["support", "writer", "analyst"];
const PLAT = { ios: "iOS", android: "Android", web: "Web" };
const STATUS = { live: "var(--good)", beta: "var(--warning)", pulled: "var(--critical)", planned: "var(--muted)" };
const AGENTS = {
  support: { title: "Support Agent", kind: "Working agent",
    role: "Answers customer questions about what the product can do today. Turns support tickets and team chat into claims for memory.",
    reads: ["support tickets", "team chat", "announcements"] },
  writer: { title: "Release Notes Writer", kind: "Working agent",
    role: "Writes the \"available now\" release notes at each checkpoint. Turns release logs and code changes into claims.",
    reads: ["release log", "code changes", "announcements", "team chat"] },
  analyst: { title: "Analyst", kind: "Working agent",
    role: "Answers questions about adoption and performance. Turns usage stats and roadmap targets into claims.",
    reads: ["usage stats", "roadmap", "team chat"] },
  curator: { title: "Curator", kind: "Product Brain only",
    role: "The only agent allowed to write to the Product Brain. Resolves conflicts by source authority (release log beats chat), links renamed features, merges duplicate bug reports, reopens regressions, marks stale entries and prunes to a size budget. Naive memory has no curator: every claim is appended.",
    reads: ["every agent's proposals"] },
  judge: { title: "Judge", kind: "Referee, on no team",
    role: "Knows the hidden truth table. At each checkpoint it writes questions with known answers, asks every team, and grades each answer as correct, wrong, stale (true earlier) or unknown. It also grades the release notes line by line.",
    reads: ["hidden truth table"] },
};
// What the curator did with a proposal, keyed by its log action.
const OUTCOME = { create: ["new entry", "var(--brain)"], update: ["applied", "var(--good)"], rollback: ["applied: rollback", "var(--good)"],
  conflict: ["rejected", "var(--critical)"], rename: ["linked rename", "var(--brain)"], merge: ["merged entries", "var(--brain)"],
  dedup: ["merged duplicate", "var(--ink-2)"], new_issue: ["new issue", "var(--brain)"], reopen: ["reopened issue", "var(--serious)"],
  fix: ["closed issue", "var(--good)"], stale: ["dropped stale", "var(--serious)"], prune: ["pruned", "var(--muted)"] };

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = v => (v == null ? "–" : Math.round(v * 100) + "%");
const fmtVal = (type, v) => (type === "adoption" && typeof v === "number" ? (v * 100).toFixed(1).replace(/\.0$/, "") + "%" : String(v).replace(/_/g, " "));
const fmtAns = (a, type) => (Array.isArray(a) ? (a.length ? a.map(f => f.name).join(", ") : "nothing") : fmtVal(type, a));
const hashParam = k => (location.hash.match(new RegExp(`[#&]${k}=([^&]+)`)) || [])[1];

let INDEX = [], RUN = null, day = 0, playing = false, selected = "support", tab = "feed", runId = null;
const office = createOffice($("office"), { onSelect: key => { selectAgent(key); setTab("agent"); } });

// ---- loading ----------------------------------------------------------------
async function boot() {
  try {
    INDEX = await (await fetch("/api/runs")).json();
  } catch {
    $("empty").hidden = false;
    $("empty").textContent = "Open this page through the local server: python -m product_brain serve";
    return;
  }
  if (!INDEX.length) { $("empty").hidden = false; return; }
  $("run").innerHTML = INDEX.map(r => `<option value="${esc(r.id)}">${esc(r.label)}${r.has_agents ? "" : " (no agent activity)"}</option>`).join("");
  const autoplay = hashParam("play") === "1";
  const wanted = decodeURIComponent(hashParam("run") || "");
  const pick = INDEX.find(r => r.id === wanted) || INDEX.find(r => r.has_agents && r.mode === "live")
    || INDEX.find(r => r.has_agents) || INDEX[0];
  await loadRun(pick.id, +(hashParam("day") || 0));
  if (autoplay) play();
}

async function loadRun(id, startDay = 0) {
  stop();
  runId = id;
  $("run").value = id;
  RUN = await (await fetch(`/api/runs/${encodeURIComponent(id)}`)).json();
  RUN.maxNaive = Math.max(...RUN.days.map(d => d.naive_notes || 0), 1);
  const m = RUN.meta;
  $("meta").textContent = `${m.product} · seed ${m.seed} · ${m.days} days · ${m.events} events · ` +
    (m.mode === "mock" ? "mock (pipeline test, no LLM)" : m.agent_model.split("/").pop());
  $("slider").max = m.days - 1;
  show(Math.min(startDay, m.days - 1));
}

// ---- playback -----------------------------------------------------------------
function show(d) {
  day = d;
  $("slider").value = d;
  history.replaceState(null, "", `#run=${encodeURIComponent(runId)}&day=${d}`);
  office.cancel();
  office.home();
  setScene(d);
  phase(RUN.days[d].checkpoint ? "Checkpoint day" : "");
  renderPanels();
}

function setScene(d) {
  const rec = RUN.days[d];
  office.updateVault(rec.brain.length, rec.sizes.brain);
  office.updateWall(rec.naive_notes || 0, (rec.naive_notes || 0) / RUN.maxNaive, rec.sizes.naive);
  office.updateInbox(rec.events.length);
  const cp = [...RUN.days.slice(0, d + 1)].reverse().find(x => x.checkpoint)?.checkpoint;
  office.updateArena(cp?.teams);
  $("dayl").textContent = `Day ${d}`;
}

function phase(text) { $("phase").textContent = text; }

function toast(text, ms = 2200) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toast.id);
  toast.id = setTimeout(() => t.classList.remove("show"), ms);
}

function animateDay(d, done) {
  office.cancel();
  office.home();
  setScene(d);
  const rec = RUN.days[d], A = rec.agents;
  const at = (ms, fn) => office.schedule(ms, fn);

  phase("Morning · events arrive");
  ROLES.forEach((role, i) => {
    const n = A ? A[role].read.length : 0;
    for (let k = 0; k < Math.min(n, 5); k++) at(i * 90 + k * 140, () => office.fly(SPOTS.inbox, office.pos(role), "mail", 650));
    at(800, () => office.say(role, n ? `✉ ${n} new event${n > 1 ? "s" : ""}` : "Quiet morning", 1300));
  });
  if (!A) at(800, () => office.say("judge", "This run has no agent activity log", 2000));

  at(2200, () => {
    phase("Work · agents extract claims");
    ROLES.forEach(role => {
      const ps = A?.[role].proposals || [];
      office.say(role, ps.length ? ps[0].summary + (ps.length > 1 ? `  (+${ps.length - 1})` : "") : "Nothing new to report", 1700);
    });
  });

  const proposers = ROLES.filter(r => A?.[r].proposals.length);
  at(4000, () => {
    if (proposers.length) phase("Proposals go to the curator");
    proposers.forEach(role => office.walk(role, SPOTS.vault[role], 900));
  });

  at(5100, () => {
    proposers.forEach((role, i) => {
      A[role].proposals.slice(0, 4).forEach((_, k) => {
        at(i * 120 + k * 160, () => {
          office.fly(office.pos(role), SPOTS.vaultCenter, "paper", 520);
          office.fly(office.pos(role), SPOTS.wall, "paper naive", 700);
        });
      });
    });
    const counts = curatorCounts(rec.log);
    const bits = [counts.applied && `✓ ${counts.applied} applied`, counts.rejected && `✗ ${counts.rejected} rejected`,
      counts.merged && `⧉ ${counts.merged} merged`].filter(Boolean);
    at(700, () => {
      office.pulseVault(counts.rejected ? "bad" : "ok");
      office.say("curator", bits.length ? bits.join(" · ") : "Nothing changes", 1900, counts.rejected ? "warn" : "");
      const conflict = rec.log.find(l => l.action === "conflict");
      if (conflict) at(1900, () => office.say("curator", `Rejected ${conflict.detail.split(" ")[0]} claim about ${conflict.feature}`, 1800, "warn"));
    });
  });

  at(7600, () => { phase("Back to desks"); proposers.forEach(role => office.walk(role, SPOTS.home[role], 900)); });

  let end = 8700;
  if (rec.checkpoint) {
    const cp = rec.checkpoint;
    const nq = new Set(cp.answers.brain.map(a => a.qid)).size;
    at(8700, () => {
      phase("Checkpoint · the judge asks questions");
      toast(`Checkpoint, day ${d}: ${nq} questions for every team`);
      office.say("judge", `Checkpoint! ${nq} questions`, 1800);
      ROLES.forEach(role => office.walk(role, SPOTS.arena[role], 1400));
    });
    at(10400, () => {
      office.updateArena(cp.teams);
      office.flashPodium();
      const t = cp.teams;
      office.say("judge", `Brain ${pct(t.brain.accuracy)} · Naive ${pct(t.naive.accuracy)} · None ${pct(t.no_memory.accuracy)}`, 2400);
    });
    at(12900, () => ROLES.forEach(role => office.walk(role, SPOTS.home[role], 1400)));
    end = 14400;
  }
  at(end, done);
}

function curatorCounts(log) {
  const c = { applied: 0, rejected: 0, merged: 0 };
  for (const l of log) {
    if (l.action === "conflict") c.rejected++;
    else if (l.action === "dedup") c.merged++;
    else if (l.action !== "prune" && l.action !== "create") c.applied++;
  }
  return c;
}

function play() {
  if (!RUN) return;
  if (day >= RUN.days.length - 1) show(0);
  playing = true;
  $("play").textContent = "❚❚";
  $("play").setAttribute("aria-label", "Pause");
  const step = () => animateDay(day, () => {
    if (!playing) return;
    if (day >= RUN.days.length - 1) return stop();
    day++;
    $("slider").value = day;
    history.replaceState(null, "", `#run=${encodeURIComponent(runId)}&day=${day}`);
    renderPanels();
    step();
  });
  renderPanels();
  step();
}
function stop() {
  playing = false;
  office.cancel();
  $("play").textContent = "▶";
  $("play").setAttribute("aria-label", "Play");
}

// ---- panels -----------------------------------------------------------------
function setTab(t) {
  tab = t;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  document.querySelectorAll(".tabbody").forEach(b => (b.hidden = b.id !== `tab-${t}`));
  renderPanels();
}
function selectAgent(key) { selected = key; office.select(key); }

function renderPanels() {
  if (!RUN) return;
  renderStrip();
  ({ feed: renderFeed, scores: renderScores, brain: renderBrain, checkpoint: renderCheckpoint, notes: renderNotes, agent: renderAgent })[tab]();
}

function checkpointsUpTo(d) { return RUN.days.filter(x => x.checkpoint && x.day <= d).map(x => x.checkpoint); }

function scoreUpTo(d) {
  const cps = checkpointsUpTo(d);
  const out = {};
  for (const t of TEAMS) {
    const all = cps.flatMap(c => c.answers[t.key]);
    const qa = all.filter(a => a.type !== "release_notes"), notes = all.filter(a => a.type === "release_notes");
    const byQ = {};
    qa.forEach(a => (byQ[a.qid] ??= new Set()).add(JSON.stringify(a.answer)));
    const pairs = Object.values(byQ), n = qa.length || 1;
    out[t.key] = {
      n: qa.length, accuracy: qa.filter(a => a.correct).length / n, stale: qa.filter(a => a.stale).length / n,
      unknown: qa.filter(a => a.abstain).length / n, contradiction: pairs.filter(v => v.size > 1).length / (pairs.length || 1),
      notes: notes.length ? notes.at(-1).f1 : null,
      tokens: all.length ? Math.round(all.reduce((a, x) => a + x.tokens, 0) / all.length) : null,
    };
  }
  return cps.length ? out : null;
}

function renderStrip() {
  const sc = scoreUpTo(day);
  const cpDays = RUN.days.filter(x => x.checkpoint).map(x => x.day);
  const done = cpDays.filter(x => x <= day).length;
  $("strip").innerHTML = `<div class="strip-head">${done ? `Scores through day ${day} · ${done}/${cpDays.length} checkpoints` : `First checkpoint on day ${cpDays[0]}`}</div>` +
    TEAMS.map(t => `<div class="strip-team"><span class="dot" style="background:${t.color}"></span><span class="nm">${t.label}</span>
      <span class="num">${sc ? pct(sc[t.key].accuracy) : "–"}</span><span class="lbl">accurate</span>
      <span class="num">${sc ? pct(sc[t.key].stale) : "–"}</span><span class="lbl">stale</span></div>`).join("");
}

function outcomeOf(rec, eventId) {
  const acts = rec.log.filter(l => l.event_id === eventId).map(l => l.action);
  const a = acts.find(x => x === "conflict") || acts.find(x => x !== "create") || acts[0];
  return a ? OUTCOME[a] || [a, "var(--ink-2)"] : ["no change", "var(--muted)"];
}

function renderFeed() {
  const rec = RUN.days[day];
  const events = rec.events.map(e => `<li class="ev"><span class="time">${esc(e.time)}</span>
      <div><span class="type t-${esc(e.type)}">${esc(e.type.replace("_", " "))}</span> <span class="who">${esc(e.author)}</span>
      ${e.trap ? `<span class="trap">${esc(e.trap.replace(/_/g, " "))}</span>` : ""}<div class="txt">#${e.id} ${esc(e.text)}</div></div></li>`).join("");
  const agents = rec.agents ? ROLES.map(role => {
    const ps = rec.agents[role].proposals;
    return `<li class="act"><span class="who-dot" style="background:${CAST[role].color}"></span><div><b>${CAST[role].name}</b>
      <span class="muted">read ${rec.agents[role].read.length}, proposed ${ps.length}</span>
      ${ps.map(p => { const [l, c] = outcomeOf(rec, p.event_id); return `<div class="claim"><span>#${p.event_id} ${esc(p.summary)}</span><span class="out" style="color:${c}">${l}</span></div>`; }).join("")}</div></li>`;
  }).join("") : `<li class="muted">This run has no agent activity log.</li>`;
  const cur = rec.log.map(l => { const [lab, c] = OUTCOME[l.action] || [l.action, "var(--ink-2)"];
    return `<li class="cur"><span class="out" style="color:${c}">${esc(lab)}</span><div><b>${esc(l.feature)}</b> ${esc(l.detail)}</div></li>`; }).join("");
  $("tab-feed").innerHTML = `<h3>Events, day ${day} <span class="count">${rec.events.length}</span></h3><ul class="log">${events || `<li class="muted">No events.</li>`}</ul>
    <h3>Agent claims</h3><ul class="log">${agents}</ul>
    <h3>Curator decisions <span class="count">${rec.log.length}</span></h3><ul class="log">${cur || `<li class="muted">Nothing to curate today.</li>`}</ul>`;
}

function renderScores() {
  const sc = scoreUpTo(day);
  const rec = RUN.days[day];
  const tiles = TEAMS.map(t => {
    const s = sc?.[t.key];
    return `<div class="tile"><div class="tile-h"><span class="dot" style="background:${t.color}"></span>${t.label}</div>
      <div class="heroes"><div><b>${s ? pct(s.accuracy) : "–"}</b><span>accurate</span></div><div><b>${s ? pct(s.stale) : "–"}</b><span>stale</span></div></div>
      <div class="tile-meta">${s ? `${s.n} answers · ${pct(s.unknown)} unknown · ${pct(s.contradiction)} contradictions · notes F1 ${s.notes == null ? "–" : s.notes.toFixed(2)} · ${s.tokens.toLocaleString()} tok/task` : "No checkpoint yet"}
      ${t.key !== "no_memory" ? ` · memory ${rec.sizes[t.key].toLocaleString()} tok` : ""}</div></div>`;
  }).join("");
  $("tab-scores").innerHTML = `${tiles}<div class="chart" id="c-acc"></div><div class="chart" id="c-stale"></div><div class="chart" id="c-size"></div>
    <p class="note">Stale means wrong, but true earlier in the timeline, and said with at least 60% confidence.</p>`;
  const cps = RUN.days.filter(x => x.checkpoint);
  const xs = cps.map(x => x.day);
  const series = metric => TEAMS.map(t => ({ label: t.short, color: t.color, values: cps.map(x => (x.day <= day ? x.checkpoint.teams[t.key][metric] : null)) }));
  lineChart($("c-acc"), { title: "Accuracy at each checkpoint", xs, series: series("accuracy"), yMax: 1, fmt: pct, cursor: day, xName: "Day" });
  const maxStale = Math.max(0.2, ...cps.flatMap(x => TEAMS.map(t => x.checkpoint.teams[t.key].stale_rate)));
  lineChart($("c-stale"), { title: "Stale answer rate", xs, series: series("stale_rate"), yMax: maxStale, fmt: pct, cursor: day, xName: "Day" });
  const dx = RUN.days.map(x => x.day);
  const maxSize = Math.max(...RUN.days.map(x => x.sizes.naive), 100);
  lineChart($("c-size"), { title: "Memory size (tokens)", xs: dx, yMax: Math.ceil(maxSize / 1000) * 1000, fmt: v => (v == null ? "–" : Math.round(v).toLocaleString()), cursor: day, xName: "Day",
    series: TEAMS.filter(t => t.key !== "no_memory").map(t => ({ label: t.short, color: t.color, values: RUN.days.map(x => (x.day <= day ? x.sizes[t.key] : null)) })) });
}

function renderBrain() {
  const rec = RUN.days[day];
  const cards = rec.brain.map(c => {
    const truth = c.fid && rec.truth[c.fid];
    const diffs = truth ? Object.keys(PLAT).filter(k => c.platforms[k] && c.platforms[k].status !== truth.platforms[k]) : [];
    const open = c.issues.filter(i => i.status === "open");
    return `<div class="fcard${diffs.length ? " off" : ""}"><div class="fh"><b>${esc(c.name)}</b>${c.former.length ? `<span class="muted">formerly ${esc(c.former.join(", "))}</span>` : ""}</div>
      <div class="pills">${Object.keys(PLAT).filter(k => c.platforms[k]).map(k => { const p = c.platforms[k];
        return `<span class="pill${p.disputed ? " disputed" : ""}" title="${esc(`${p.source} · day ${p.day}${p.disputed ? " · " + p.disputed : ""}`)}"><i style="background:${STATUS[p.status]}"></i>${PLAT[k]} ${p.status}${p.disputed ? " ⚑" : ""}</span>`; }).join("")}</div>
      <div class="muted small">${[c.adoption != null || c.target != null ? `adoption ${pct(c.adoption)}${c.target != null ? ` vs target ${pct(c.target)}` : ""}` : "",
        open.length ? `${open.length} open issue${open.length > 1 ? "s" : ""} (${open.reduce((a, i) => a + i.reports, 0)} reports)` : ""].filter(Boolean).join(" · ")}</div>
      ${diffs.length ? `<div class="warnline">Differs from truth: ${diffs.map(k => `${PLAT[k]} is really ${truth.platforms[k]}`).join(", ")}</div>` : ""}</div>`;
  }).join("");
  $("tab-brain").innerHTML = `<p class="note">What the curated brain believes on day ${day}. ⚑ marks a claim the curator rejected. Hover a platform to see its source.</p>${cards || `<p class="muted">Empty.</p>`}`;
}

function badge(a) {
  if (a.abstain) return `<span class="bdg unk">?</span>`;
  if (a.correct) return `<span class="bdg ok">✓</span>`;
  return a.stale ? `<span class="bdg stale">STALE</span>` : `<span class="bdg bad">✗</span>`;
}

function latestCheckpoint() { return [...RUN.days.slice(0, day + 1)].reverse().find(x => x.checkpoint); }

function renderCheckpoint() {
  const cpDay = latestCheckpoint();
  if (!cpDay) { $("tab-checkpoint").innerHTML = `<p class="muted">No checkpoint yet. The first is on day ${RUN.days.find(x => x.checkpoint).day}.</p>`; return; }
  const cp = cpDay.checkpoint;
  const qids = [...new Set(cp.answers.brain.filter(a => a.type !== "release_notes").map(a => a.qid))];
  const rows = qids.map(qid => {
    const q = cp.answers.brain.find(a => a.qid === qid);
    const cells = TEAMS.map(t => {
      const as = cp.answers[t.key].filter(a => a.qid === qid);
      const same = as.every(a => JSON.stringify(a.answer) === JSON.stringify(as[0].answer));
      const tip = as.map(a => `${a.agent} (${Math.round(a.confidence * 100)}%): ${a.reason}`).join("\n");
      const body = same ? `${esc(fmtAns(as[0].answer, q.type))} ${badge(as[0])}`
        : as.map(a => `<span class="split">${a.agent[0].toUpperCase()}: ${esc(fmtAns(a.answer, q.type))} ${badge(a)}</span>`).join("");
      return `<div class="qa-cell" title="${esc(tip)}"><span class="dot" style="background:${t.color}"></span><span>${body}</span></div>`;
    }).join("");
    return `<div class="q"><div class="qt">${esc(q.question)}</div><div class="truth">Truth: <b>${esc(fmtVal(q.type, q.truth))}</b></div>${cells}</div>`;
  }).join("");
  $("tab-checkpoint").innerHTML = `<p class="note">Day ${cp.day}: the judge's questions and every team's answers. When Support and Analyst disagree, both are shown. Hover for reasoning.</p>${rows}`;
}

function renderNotes() {
  const cpDay = latestCheckpoint();
  if (!cpDay) { $("tab-notes").innerHTML = `<p class="muted">The Writer drafts release notes at each checkpoint.</p>`; return; }
  const cp = cpDay.checkpoint;
  const fidOf = {};
  RUN.features.forEach(f => f.names.forEach(n => (fidOf[n.toLowerCase()] = f.fid)));
  const truth = new Set(cp.answers.brain.find(a => a.type === "release_notes").truth.map(([f, p]) => `${f}|${p}`));
  const past = new Set();
  RUN.days.filter(x => x.day < cp.day).forEach(x => Object.entries(x.truth).forEach(([fid, st]) =>
    Object.entries(st.platforms).forEach(([p, v]) => v === "live" && past.add(`${fid}|${p}`))));
  const grouped = keys => keys.reduce((g, k) => { const [f, p] = k.split("|"); (g[f] ??= []).push(p); return g; }, {});
  const truthHtml = Object.entries(grouped([...truth])).map(([f, ps]) => `<div class="nl"><span>${esc(cpDay.truth[f].name)}</span><span class="chips">${ps.map(p => `<span class="chip">${PLAT[p]}</span>`).join("")}</span></div>`).join("");
  const teams = TEAMS.map(t => {
    const a = cp.answers[t.key].find(x => x.type === "release_notes");
    const covered = new Set();
    const lines = a.answer.map(f => {
      const fid = fidOf[f.name.trim().toLowerCase()];
      const chips = f.platforms.map(p => {
        const k = `${fid}|${p}`;
        covered.add(k);
        const cls = fid && truth.has(k) ? "ok" : fid && past.has(k) ? "stale" : "bad";
        return `<span class="chip ${cls}">${PLAT[p] || p} ${cls === "ok" ? "✓" : cls === "stale" ? "STALE" : "✗"}</span>`;
      }).join("");
      return `<div class="nl"><span>${esc(f.name)}</span><span class="chips">${chips}</span></div>`;
    }).join("");
    const missing = Object.entries(grouped([...truth].filter(k => !covered.has(k)))).map(([f, ps]) => `${esc(cpDay.truth[f].name)} (${ps.map(p => PLAT[p]).join(", ")})`).join(", ");
    return `<div class="notes-team"><div class="tile-h"><span class="dot" style="background:${t.color}"></span>${t.label}<span class="muted"> · F1 ${a.f1.toFixed(2)}</span></div>
      ${lines || `<p class="muted">Listed nothing.</p>`}${missing ? `<div class="missing">Missing: ${missing}</div>` : ""}</div>`;
  }).join("");
  $("tab-notes").innerHTML = `<p class="note">Day ${cp.day}: each team's Writer drafts the "available now" notes from its own memory, checked line by line against what is really live.</p>
    <div class="notes-team truth"><div class="tile-h">Actually live</div>${truthHtml}</div>${teams}`;
}

function renderAgent() {
  const info = AGENTS[selected], rec = RUN.days[day];
  const upto = RUN.days.slice(0, day + 1);
  const picker = Object.keys(AGENTS).map(k => `<button class="agent-pick${k === selected ? " active" : ""}" data-agent="${k}"><span class="dot" style="background:${CAST[k].color}"></span>${CAST[k].name}</button>`).join("");
  let today = "", sofar = "";
  if (ROLES.includes(selected)) {
    const a = rec.agents?.[selected];
    if (!a) today = `<p class="muted">This run has no agent activity log.</p>`;
    else {
      today = `<p>Read ${a.read.length} event${a.read.length === 1 ? "" : "s"} · proposed ${a.proposals.length} claim${a.proposals.length === 1 ? "" : "s"}</p>` +
        a.proposals.map(p => { const [l, c] = outcomeOf(rec, p.event_id); return `<div class="claim"><span>#${p.event_id} ${esc(p.summary)}</span><span class="out" style="color:${c}">${l}</span></div>`; }).join("");
      const tot = upto.reduce((acc, x) => { const g = x.agents?.[selected]; if (g) { acc.read += g.read.length; acc.prop += g.proposals.length;
        acc.rej += g.proposals.filter(p => outcomeOf(x, p.event_id)[0] === "rejected").length; } return acc; }, { read: 0, prop: 0, rej: 0 });
      sofar = `<p>${tot.read} events read · ${tot.prop} claims proposed · ${tot.rej} rejected by the curator</p>`;
    }
    const cps = checkpointsUpTo(day);
    sofar += `<div class="agent-stats">${TEAMS.map(t => {
      const all = cps.flatMap(c => c.answers[t.key]).filter(x => x.agent === selected);
      const v = selected === "writer" ? (all.at(-1) ? all.at(-1).f1.toFixed(2) : "–") : all.length ? pct(all.filter(x => x.correct).length / all.length) : "–";
      return `<div><span class="dot" style="background:${t.color}"></span>${t.short}<b>${v}</b></div>`;
    }).join("")}</div><p class="note">${selected === "writer" ? "Latest release-notes F1" : "Accuracy on its checkpoint answers"}, by team.</p>`;
  } else if (selected === "curator") {
    const count = log => log.reduce((c, l) => { const k = (OUTCOME[l.action] || [l.action])[0]; c[k] = (c[k] || 0) + 1; return c; }, {});
    const fmt = c => Object.entries(c).map(([k, v]) => `${v} ${k}`).join(" · ") || "nothing";
    today = `<p>${fmt(count(rec.log))}</p>` + rec.log.map(l => `<div class="claim"><span><b>${esc(l.feature)}</b> ${esc(l.detail)}</span><span class="out" style="color:${(OUTCOME[l.action] || [, "var(--ink-2)"])[1]}">${esc((OUTCOME[l.action] || [l.action])[0])}</span></div>`).join("");
    sofar = `<p>${fmt(count(upto.flatMap(x => x.log)))}</p><p>Brain ${rec.sizes.brain.toLocaleString()} tokens vs naive memory ${rec.sizes.naive.toLocaleString()}</p>`;
  } else {
    const cpDays = RUN.days.filter(x => x.checkpoint).map(x => x.day), next = cpDays.find(x => x > day);
    today = rec.checkpoint ? `<p>Checkpoint: asked ${new Set(rec.checkpoint.answers.brain.map(x => x.qid)).size} questions and graded all three teams.</p>`
      : `<p>${next != null ? `Waiting. Next checkpoint on day ${next}.` : "No more checkpoints."}</p>`;
    sofar = `<p>${checkpointsUpTo(day).length} of ${cpDays.length} checkpoints done.</p>`;
  }
  $("tab-agent").innerHTML = `<div class="agent-picker">${picker}</div>
    <div class="agent-card"><div class="ah"><span class="avatar" style="background:${CAST[selected].color}">${CAST[selected].letter}</span>
      <div><b>${info.title}</b><div class="kind">${info.kind}</div></div></div>
      <p class="role">${esc(info.role)}</p><div class="reads">Reads ${info.reads.map(r => `<span class="chip">${esc(r)}</span>`).join("")}</div>
      <h3>Today, day ${day}</h3>${today}<h3>So far</h3>${sofar}</div>`;
  $("tab-agent").querySelectorAll(".agent-pick").forEach(b => (b.onclick = () => { selectAgent(b.dataset.agent); renderAgent(); }));
}

// ---- small line chart with hover -------------------------------------------------
function lineChart(host, { xs, series, yMax, fmt, title, cursor, xName }) {
  const W = Math.max(260, host.clientWidth || 340), H = 150, m = { l: 38, r: 70, t: 22, b: 22 };
  const x = v => m.l + (xs.length < 2 ? 0 : ((v - xs[0]) / (xs.at(-1) - xs[0])) * (W - m.l - m.r));
  const y = v => H - m.b - (v / (yMax || 1)) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}"><text class="ct" x="0" y="11">${esc(title)}</text>`;
  [0, yMax / 2, yMax].forEach(t => (s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" class="grid"/><text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`));
  const step = Math.max(1, Math.ceil(xs.length / 7));
  xs.forEach((v, i) => { if (i % step === 0 || i === xs.length - 1) s += `<text x="${x(v)}" y="${H - 6}" text-anchor="middle">${v}</text>`; });
  if (cursor != null) s += `<line x1="${x(Math.min(Math.max(cursor, xs[0]), xs.at(-1)))}" x2="${x(Math.min(Math.max(cursor, xs[0]), xs.at(-1)))}" y1="${m.t}" y2="${y(0)}" class="cursor"/>`;
  const labels = [];
  series.forEach(sr => {
    const pts = sr.values.map((v, i) => (v == null ? null : [x(xs[i]), y(v)])).filter(Boolean);
    if (!pts.length) return;
    s += `<polyline fill="none" style="stroke:${sr.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="${pts.map(p => p.join(",")).join(" ")}"/>`;
    if (xs.length < 10) pts.forEach(p => (s += `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" style="fill:${sr.color}" class="mk"/>`));
    labels.push({ x: pts.at(-1)[0], y: pts.at(-1)[1], text: `${sr.label} ${fmt(sr.values.filter(v => v != null).at(-1))}` });
  });
  labels.sort((a, b) => a.y - b.y).forEach((l, i, arr) => { if (i && l.y - arr[i - 1].y < 12) l.y = arr[i - 1].y + 12; });
  for (let i = labels.length - 1, floor = y(0); i >= 0; i--, floor -= 12) labels[i].y = Math.min(labels[i].y, floor);
  labels.forEach(l => (s += `<text class="dl" x="${l.x + 7}" y="${l.y + 4}">${esc(l.text)}</text>`));
  s += `<line class="xh" x1="0" x2="0" y1="${m.t}" y2="${y(0)}" visibility="hidden"/><rect x="${m.l - 8}" y="0" width="${W - m.l - m.r + 16}" height="${H}" fill="transparent"/></svg>`;
  host.innerHTML = s;
  const svg = host.querySelector("svg"), xh = svg.querySelector(".xh"), tip = $("tip"), hit = svg.querySelector("rect");
  hit.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) * W) / r.width;
    let i = 0;
    xs.forEach((v, j) => { if (Math.abs(x(v) - px) < Math.abs(x(xs[i]) - px)) i = j; });
    xh.setAttribute("x1", x(xs[i])); xh.setAttribute("x2", x(xs[i])); xh.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${xName} ${xs[i]}</b>` + series.map(sr => `<div><span class="dot" style="background:${sr.color}"></span> ${esc(sr.label)}: ${fmt(sr.values[i])}</div>`).join("");
    tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX + 14, innerWidth - 180) + "px";
    tip.style.top = ev.clientY + 14 + "px";
  });
  hit.addEventListener("mouseleave", () => { tip.style.display = "none"; xh.setAttribute("visibility", "hidden"); });
}

// ---- controls ---------------------------------------------------------------------
$("play").onclick = () => (playing ? stop() : play());
$("slider").oninput = e => { stop(); show(+e.target.value); };
$("speed").onchange = e => office.setSpeed(+e.target.value);
$("run").onchange = e => loadRun(e.target.value);
document.querySelectorAll(".tabs button").forEach(b => (b.onclick = () => setTab(b.dataset.tab)));
addEventListener("keydown", e => {
  if (!RUN || ["INPUT", "SELECT"].includes(e.target.tagName) && e.target.type !== "range") return;
  if (e.key === "ArrowRight") { stop(); show(Math.min(day + 1, RUN.days.length - 1)); }
  if (e.key === "ArrowLeft") { stop(); show(Math.max(day - 1, 0)); }
  if (e.key === " ") { e.preventDefault(); playing ? stop() : play(); }
});
addEventListener("resize", () => tab === "scores" && renderScores());
selectAgent(selected);
boot();
