"use client";

import { Fragment, Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { apiGet, apiPost, horseHref } from "../../lib/api";
import { deskKey, loadDesk, saveDesk, starredIds, withStarToggle } from "../../lib/salesDesk";
import {
  horseHrefWithReturn,
  salesHref,
  salesReturnFromParts,
} from "../../lib/salesNav";
import PedigreeChart from "../../components/PedigreeChart";
import FemaleFamily from "../../components/FemaleFamily";
import ProjectedValue from "../../components/ProjectedValue";

function money(n) {
  if (n == null || n === "") return "—";
  const num = Number(n);
  if (!num) return "—";
  return `$${num.toLocaleString()}`;
}

function priceLabel(lot) {
  if (!lot) return "—";
  const raw = lot.price_raw == null ? "" : String(lot.price_raw).trim();
  if (lot.is_rna) {
    if (!raw || raw.toUpperCase() === "RNA") return "RNA";
    return raw.toUpperCase().startsWith("RNA") ? raw : `RNA ${raw}`;
  }
  if (raw && lot.price_num) return raw;
  if (lot.price_num) return money(lot.price_num);
  return "—";
}

function navId(mode, lot) {
  if (!lot) return "";
  return mode === "past" ? String(lot.id) : String(lot.hip ?? "");
}

function blank(value) {
  return value == null ? "" : String(value).trim();
}

function sexWord(lot) {
  if (!lot) return "";
  if (lot.sex_label) return lot.sex_label;
  const letter = String(lot.sex_letter || lot.sex || "").trim().toUpperCase().slice(0, 1);
  return ({
    C: "Colt", F: "Filly", M: "Mare", H: "Horse", G: "Gelding", R: "Ridgling", W: "Weanling",
  })[letter] || blank(lot.sex) || "";
}

function colorWord(lot) {
  if (!lot) return "";
  if (lot.color_label) return lot.color_label;
  const key = blank(lot.color).toUpperCase().replace(/\./g, "").replace(/\s+/g, " ");
  return ({
    B: "Bay",
    CH: "Chestnut",
    "DK B/BR": "Dark Bay or Brown",
    "GR/RO": "Gray/Roan",
    GR: "Gray",
    RO: "Roan",
    BLK: "Black",
  })[key] || blank(lot.color);
}

function projectedPriceLabel(detail) {
  const band = detail?.expected_market;
  if (band?.label) return band.label;
  return "Projection unavailable";
}

/** Y/W → Price + Value; broodmare catalogs → Value only; 2yo/HORA → hide both. */
function projectionPanels(detail, lot) {
  const em = detail?.expected_market;
  if (em && typeof em.show_projected_price === "boolean") {
    return {
      showPrice: Boolean(em.show_projected_price),
      showValue: Boolean(em.show_projected_value),
    };
  }
  const kind = em?.sold_as || lot?.sold_as_kind || "";
  const role = em?.value_projector?.role || "";
  const isYW = kind === "Yearling" || kind === "Weanling";
  const isBroodmare = role === "broodmare";
  return { showPrice: isYW, showValue: isYW || isBroodmare };
}

/** Show sale title once; skip appending year when already in the title. */
function saleHeading(title, year) {
  const name = blank(title);
  const y = year == null || year === "" ? "" : String(year).trim();
  if (!name) return y;
  if (!y) return name;
  if (name.includes(y)) return name;
  return `${name} ${y}`;
}

/** Widening lower bands, then $250k steps to $2M. Half-open [min, max); last is 2M+. */
const PRICE_RANGES = [
  { id: "1-5", min: 1000, max: 5000, label: "$1,000–5k" },
  { id: "5-10", min: 5000, max: 10000, label: "5k–10k" },
  { id: "10-20", min: 10000, max: 20000, label: "10k–20k" },
  { id: "20-30", min: 20000, max: 30000, label: "20k–30k" },
  { id: "30-45", min: 30000, max: 45000, label: "30k–45k" },
  { id: "45-60", min: 45000, max: 60000, label: "45k–60k" },
  { id: "60-100", min: 60000, max: 100000, label: "60k–100k" },
  { id: "100-150", min: 100000, max: 150000, label: "100k–150k" },
  { id: "150-250", min: 150000, max: 250000, label: "150k–250k" },
  { id: "250-500", min: 250000, max: 500000, label: "250k–500k" },
  { id: "500-750", min: 500000, max: 750000, label: "500k–750k" },
  { id: "750-1000", min: 750000, max: 1000000, label: "750k–1M" },
  { id: "1000-1250", min: 1000000, max: 1250000, label: "1M–1.25M" },
  { id: "1250-1500", min: 1250000, max: 1500000, label: "1.25M–1.5M" },
  { id: "1500-1750", min: 1500000, max: 1750000, label: "1.5M–1.75M" },
  { id: "1750-2000", min: 1750000, max: 2000000, label: "1.75M–2M" },
  { id: "2000+", min: 2000000, max: null, label: "2M+" },
];

function lotFilterPrice(lot) {
  if (!lot) return 0;
  const direct = Number(lot.filter_price);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const sale = Number(lot.price_num);
  if (Number.isFinite(sale) && sale > 0) return sale;
  return 0;
}

function priceInRanges(price, selectedIds) {
  if (!selectedIds.length) return true;
  if (!price) return false;
  return selectedIds.some((id) => {
    const range = PRICE_RANGES.find((row) => row.id === id);
    if (!range) return false;
    if (price < range.min) return false;
    if (range.max == null) return true;
    return price < range.max;
  });
}

function SalesPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState("");
  const [years, setYears] = useState([]);
  const [year, setYear] = useState("");
  const [catalogs, setCatalogs] = useState([]);
  const [pastCatalogs, setPastCatalogs] = useState([]);
  const [upcomingCatalogs, setUpcomingCatalogs] = useState([]);
  const [loadingPast, setLoadingPast] = useState(false);
  const [loadingUpcoming, setLoadingUpcoming] = useState(false);
  const [loadingCatalogs, setLoadingCatalogs] = useState(false);
  const [pastOpen, setPastOpen] = useState(false);
  const [upcomingOpen, setUpcomingOpen] = useState(true);
  const [catalog, setCatalog] = useState(null);
  const [lots, setLots] = useState([]);
  const [listError, setListError] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [currentId, setCurrentId] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [hipInput, setHipInput] = useState("");
  const [jumpError, setJumpError] = useState("");
  const [railOpen, setRailOpen] = useState(false);
  const [desk, setDesk] = useState({ clients: [], dismissed: {}, notes: {}, stars: {} });
  const [activeClient, setActiveClient] = useState("");
  const [sex, setSex] = useState("");
  const [color, setColor] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [selectedSires, setSelectedSires] = useState([]);
  const [sireQuery, setSireQuery] = useState("");
  const [priceRanges, setPriceRanges] = useState([]);
  const [height, setHeight] = useState("");
  const [onlyDismissed, setOnlyDismissed] = useState(false);
  const [onlyStarred, setOnlyStarred] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteState, setNoteState] = useState("");
  const [openAuction, setOpenAuction] = useState("");
  const readyRef = useRef(false);
  const draftRef = useRef("");
  const loadedNote = useRef("");
  const restoreRef = useRef(null);
  const restoreBooted = useRef(false);

  useEffect(() => {
    setDesk(loadDesk());
  }, []);

  useEffect(() => {
    if (restoreBooted.current) return;
    restoreBooted.current = true;
    const modeParam = searchParams.get("mode") || "";
    const catalogParam = searchParams.get("catalog") || "";
    const hipParam = searchParams.get("hip") || "";
    const lotParam = searchParams.get("lot") || "";
    const yearParam = searchParams.get("year") || "";
    const titleParam = searchParams.get("title") || "";
    if (!modeParam || !catalogParam) return;
    restoreRef.current = {
      mode: modeParam,
      catalogId: catalogParam,
      hip: hipParam,
      lotId: lotParam,
      year: yearParam,
      title: titleParam,
    };
    setMode(modeParam);
    if (yearParam) setYear(yearParam);
    setLoadingCatalogs(true);
  }, [searchParams]);

  // Entry screen: keep Past + Upcoming lists loaded independently (both start open).
  useEffect(() => {
    if (catalog) return;
    apiGet("/api/sales/years")
      .then((d) => {
        const list = d.years || [];
        setYears(list);
        setYear((prev) => prev || (list[0] != null ? String(list[0]) : ""));
      })
      .catch((e) => setListError(e.message));
  }, [catalog]);

  useEffect(() => {
    if (catalog || !year) return;
    setLoadingPast(true);
    apiGet(`/api/sales/catalogs?year=${year}`)
      .then((d) => setPastCatalogs(d.catalogs || []))
      .catch((e) => setListError(e.message))
      .finally(() => setLoadingPast(false));
  }, [catalog, year]);

  useEffect(() => {
    if (catalog) return;
    setLoadingUpcoming(true);
    apiGet("/api/sales/upcoming")
      .then((d) => setUpcomingCatalogs(d.catalogs || []))
      .catch((e) => setListError(e.message))
      .finally(() => setLoadingUpcoming(false));
  }, [catalog]);

  // Catalog workspace: load the list for the active mode (URL restore / open catalog).
  useEffect(() => {
    if (!catalog && mode !== "past") return;
    if (mode !== "past") return;
    apiGet("/api/sales/years")
      .then((d) => {
        const list = d.years || [];
        setYears(list);
        setYear((prev) => prev || (list[0] != null ? String(list[0]) : ""));
      })
      .catch((e) => setListError(e.message));
  }, [mode, catalog]);

  useEffect(() => {
    if (mode !== "past" || !year || !catalog) return;
    setListError("");
    setLoadingCatalogs(true);
    apiGet(`/api/sales/catalogs?year=${year}`)
      .then((d) => setCatalogs(d.catalogs || []))
      .catch((e) => setListError(e.message))
      .finally(() => setLoadingCatalogs(false));
  }, [mode, year, catalog]);

  useEffect(() => {
    if (mode !== "upcoming" || !catalog) return;
    setListError("");
    setLoadingCatalogs(true);
    apiGet("/api/sales/upcoming")
      .then((d) => setCatalogs(d.catalogs || []))
      .catch((e) => setListError(e.message))
      .finally(() => setLoadingCatalogs(false));
  }, [mode, catalog]);

  useEffect(() => {
    const pending = restoreRef.current;
    if (!pending || pending.mode !== mode || catalog) return;
    const pool = pending.mode === "upcoming" ? upcomingCatalogs : (catalogs.length ? catalogs : pastCatalogs);
    if (!pool.length) return;
    const match = pool.find((item) => String(item.id) === String(pending.catalogId));
    if (!match) return;
    setCatalog(match);
  }, [catalogs, pastCatalogs, upcomingCatalogs, mode, catalog]);

  useEffect(() => {
    setSelectedSires([]);
    setSireQuery("");
    setPriceRanges([]);
  }, [catalog?.id, mode]);

  useEffect(() => {
    if (!catalog) return;
    let cancel = false;
    setLoadingList(true);
    setListError("");
    setLots([]);
    setCurrentId("");
    setDetail(null);
    const path = mode === "upcoming"
      ? `/api/sales/upcoming/${encodeURIComponent(catalog.id)}/lots`
      : `/api/sales/catalogs/${catalog.id}/nav`;
    apiGet(path)
      .then((d) => {
        if (cancel) return;
        const rows = d.lots || [];
        setLots(rows);
        const pending = restoreRef.current;
        let nextId = rows[0] ? navId(mode, rows[0]) : "";
        if (pending && String(pending.catalogId) === String(catalog.id) && pending.mode === mode) {
          const want = mode === "past"
            ? String(pending.lotId || pending.hip || "")
            : String(pending.hip || "");
          if (want && rows.some((lot) => navId(mode, lot) === want)) {
            nextId = want;
          }
          restoreRef.current = null;
        }
        if (nextId) setCurrentId(nextId);
      })
      .catch((e) => {
        if (!cancel) setListError(e.message);
      })
      .finally(() => {
        if (!cancel) setLoadingList(false);
      });
    return () => { cancel = true; };
  }, [catalog, mode]);

  const dismissedSet = useMemo(() => {
    if (!catalog) return new Set();
    const list = (desk.dismissed || {})[deskKey(mode, catalog.id)] || [];
    return new Set(list.map(String));
  }, [desk, catalog, mode]);

  const starredSet = useMemo(() => {
    if (!catalog) return new Set();
    return new Set(starredIds(desk, mode, catalog.id));
  }, [desk, catalog, mode]);

  const sireOptions = useMemo(() => {
    const counts = new Map();
    for (const lot of lots) {
      const name = blank(lot.sire);
      if (!name) continue;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    return [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [lots]);

  const visibleSireOptions = useMemo(() => {
    const q = sireQuery.trim().toLowerCase();
    if (!q) return sireOptions;
    return sireOptions.filter((row) => row.name.toLowerCase().includes(q));
  }, [sireOptions, sireQuery]);

  const sexOptions = useMemo(() => {
    const map = new Map();
    for (const lot of lots) {
      const letter = (lot.sex_letter || lot.sex || "").toUpperCase().slice(0, 1);
      if (!letter) continue;
      map.set(letter, sexWord(lot) || letter);
    }
    const order = ["C", "F", "G", "R", "H", "M", "W"];
    return [...map.entries()]
      .map(([letter, label]) => ({ letter, label }))
      .sort((a, b) => {
        const ai = order.indexOf(a.letter);
        const bi = order.indexOf(b.letter);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.label.localeCompare(b.label);
      });
  }, [lots]);

  const priceProxyNote = useMemo(() => {
    if (!lots.length) return "";
    const sources = new Set(lots.map((lot) => lot.filter_price_source).filter(Boolean));
    if (sources.has("sale_price") && (sources.has("expected_market_mid") || sources.has("unknown"))) {
      return "Price uses sale price when sold; otherwise Projected Price mid.";
    }
    if (sources.has("sale_price")) return "Price uses catalog sale price.";
    return "Price uses Projected Price mid — no sale prices yet.";
  }, [lots]);

  function lotIsStarred(lot) {
    if (!lot) return false;
    const id = navId(mode, lot);
    if (starredSet.has(id)) return true;
    if (mode === "upcoming" && lot.starred) return true;
    return false;
  }

  const filtered = useMemo(() => {
    const sireSet = new Set(selectedSires);
    return lots.filter((lot) => {
      const id = navId(mode, lot);
      const dismissed = dismissedSet.has(id);
      const isStarred = starredSet.has(id) || (mode === "upcoming" && Boolean(lot.starred));
      if (onlyStarred) return isStarred;
      if (onlyDismissed) return dismissed;
      if (dismissed) return false;
      const letter = (lot.sex_letter || lot.sex || "").toUpperCase().slice(0, 1);
      if (sex && letter !== sex) return false;
      if (sireSet.size) {
        const sire = blank(lot.sire);
        if (!sire || !sireSet.has(sire)) return false;
      }
      if (color) {
        const coat = (lot.color || lot.color_label || "").toLowerCase();
        if (!coat || !coat.includes(color.trim().toLowerCase())) return false;
      }
      if (!priceInRanges(lotFilterPrice(lot), priceRanges)) return false;
      if (maxPrice) {
        const price = lotFilterPrice(lot);
        if (!price || price > Number(maxPrice)) return false;
      }
      if (height) {
        const hands = (lot.height || "").toLowerCase();
        if (!hands || !hands.includes(height.trim().toLowerCase())) return false;
      }
      return true;
    });
  }, [lots, mode, dismissedSet, starredSet, onlyDismissed, onlyStarred, sex, color, maxPrice, height, selectedSires, priceRanges]);

  useEffect(() => {
    if (!catalog || !filtered.length) return;
    if (!filtered.some((lot) => navId(mode, lot) === currentId)) {
      setCurrentId(navId(mode, filtered[0]));
    }
  }, [filtered, currentId, catalog, mode]);

  const current = filtered.find((lot) => navId(mode, lot) === currentId) || null;
  const position = current ? filtered.findIndex((lot) => navId(mode, lot) === currentId) : -1;

  useEffect(() => {
    setHipInput(current?.hip != null ? String(current.hip) : "");
    setJumpError("");
    setOpenAuction("");
    setNoteDraft("");
    setNoteState("");
  }, [currentId]);

  useEffect(() => {
    if (!catalog || !current) return;
    let cancel = false;
    setLoadingDetail(true);
    setDetailError("");
    const path = mode === "upcoming"
      ? `/api/sales/upcoming/${encodeURIComponent(catalog.id)}/lots/${encodeURIComponent(current.hip)}`
      : `/api/sales/lots/${current.id}`;
    apiGet(path)
      .then((d) => {
        if (cancel) return;
        setDetail(d);
        const pastNote = (loadDesk().notes || {})[String(d.lot?.id)] || "";
        const text = mode === "past" ? pastNote : (d.lot?.notes || "");
        loadedNote.current = text;
        setNoteDraft(text);
      })
      .catch((e) => {
        if (!cancel) setDetailError(e.message);
      })
      .finally(() => {
        if (!cancel) setLoadingDetail(false);
      });
    return () => { cancel = true; };
  }, [catalog, mode, currentId]);

  const ready = Boolean(detail && current && navId(mode, detail.lot) === currentId);
  readyRef.current = ready;
  draftRef.current = noteDraft;
  const starred = Boolean(current && lotIsStarred(current));
  const starredCount = useMemo(
    () => lots.filter((lot) => lotIsStarred(lot)).length,
    // lotIsStarred closes over mode/starredSet
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lots, mode, starredSet],
  );

  const salesReturn = useMemo(() => {
    if (!catalog || !current) return null;
    return salesReturnFromParts({
      mode,
      catalogId: catalog.id,
      catalogTitle: catalog.title,
      year: mode === "past" ? year : catalog.year,
      hip: current.hip,
      lotId: current.id,
    });
  }, [catalog, current, mode, year]);

  const hrefFor = useMemo(
    () => (horseName) => (salesReturn ? horseHrefWithReturn(horseName, salesReturn) : horseHref(horseName)),
    [salesReturn],
  );

  useEffect(() => {
    if (!salesReturn || typeof window === "undefined") return;
    const next = salesHref(salesReturn);
    const currentPath = `${pathname}${window.location.search || ""}`;
    if (currentPath === next) return;
    router.replace(next, { scroll: false });
  }, [salesReturn, pathname, router]);

  // Past and upcoming are alternatives: opening one closes the other.
  function togglePastSection() {
    const next = !pastOpen;
    setPastOpen(next);
    if (next) setUpcomingOpen(false);
  }

  function toggleUpcomingSection() {
    const next = !upcomingOpen;
    setUpcomingOpen(next);
    if (next) setPastOpen(false);
  }

  function openCatalog(item, nextMode) {
    restoreRef.current = null;
    setMode(nextMode);
    setCatalog(item);
    setCatalogs(nextMode === "upcoming" ? upcomingCatalogs : pastCatalogs);
    setRailOpen(false);
    setOnlyDismissed(false);
    setActiveClient("");
    setSex("");
    setColor("");
    setMaxPrice("");
    setHeight("");
  }

  function updateClient(id, patch) {
    const next = {
      ...desk,
      clients: (desk.clients || []).map((client) => (client.id === id ? { ...client, ...patch } : client)),
    };
    setDesk(saveDesk(next));
  }

  function applyFilter(patch) {
    if (patch.sex !== undefined) setSex(patch.sex);
    if (patch.color !== undefined) setColor(patch.color);
    if (patch.maxPrice !== undefined) setMaxPrice(patch.maxPrice);
    if (patch.height !== undefined) setHeight(patch.height);
    if (patch.selectedSires !== undefined) setSelectedSires(patch.selectedSires);
    if (patch.priceRanges !== undefined) setPriceRanges(patch.priceRanges);
    if (activeClient) {
      const clientPatch = {};
      if (patch.sex !== undefined) clientPatch.sex = patch.sex;
      if (patch.color !== undefined) clientPatch.color = patch.color;
      if (patch.maxPrice !== undefined) clientPatch.maxPrice = patch.maxPrice;
      if (patch.height !== undefined) clientPatch.height = patch.height;
      if (Object.keys(clientPatch).length) updateClient(activeClient, clientPatch);
    }
  }

  function toggleSire(name) {
    setSelectedSires((cur) => (
      cur.includes(name) ? cur.filter((item) => item !== name) : [...cur, name]
    ));
  }

  function togglePriceRange(id) {
    setPriceRanges((cur) => (
      cur.includes(id) ? cur.filter((item) => item !== id) : [...cur, id]
    ));
  }

  function selectClient(client) {
    if (activeClient === client.id) {
      setActiveClient("");
      return;
    }
    setActiveClient(client.id);
    setOnlyDismissed(false);
    setOnlyStarred(false);
    setSex(client.sex || "");
    setColor(client.color || "");
    setMaxPrice(client.maxPrice || "");
    setHeight(client.height || "");
  }

  function viewFull() {
    setSex("");
    setColor("");
    setMaxPrice("");
    setHeight("");
    setSelectedSires([]);
    setPriceRanges([]);
    setOnlyDismissed(false);
    setOnlyStarred(false);
    setActiveClient("");
  }

  function viewDismissed() {
    setOnlyDismissed(true);
    setOnlyStarred(false);
    setSex("");
    setColor("");
    setMaxPrice("");
    setHeight("");
    setSelectedSires([]);
    setPriceRanges([]);
    setActiveClient("");
    setRailOpen(true);
  }

  function viewStarred() {
    setOnlyStarred(true);
    setOnlyDismissed(false);
    setSex("");
    setColor("");
    setMaxPrice("");
    setHeight("");
    setSelectedSires([]);
    setPriceRanges([]);
    setActiveClient("");
    setRailOpen(true);
  }

  function jumpToHip(raw) {
    const hip = String(raw || "").trim();
    const found = filtered.find((lot) => String(lot.hip) === hip);
    if (!found) {
      setJumpError("That hip is not in this list.");
      return;
    }
    setJumpError("");
    setCurrentId(navId(mode, found));
  }

  function dismissCurrent() {
    if (!catalog || !current) return;
    const neighbor = filtered[position + 1] || filtered[position - 1] || null;
    const key = deskKey(mode, catalog.id);
    const list = new Set(((desk.dismissed || {})[key] || []).map(String));
    list.add(currentId);
    const next = { ...desk, dismissed: { ...desk.dismissed, [key]: Array.from(list) } };
    setDesk(saveDesk(next));
    if (neighbor) setCurrentId(navId(mode, neighbor));
  }

  async function toggleStar() {
    if (!current || !catalog) return;
    const nextOn = !starred;
    try {
      if (mode === "upcoming") {
        const data = await apiPost(
          `/api/sales/upcoming/${encodeURIComponent(catalog.id)}/lots/${encodeURIComponent(current.hip)}`,
          { starred: nextOn },
        );
        const on = Boolean(data.lot?.starred);
        setLots((rows) => rows.map((lot) => (String(lot.hip) === String(current.hip) ? { ...lot, starred: on } : lot)));
        setDetail((prev) => (prev && String(prev.lot?.hip) === String(current.hip)
          ? { ...prev, lot: { ...prev.lot, starred: on } }
          : prev));
        setDesk(saveDesk(withStarToggle(desk, mode, catalog.id, currentId, on)));
        return;
      }
      setDesk(saveDesk(withStarToggle(desk, mode, catalog.id, currentId, nextOn)));
    } catch (e) {
      setDetailError(e.message);
    }
  }

  async function saveNotes() {
    if (!current || !readyRef.current) return;
    if (draftRef.current === loadedNote.current) return;
    const text = draftRef.current;
    setNoteState("Saving…");
    try {
      if (mode === "upcoming") {
        const data = await apiPost(
          `/api/sales/upcoming/${encodeURIComponent(catalog.id)}/lots/${encodeURIComponent(current.hip)}`,
          { notes: text },
        );
        const notes = data.lot?.notes || "";
        setLots((rows) => rows.map((lot) => (String(lot.hip) === String(current.hip) ? { ...lot, notes } : lot)));
        setDetail((prev) => (prev ? { ...prev, lot: { ...prev.lot, notes } } : prev));
        loadedNote.current = notes;
      } else {
        const next = { ...desk, notes: { ...desk.notes, [currentId]: text } };
        setDesk(saveDesk(next));
        loadedNote.current = text;
      }
      setNoteState("Saved");
    } catch (e) {
      setNoteState(e.message);
    }
  }

  const active = (desk.clients || []).find((client) => client.id === activeClient) || null;

  return (
    <div className={`sales-root${catalog ? " workspace" : ""}`}>
      {catalog ? (
        <div className="maneuver">
          <button className="ghost" type="button" onClick={() => position > 0 && setCurrentId(navId(mode, filtered[position - 1]))} disabled={position <= 0}>
            ←
          </button>
          <label className="hip-jump">
            Hip
            <input
              value={hipInput}
              onChange={(e) => setHipInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") jumpToHip(hipInput);
              }}
            />
          </label>
          <button
            className="ghost"
            type="button"
            onClick={() => position >= 0 && position < filtered.length - 1 && setCurrentId(navId(mode, filtered[position + 1]))}
            disabled={position < 0 || position >= filtered.length - 1}
          >
            →
          </button>
          <div className="maneuver-title">{saleHeading(catalog.title, catalog.year)}</div>
          <span className="maneuver-count">
            {filtered.length ? `${position + 1} / ${filtered.length}` : "0"}
          </span>
          <button className="ghost" type="button" onClick={() => setCatalog(null)}>Sales</button>
        </div>
      ) : (
        <div className="sales-entry">
          <div className="mode-row">
            <button className={pastOpen ? "primary" : "ghost"} type="button" onClick={togglePastSection}>
              Past results
            </button>
            <button className={upcomingOpen ? "primary" : "ghost"} type="button" onClick={toggleUpcomingSection}>
              Upcoming sales
            </button>
          </div>
          {listError ? <p className="error">{listError}</p> : null}
          {pastOpen ? (
            <div className="panel">
              <h4>PAST RESULTS</h4>
              <h4 style={{ marginTop: 8 }}>YEAR</h4>
              <select value={year} onChange={(e) => setYear(e.target.value)}>
                {years.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <h4 style={{ marginTop: 12 }}>SALES</h4>
              {loadingPast ? <p className="empty">Loading sales…</p> : pastCatalogs.map((item) => (
                <button key={item.id} className="ghost catalog-btn" type="button" onClick={() => openCatalog(item, "past")}>
                  {item.title}
                </button>
              ))}
            </div>
          ) : null}
          {upcomingOpen ? (
            <div className="panel" style={{ marginTop: pastOpen ? 12 : 0 }}>
              <h4>UPCOMING SALES</h4>
              {loadingUpcoming ? <p className="empty">Loading sales…</p> : upcomingCatalogs.length === 0 ? (
                <p className="empty">No upcoming catalogs yet. Import a sale into Upcoming Sales and run the analyzer.</p>
              ) : upcomingCatalogs.map((item) => (
                <button key={item.id} className="ghost catalog-btn" type="button" onClick={() => openCatalog(item, "upcoming")}>
                  {item.title}
                  <span>{item.hips} hips</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}

      {catalog ? (
        <div className="sales-columns">
          <div className="sales-col sales-col-pedigree">
            <div className="panel">
              <h4>PEDIGREE</h4>
              {ready ? <PedigreeChart tree={detail.pedigree} showSubject={false} hrefFor={hrefFor} /> : <p className="empty">Loading pedigree…</p>}
            </div>
            <div className="panel family-panel">
              <h4>FEMALE FAMILY</h4>
              {ready ? <FemaleFamily family={detail.female_family} hrefFor={hrefFor} /> : <p className="empty">Loading female family…</p>}
            </div>
            <div className="panel">
              <h4>PHYSICAL</h4>
              <div className="blank-value" aria-label="Physical" />
            </div>
            <div className="panel">
              <h4>NOTES</h4>
              <textarea
                className="note-box"
                value={noteDraft}
                onChange={(e) => { setNoteDraft(e.target.value); setNoteState(""); }}
                onBlur={saveNotes}
                placeholder="Add a note"
                disabled={!current}
              />
              {noteState ? <p className="note-state">{noteState}</p> : null}
            </div>
          </div>

          <div className="sales-col sales-col-info">
            {listError ? <p className="error">{listError}</p> : null}
            {loadingList ? <p className="empty">Loading catalog…</p> : null}
            {!loadingList && !current ? <p className="empty">No hips match this list.</p> : null}
            {current ? (
              <>
                <div className="panel sale-identity">
                  <h2>
                    <Link href={hrefFor(current.name)}>{current.name || current.raw_name || "Unnamed"}</Link>
                  </h2>
                  <div className="sale-meta">
                    <div><span className="meta-label">Color</span><b>{colorWord(current) || "—"}</b></div>
                    <div><span className="meta-label">Sex</span><b>{sexWord(current) || "—"}</b></div>
                    <div><span className="meta-label">Foaled</span><b className={blank(current.birth_date) ? "meta-fit" : undefined}>{blank(current.birth_date) || current.birth_year || "—"}</b></div>
                    <div>
                      <span className="meta-label">Consigned by</span>
                      <b className={(blank(current.consignor) || "").length > 14 ? "meta-fit" : undefined}>
                        {blank(current.consignor) || "—"}
                      </b>
                    </div>
                    <div><span className="meta-label">Hip</span><b>{current.hip || "—"}</b></div>
                    <div><span className="meta-label">Barn</span><b>{blank(current.barn) || "—"}</b></div>
                    {mode === "past" ? (
                      <div><span className="meta-label">Auction price</span><b className="money">{priceLabel(current)}</b></div>
                    ) : null}
                  </div>
                  {jumpError ? <p className="error">{jumpError}</p> : null}
                </div>

                {(!ready || projectionPanels(detail, current).showValue || projectionPanels(detail, current).showPrice) ? (
                  <div className="panel" data-panel="projected-value">
                    <h4>MARKET PROJECTION</h4>
                    {(!ready || projectionPanels(detail, current).showPrice) ? (
                      <div className="pv-price" data-meta="projected-price">
                        <span className="pv-label">
                          Projected Price
                          {ready && detail?.expected_market?.sales_model?.in_sample ? (
                            <span className="pv-badge" title="This sale is in the model's training data, so the figure is a backtest, not a forecast.">Backtest</span>
                          ) : null}
                        </span>
                        <b className="money">{ready ? projectedPriceLabel(detail) : "…"}</b>
                      </div>
                    ) : null}
                    {ready && Number.isFinite(Number(detail?.market_prediction?.boom_pct)) && detail?.market_prediction?.boom_pct != null ? (
                      // Boom %: chance of a graded / Group stakes win; ~1.2% is average.
                      <div className="pv-price pv-boom">
                        <span className="pv-label">Boom</span>
                        <b>
                          {Number(detail.market_prediction.boom_pct).toFixed(1)}%
                          <span className="pv-boom-rel"> · {(Number(detail.market_prediction.boom_pct) / 1.2).toFixed(1)}× average</span>
                        </b>
                      </div>
                    ) : null}
                    {(!ready || projectionPanels(detail, current).showValue) ? (
                      <>
                      {ready ? <span className="pv-label pv-section">Projected Value</span> : null}
                      <ProjectedValue
                        valueProjector={ready ? detail?.expected_market?.value_projector : null}
                        lot={ready ? (detail?.lot || current) : current}
                        showSold={mode === "past"}
                      />
                      </>
                    ) : null}
                  </div>
                ) : null}

                <div className="panel">
                  <h4>SUCCESSFUL SIMILAR CROSSES</h4>
                  {detailError ? <p className="error">{detailError}</p> : null}
                  {loadingDetail && !ready ? <p className="empty">Loading crosses…</p> : null}
                  {ready && !(detail.similar_crosses || []).length ? (
                    <p className="empty">No similar successful crosses on file for this sire yet.</p>
                  ) : null}
                  {ready && (detail.similar_crosses || []).length ? (
                    <table>
                      <thead>
                        <tr>
                          <th>Horse</th>
                          <th>Class</th>
                          <th>Similarity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.similar_crosses.map((row, index) => (
                          <tr key={`${row.name}-${row.class}-${index}`}>
                            <td><Link href={hrefFor(row.name)}>{row.name}</Link></td>
                            <td>{row.class || "—"}</td>
                            <td>{row.similarity != null ? `${row.similarity}%` : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : null}
                </div>

                <div className="panel">
                  <h4>SIMILAR CROSSES AUCTION HISTORY</h4>
                  {ready && !(detail.auction_history || []).length ? (
                    <p className="empty">No auction history on file for these crosses yet.</p>
                  ) : null}
                  {ready && (detail.auction_history || []).length ? (
                    <table>
                      <thead>
                        <tr>
                          <th>Horse</th>
                          <th>Similarity</th>
                          <th>Sale</th>
                          <th>Price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.auction_history.map((row, index) => {
                          const key = `${row.name}-${row.sale}-${row.hip}-${index}`;
                          const open = openAuction === key;
                          return (
                            <Fragment key={key}>
                              <tr className="auction-row" role="button" tabIndex={0} onClick={() => setOpenAuction(open ? "" : key)}>
                                <td><Link href={hrefFor(row.name)} onClick={(e) => e.stopPropagation()}>{row.name}</Link></td>
                                <td>{row.similarity != null ? `${row.similarity}%` : "—"}</td>
                                <td>{saleHeading(row.sale, row.year)}</td>
                                <td className="money">{priceLabel(row)}</td>
                              </tr>
                              {open ? (
                                <tr className="auction-more">
                                  <td colSpan={4}>
                                    Hip {row.hip || "—"}
                                    {row.is_rna ? " · RNA" : ""}
                                    {row.purchaser ? ` · Purchaser ${row.purchaser}` : ""}
                                  </td>
                                </tr>
                              ) : null}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>

          <aside className={`sales-rail${railOpen ? " open" : ""}`}>
            <button
              className={`rail-btn${starred ? " on" : ""}`}
              type="button"
              onClick={toggleStar}
              title={starred ? "Unstar this hip" : "Star this hip"}
            >
              {starred ? "★" : "☆"}
            </button>
            <button className="rail-btn" type="button" onClick={dismissCurrent} title="Dismiss">✕</button>
            <button className="rail-btn" type="button" onClick={() => setRailOpen((open) => !open)} title={railOpen ? "Collapse" : "Expand"}>
              {railOpen ? "»" : "«"}
            </button>
            {railOpen ? (
              <div className="rail-body">
                <h4>CLIENTS</h4>
                {(desk.clients || []).map((client) => (
                  <button
                    key={client.id}
                    className={activeClient === client.id ? "primary" : "ghost"}
                    type="button"
                    onClick={() => selectClient(client)}
                  >
                    {client.name}
                  </button>
                ))}
                {active ? (
                  <div className="client-prefs">
                    <label>
                      Name
                      <input value={active.name} onChange={(e) => updateClient(active.id, { name: e.target.value })} />
                    </label>
                    <label>
                      Sex
                      <select value={active.sex || ""} onChange={(e) => { updateClient(active.id, { sex: e.target.value }); setSex(e.target.value); }}>
                        <option value="">Any</option>
                        <option value="C">Colt</option>
                        <option value="F">Filly</option>
                        <option value="G">Gelding</option>
                        <option value="M">Mare</option>
                      </select>
                    </label>
                    <label>
                      Color
                      <input value={active.color || ""} onChange={(e) => { updateClient(active.id, { color: e.target.value }); setColor(e.target.value); }} />
                    </label>
                    <label>
                      Price ceiling
                      <input value={active.maxPrice || ""} onChange={(e) => { updateClient(active.id, { maxPrice: e.target.value }); setMaxPrice(e.target.value); }} />
                    </label>
                    <label>
                      Height
                      <input value={active.height || ""} onChange={(e) => { updateClient(active.id, { height: e.target.value }); setHeight(e.target.value); }} placeholder="16.1" />
                    </label>
                  </div>
                ) : null}

                <h4>FILTER</h4>
                <p className="filter-count">{filtered.length} / {lots.length} hips</p>
                <label>
                  Stallion
                  <input
                    className="filter-sire-search"
                    type="search"
                    value={sireQuery}
                    onChange={(e) => setSireQuery(e.target.value)}
                    placeholder="Type a stallion name…"
                    aria-label="Filter stallion list"
                  />
                  <div className="filter-sire-list" role="group" aria-label="Stallions in this catalog">
                    {visibleSireOptions.length ? visibleSireOptions.map((row) => (
                      <label key={row.name} className="filter-check">
                        <input
                          type="checkbox"
                          checked={selectedSires.includes(row.name)}
                          onChange={() => toggleSire(row.name)}
                        />
                        <span>{row.name}</span>
                        <em>{row.count}</em>
                      </label>
                    )) : (
                      <span className="empty" style={{ padding: 8 }}>
                        {sireOptions.length ? "No stallions match that name" : "No sires in catalog"}
                      </span>
                    )}
                  </div>
                  {selectedSires.length ? (
                    <p className="filter-note">
                      {selectedSires.length} selected
                      {sireQuery.trim() ? ` · showing ${visibleSireOptions.length} of ${sireOptions.length}` : ""}
                    </p>
                  ) : sireQuery.trim() ? (
                    <p className="filter-note">Showing {visibleSireOptions.length} of {sireOptions.length}</p>
                  ) : null}
                  {selectedSires.length ? (
                    <button className="ghost filter-clear" type="button" onClick={() => setSelectedSires([])}>
                      Clear stallions
                    </button>
                  ) : null}
                </label>
                <label>
                  Sex
                  <select value={sex} onChange={(e) => applyFilter({ sex: e.target.value })}>
                    <option value="">Any</option>
                    {sexOptions.map((opt) => (
                      <option key={opt.letter} value={opt.letter}>{opt.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Price range
                  <div className="filter-price-ranges" role="group" aria-label="Price ranges">
                    {PRICE_RANGES.map((range) => (
                      <label key={range.id} className="filter-check">
                        <input
                          type="checkbox"
                          checked={priceRanges.includes(range.id)}
                          onChange={() => togglePriceRange(range.id)}
                        />
                        <span>{range.label}</span>
                      </label>
                    ))}
                  </div>
                  {priceProxyNote ? <span className="filter-note">{priceProxyNote}</span> : null}
                  {priceRanges.length ? (
                    <button className="ghost filter-clear" type="button" onClick={() => setPriceRanges([])}>
                      Clear price ranges
                    </button>
                  ) : null}
                </label>
                <label>
                  Color
                  <input value={color} onChange={(e) => applyFilter({ color: e.target.value })} />
                </label>
                <label>
                  Height
                  <input value={height} onChange={(e) => applyFilter({ height: e.target.value })} placeholder="16.1" />
                </label>
                <button
                  className={onlyStarred ? "primary" : "ghost"}
                  type="button"
                  onClick={viewStarred}
                >
                  View Starred Horses{starredCount ? ` (${starredCount})` : ""}
                </button>
                <button className="ghost" type="button" onClick={viewFull}>View full</button>
                <button className={onlyDismissed ? "primary" : "ghost"} type="button" onClick={viewDismissed}>X&apos;d list</button>
                {onlyStarred && !filtered.length ? (
                  <p className="filter-note">No starred hips in this catalog yet. Tap ★ on a hip to add it.</p>
                ) : null}
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}
    </div>
  );
}

export default function SalesPageSuspense() {
  return (
    <Suspense fallback={<p className="empty">Loading sales…</p>}>
      <SalesPage />
    </Suspense>
  );
}
