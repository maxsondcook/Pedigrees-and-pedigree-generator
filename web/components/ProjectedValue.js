"use client";

function money(n) {
  if (n == null || n === "") return "";
  const num = Number(n);
  if (!Number.isFinite(num) || !num) return "";
  return `$${Math.round(num).toLocaleString()}`;
}

function parseMoney(raw) {
  if (raw == null || raw === "") return null;
  if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) return raw;
  const digits = String(raw).replace(/[^0-9.]/g, "");
  if (!digits) return null;
  const num = Number(digits);
  return Number.isFinite(num) && num > 0 ? num : null;
}

/** True when this hip should never show a breeding-value column (male racing prospects). */
function isMaleYoungstock(vp, lot) {
  const kind = String(vp?.kind || "").toLowerCase();
  if (kind === "colt" || kind === "gelding") return true;
  const role = String(vp?.role || "").toLowerCase();
  const sex = String(lot?.sex_letter || lot?.sex || "").trim().toUpperCase();
  if (role === "youngstock" && ["C", "H", "R", "G"].includes(sex.slice(0, 1))) return true;
  if (/^(COLT|HORSE|RIDGLING|GELDING)/.test(sex)) return true;
  return false;
}

function breedingLabel(vp, lot) {
  if (!vp || isMaleYoungstock(vp, lot)) return "";
  if (vp.breeding_ok === false && !vp.display && vp.point == null) return "";
  if (vp.display) return vp.display;
  if (vp.low != null && vp.high != null && vp.low !== vp.high) {
    return `${money(vp.low)}–${money(vp.high)}`;
  }
  return money(vp.point) || "";
}

function raceLabel(vp) {
  if (!vp) return "";
  const raw = (vp.projected_race_earnings || "").trim();
  if (raw) return raw;
  return "";
}

function soldLabel(lot) {
  if (!lot) return "";
  const raw = lot.price_raw == null ? "" : String(lot.price_raw).trim();
  if (lot.is_rna) {
    if (!raw || raw.toUpperCase() === "RNA") return "RNA";
    return raw.toUpperCase().startsWith("RNA") ? raw : `RNA ${raw}`;
  }
  if (raw && lot.price_num) return raw;
  if (lot.price_num) return money(lot.price_num);
  if (lot.is_out) return "OUT";
  return "";
}

function totalLabel(vp, lot, breedingShown, raceShown) {
  const raceN = parseMoney(raceShown || vp?.projected_race_earnings);
  const allowBreeding = breedingShown && !isMaleYoungstock(vp, lot);
  let low = allowBreeding ? Number(vp?.low) : null;
  let high = allowBreeding ? Number(vp?.high) : null;
  let point = allowBreeding ? Number(vp?.point) : null;
  if (allowBreeding && (!Number.isFinite(low) || !Number.isFinite(high))) {
    // Parse display like "$122,365–$151,921"
    const disp = String(vp?.display || breedingShown || "");
    const parts = disp.split(/[–—-]/).map((p) => parseMoney(p)).filter((n) => n != null);
    if (parts.length >= 2) {
      low = parts[0];
      high = parts[1];
    } else if (parts.length === 1) {
      point = parts[0];
    }
  }
  if (!allowBreeding) {
    return raceN != null ? money(raceN) : "";
  }
  if (Number.isFinite(low) && Number.isFinite(high) && low > 0 && high > 0) {
    const r = raceN || 0;
    const tLow = low + r;
    const tHigh = high + r;
    if (Math.round(tLow) === Math.round(tHigh)) return money(tLow);
    return `${money(tLow)}–${money(tHigh)}`;
  }
  const base = Number.isFinite(point) && point > 0 ? point : parseMoney(breedingShown);
  if (base != null && raceN != null) return money(base + raceN);
  if (base != null) return money(base);
  if (raceN != null) return money(raceN);
  return "";
}

export default function ProjectedValue({ valueProjector, lot, showSold }) {
  const vp = valueProjector || {};
  const breeding = breedingLabel(vp, lot);
  const race = raceLabel(vp);
  const sold = showSold ? soldLabel(lot) : "";
  const showBreeding = Boolean(breeding);
  const showRace = Boolean(race);
  const total = totalLabel(vp, lot, breeding, race);
  const showTotal = Boolean(total) && (showBreeding || showRace);
  const cols = [showBreeding, showRace, showTotal, showSold].filter(Boolean).length;
  const ready = Boolean(breeding || race || sold || total);

  return (
    <div className="projected-value" data-ready={ready ? "1" : "0"} data-cols={cols || 1}>
      <div className={`pv-grid cols-${Math.min(cols || 1, 4)}`}>
        {showBreeding ? (
          <div className="pv-item" data-pv="breeding">
            <span className="pv-label">Breeding value</span>
            <b className="money">{breeding}</b>
          </div>
        ) : null}
        {showRace ? (
          <div className="pv-item" data-pv="race">
            <span className="pv-label">Projected race value</span>
            <b className="money">{race}</b>
          </div>
        ) : null}
        {showTotal ? (
          <div className="pv-item" data-pv="total">
            <span className="pv-label">Total</span>
            <b className="money">{total}</b>
          </div>
        ) : null}
        {showSold ? (
          <div className="pv-item" data-pv="sold">
            <span className="pv-label">Sold</span>
            <b className="money">{sold || "—"}</b>
          </div>
        ) : null}
        {!showBreeding && !showRace && !showTotal && !showSold ? (
          <div className="pv-item">
            <span className="pv-label">Projected value</span>
            <b>—</b>
          </div>
        ) : null}
      </div>
    </div>
  );
}
