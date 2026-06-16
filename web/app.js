const EDITIONS = "/editions/";

// An edition's stable slug, used in ?edition= and matching its JSON basename
// (e.g. "2026-06-15-evening" ↔ "2026-06-15-evening.json").
const slug = (entry) => `${entry.date}-${entry.edition}`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Format "2026-06-15" → "Jun 15, 2026" without Date() (avoids UTC shift).
const formatDate = (iso) => {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
};

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

function section(name) {
  const s = el("section");
  s.dataset.section = name;            // structural hook for future hover/click/reorder
  return s;
}

function renderMasthead(b) {
  const s = section("masthead");
  const logo = el("img", "masthead-logo");
  logo.src = "morningfox.png";
  logo.alt = "";
  s.append(logo);
  s.append(el("h1", "masthead-title", b.title));
  const sub = el("div", "masthead-sub");
  sub.append(el("span", null, b.volume), el("span", null, b.date), el("span", null, b.location));
  s.append(sub);
  return s;
}

function renderWeather(b) {
  const w = b.weather;
  const s = section("weather");
  s.append(el("span", "wx-cond", w.conditions));
  s.append(el("span", "wx-temp", `${w.temp_high}° / ${w.temp_low}°`));
  s.append(el("span", "wx-sun", `↑ ${w.sunrise}  ↓ ${w.sunset}  ${w.daylight}`));
  return s;
}

function renderMarkets(b) {
  const s = section("markets");
  for (const m of b.markets.items) {
    const item = el("div", "market");
    item.append(el("span", "mkt-sym", m.symbol), el("span", "mkt-val", m.value));
    if (m.change) item.append(el("span", "mkt-chg", m.change));
    s.append(item);
  }
  return s;
}

function renderLead(b) {
  const s = section("lead");
  s.append(el("h2", "lead-headline", b.lead.headline));
  s.append(el("p", "lead-deck", b.lead.deck));
  s.append(el("p", "lead-body", b.lead.body));
  const ul = el("ul", "at-a-glance");
  for (const g of b.lead.at_a_glance) ul.append(el("li", null, g));
  s.append(ul);
  return s;
}

function renderPanels(b) {
  const wrap = section("panels");
  for (const p of b.panels) {
    const panel = el("article", "panel");
    panel.dataset.panel = p.section;
    panel.append(el("h3", "panel-section", p.section));
    panel.append(el("h4", "panel-lede-headline", p.lede_headline));
    panel.append(el("p", "panel-lede-body", p.lede_body));
    for (const a of p.also) {
      const item = el("div", "panel-also");
      item.append(el("strong", null, a.headline), el("span", null, ` ${a.body}`));
      panel.append(item);
    }
    wrap.append(panel);
  }
  return wrap;
}

function renderPullQuote(b) {
  const s = section("pull-quote");
  s.append(el("blockquote", null, b.pull_quote));
  return s;
}

function renderBriefs(b) {
  const s = section("briefs");
  s.append(el("h3", "briefs-title", "In Brief"));
  for (const br of b.briefs) {
    const item = el("div", "brief");
    item.append(el("strong", null, br.topic), el("span", null, ` ${br.body}`));
    s.append(item);
  }
  return s;
}

function renderExtras(b) {
  const s = section("extras");
  const dp = el("div", "data-point");
  dp.append(el("span", "dp-value", b.data_point.value), el("span", "dp-context", b.data_point.context));
  const otd = el("div", "on-this-day");
  otd.append(el("strong", null, b.on_this_day.year_and_title), el("span", null, ` ${b.on_this_day.body}`));
  s.append(dp, otd);
  return s;
}

function renderDownload(entry) {
  const s = section("download");
  const a = el("a", "pdf-link", "Download the print edition (PDF)");
  a.href = EDITIONS + entry.pdf;
  s.append(a);
  return s;
}

// Footer dropdown for browsing every published edition. Selecting one
// navigates to its ?edition= slug, which main() then renders.
function renderArchive(index, current) {
  const s = section("archive");
  const sel = el("select", "archive-select");
  sel.setAttribute("aria-label", "Choose an edition");
  for (const e of index) {
    const opt = el("option", null, `${formatDate(e.date)} · ${cap(e.edition)}`);
    opt.value = slug(e);
    if (slug(e) === slug(current)) opt.selected = true;
    sel.append(opt);
  }
  sel.addEventListener("change", () => {
    window.location.search = `?edition=${sel.value}`;
  });
  s.append(el("span", "archive-label", "Past editions"), sel);
  return s;
}

function render(b, entry, index) {
  const paper = document.getElementById("paper");
  paper.replaceChildren(
    renderMasthead(b),
    renderWeather(b),
    renderMarkets(b),
    renderLead(b),
    renderPanels(b),
    renderPullQuote(b),
    renderBriefs(b),
    renderExtras(b),
    renderDownload(entry),
    renderArchive(index, entry),
  );
}

function showStatus(msg) {
  document.getElementById("paper").replaceChildren(el("p", "status", msg));
}

async function main() {
  try {
    const indexRes = await fetch(EDITIONS + "index.json", { cache: "no-store" });
    if (!indexRes.ok) throw new Error(`index.json: HTTP ${indexRes.status}`);
    const index = await indexRes.json();
    if (!Array.isArray(index) || index.length === 0) {
      showStatus("No briefing published yet. Check back after the next edition.");
      return;
    }
    // Honor ?edition=<slug> for shareable/bookmarkable editions; fall back to
    // the latest if the param is absent or names an edition we don't have.
    const wanted = new URLSearchParams(window.location.search).get("edition");
    const entry = (wanted && index.find((e) => slug(e) === wanted)) || index[0];
    const editionRes = await fetch(EDITIONS + entry.json, { cache: "no-store" });
    if (!editionRes.ok) throw new Error(`${entry.json}: HTTP ${editionRes.status}`);
    const briefing = await editionRes.json();
    render(briefing, entry, index);
  } catch (e) {
    showStatus("Could not load the latest edition. Please try again shortly.");
    console.error(e);
  }
}

main();
