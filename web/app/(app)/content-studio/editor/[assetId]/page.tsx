"use client";

import type { ContentAsset } from "@marketingos/api-client";
import { ArrowDown, ArrowUp, ImagePlus, Redo2, Square, Trash2, Type, Undo2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, cn, Field, Input, Notice, PageHeader, Panel, Select, Spinner, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiQuery } from "@/lib/hooks";

interface Layer {
  id: string; type: "text" | "image" | "rect";
  x: number; y: number; w: number; h: number;
  text?: string; fontSize?: number; fontWeight?: number; color?: string; align?: "start" | "middle" | "end";
  fill?: string; radius?: number; src?: string;
}
interface Design { size: string; width: number; height: number; background: string; layers: Layer[] }

const SIZES: Record<string, [number, number, string]> = {
  square: [1080, 1080, "Feed 1:1"], portrait: [1080, 1350, "Feed 4:5"], story: [1080, 1920, "Story / Reel 9:16"], landscape: [1200, 628, "Link ad 1.91:1"],
};
const uid = () => Math.random().toString(36).slice(2, 9);

function initialDesign(asset: ContentAsset, colors: string[]): Design {
  const [w, h] = SIZES[asset.brief?.dimensions ?? "square"] ?? SIZES.square;
  const b = asset.body;
  const headline = b.hook ?? b.headline ?? b.title ?? b.slides?.[0]?.headline ?? b.hero?.headline ?? asset.title;
  const sub = (b.caption ?? b.primary_text ?? b.slides?.[0]?.body ?? "").split("\n").filter(Boolean)[1] ?? "";
  const cta = b.cta ?? b.hero?.cta ?? "";
  const bg = colors[0] ?? "#172033";
  const accent = colors[1] ?? "#E8A317";
  const layers: Layer[] = [];
  if (b.media?.[0]?.url) layers.push({ id: uid(), type: "image", x: 0, y: 0, w, h: Math.round(h * 0.55), src: b.media[0].url });
  layers.push({ id: uid(), type: "text", x: 80, y: Math.round(h * 0.62), w: w - 160, h: 200, text: headline, fontSize: 64, fontWeight: 800, color: "#ffffff", align: "start" });
  if (sub) layers.push({ id: uid(), type: "text", x: 80, y: Math.round(h * 0.62) + 190, w: w - 160, h: 120, text: sub, fontSize: 34, fontWeight: 400, color: "#ffffff", align: "start" });
  if (cta) {
    layers.push({ id: uid(), type: "rect", x: 80, y: h - 180, w: 420, h: 96, fill: accent, radius: 48 });
    layers.push({ id: uid(), type: "text", x: 80, y: h - 152, w: 420, h: 60, text: cta, fontSize: 36, fontWeight: 700, color: "#172033", align: "middle" });
  }
  return { size: asset.brief?.dimensions ?? "square", width: w, height: h, background: bg, layers };
}

function wrap(text: string, width: number, fontSize: number): string[] {
  const max = Math.max(4, Math.floor(width / (fontSize * 0.55)));
  const lines: string[] = [];
  for (const para of text.split("\n")) {
    let line = "";
    for (const word of para.split(" ")) {
      if ((line + " " + word).trim().length > max) { if (line) lines.push(line); line = word; } else line = `${line} ${word}`.trim();
    }
    lines.push(line);
  }
  return lines;
}

function LayerShape({ l, selected, onPointerDown }: { l: Layer; selected: boolean; onPointerDown: (e: React.PointerEvent) => void }) {
  const outline = selected ? <rect x={l.x - 4} y={l.y - 4} width={l.w + 8} height={l.h + 8} fill="none" stroke="#2f5d9e" strokeWidth={4} strokeDasharray="12 8" /> : null;
  if (l.type === "rect") {
    return <g onPointerDown={onPointerDown} className="cursor-move"><rect x={l.x} y={l.y} width={l.w} height={l.h} rx={l.radius ?? 0} fill={l.fill} />{outline}</g>;
  }
  if (l.type === "image") {
    return <g onPointerDown={onPointerDown} className="cursor-move"><image href={l.src} x={l.x} y={l.y} width={l.w} height={l.h} preserveAspectRatio="xMidYMid slice" crossOrigin="anonymous" />{outline}</g>;
  }
  const fs = l.fontSize ?? 40;
  const anchorX = l.align === "middle" ? l.x + l.w / 2 : l.align === "end" ? l.x + l.w : l.x;
  return (
    <g onPointerDown={onPointerDown} className="cursor-move">
      <rect x={l.x} y={l.y} width={l.w} height={l.h} fill="transparent" />
      <text x={anchorX} y={l.y + fs} fontSize={fs} fontWeight={l.fontWeight} fill={l.color} textAnchor={l.align} fontFamily="Schibsted Grotesk, sans-serif">
        {wrap(l.text ?? "", l.w, fs).map((line, i) => <tspan key={i} x={anchorX} dy={i === 0 ? 0 : fs * 1.15}>{line}</tspan>)}
      </text>
      {outline}
    </g>
  );
}

export default function CreativeEditorPage() {
  const { assetId } = useParams<{ assetId: string }>();
  const { data: asset, refetch } = useApiQuery<ContentAsset>(`/content/${assetId}`);
  const { data: brands } = useApiQuery<{ id: string; colors: string[]; logo_url: string | null }[]>("/brands");
  const { data: media } = useApiQuery<{ id: string; url: string; kind: string }[]>("/media", { kind: "image" });
  const [history, setHistory] = useState<Design[]>([]);
  const [index, setIndex] = useState(-1);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const brand = brands?.find((b) => b.id === asset?.brand_id) ?? brands?.[0];
  const palette = [...(brand?.colors ?? []), "#ffffff", "#172033", "#E8A317", "#1E7A57"];
  const design = history[index];

  useEffect(() => {
    if (asset && index === -1) {
      setHistory([asset.body.design ?? initialDesign(asset, brand?.colors ?? [])]);
      setIndex(0);
    }
  }, [asset, brand, index]);

  const commit = useCallback((next: Design) => {
    setHistory((h) => [...h.slice(0, index + 1), next].slice(-60));
    setIndex((i) => Math.min(i + 1, 59));
  }, [index]);
  const update = (id: string, patch: Partial<Layer>) => commit({ ...design, layers: design.layers.map((l) => (l.id === id ? { ...l, ...patch } : l)) });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); setIndex((i) => (e.shiftKey ? Math.min(i + 1, history.length - 1) : Math.max(i - 1, 0))); }
      if ((e.key === "Delete" || e.key === "Backspace") && selected && !(e.target as HTMLElement).closest("input,textarea")) {
        commit({ ...design, layers: design.layers.filter((l) => l.id !== selected) }); setSelected(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [history.length, selected, design, commit]);

  if (!asset || !design) return <Spinner />;
  const layer = design.layers.find((l) => l.id === selected);

  const toCanvas = (e: React.PointerEvent) => {
    const pt = svgRef.current!.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svgRef.current!.getScreenCTM()!.inverse());
  };
  const resize = (size: string) => {
    const [w, h] = SIZES[size];
    const sx = w / design.width, sy = h / design.height;
    commit({ ...design, size, width: w, height: h, layers: design.layers.map((l) => ({ ...l, x: Math.round(l.x * sx), y: Math.round(l.y * sy), w: Math.round(l.w * sx), h: Math.round(l.h * sy) })) });
  };
  const move = (dir: -1 | 1) => {
    const i = design.layers.findIndex((l) => l.id === selected);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= design.layers.length) return;
    const layers = [...design.layers];
    [layers[i], layers[j]] = [layers[j], layers[i]];
    commit({ ...design, layers });
  };
  const add = (type: Layer["type"]) => {
    const l: Layer = type === "text"
      ? { id: uid(), type, x: 100, y: 100, w: design.width - 200, h: 120, text: "New text", fontSize: 48, fontWeight: 700, color: "#ffffff", align: "start" }
      : type === "rect" ? { id: uid(), type, x: 100, y: 100, w: 300, h: 160, fill: palette[1] ?? "#E8A317", radius: 16 }
      : { id: uid(), type, x: 0, y: 0, w: design.width, h: Math.round(design.height / 2), src: media?.[0]?.url ?? brand?.logo_url ?? "" };
    commit({ ...design, layers: [...design.layers, l] });
    setSelected(l.id);
  };
  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/content/${asset.id}`, { body: { ...asset.body, design }, note: "Edited in the creative editor" });
      await refetch();
      setMessage({ tone: "success", text: "Saved as a new version." });
    } catch (e) { setMessage({ tone: "error", text: errorMessage(e) }); } finally { setSaving(false); }
  };
  const exportPng = () => {
    const svg = svgRef.current!.cloneNode(true) as SVGSVGElement;
    svg.querySelectorAll("[stroke-dasharray='12 8']").forEach((n) => n.remove());
    const data = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = design.width; canvas.height = design.height;
      canvas.getContext("2d")!.drawImage(img, 0, 0);
      try {
        const a = document.createElement("a");
        a.href = canvas.toDataURL("image/png");
        a.download = `${asset.title.slice(0, 40)}-${design.size}.png`;
        a.click();
      } catch {
        setMessage({ tone: "error", text: "This design uses an image the browser won't export. Replace it with one from your media library." });
      }
    };
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(data)}`;
  };

  return (
    <>
      <PageHeader title="Creative editor" description={<Link href="/content-studio" className="underline-offset-2 hover:underline">{asset.title}</Link>}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => setIndex(Math.max(0, index - 1))} disabled={index <= 0} aria-label="Undo"><Undo2 className="size-4" /></Button>
            <Button size="sm" variant="ghost" onClick={() => setIndex(Math.min(history.length - 1, index + 1))} disabled={index >= history.length - 1} aria-label="Redo"><Redo2 className="size-4" /></Button>
            <Select aria-label="Size" className="w-44" value={design.size} onChange={(e) => resize(e.target.value)} options={Object.entries(SIZES).map(([k, [, , l]]) => ({ value: k, label: l }))} />
            <Button onClick={exportPng}>Export PNG</Button>
            <Button variant="primary" loading={saving} onClick={save}>Save draft</Button>
          </>
        } />
      {message && <Notice tone={message.tone} className="mb-4">{message.text}</Notice>}
      <div className="grid gap-5 lg:grid-cols-[200px_1fr_280px]">
        <Panel title="Layers">
          <div className="mb-3 flex gap-1">
            <Button size="sm" onClick={() => add("text")} aria-label="Add text"><Type className="size-3.5" /></Button>
            <Button size="sm" onClick={() => add("rect")} aria-label="Add shape"><Square className="size-3.5" /></Button>
            <Button size="sm" onClick={() => add("image")} aria-label="Add image"><ImagePlus className="size-3.5" /></Button>
          </div>
          <ul className="space-y-1">
            {[...design.layers].reverse().map((l) => (
              <li key={l.id}>
                <button onClick={() => setSelected(l.id)} className={cn("w-full truncate rounded px-2 py-1 text-left text-[13px]", selected === l.id ? "bg-ink text-white" : "hover:bg-sunk")}>
                  {l.type === "text" ? `Text: ${l.text}` : l.type === "image" ? "Image" : "Shape"}
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        <div className="flex items-start justify-center rounded-[var(--radius-panel)] border border-rule bg-sunk p-4">
          <svg ref={svgRef} xmlns="http://www.w3.org/2000/svg" viewBox={`0 0 ${design.width} ${design.height}`} width={design.width} height={design.height}
            className="h-auto max-h-[70vh] w-full max-w-[560px] touch-none bg-white shadow" role="img" aria-label="Design canvas"
            onPointerMove={(e) => {
              if (!drag.current) return;
              const p = toCanvas(e);
              setHistory((h) => h.map((d, i) => (i === index ? { ...d, layers: d.layers.map((l) => (l.id === drag.current!.id ? { ...l, x: Math.round(p.x - drag.current!.dx), y: Math.round(p.y - drag.current!.dy) } : l)) } : d)));
            }}
            onPointerUp={() => { if (drag.current) { commit(history[index]); drag.current = null; } }}
            onPointerDown={(e) => { if (e.target === svgRef.current || (e.target as Element).getAttribute("data-bg")) setSelected(null); }}>
            <rect data-bg="1" width="100%" height="100%" fill={design.background} />
            {design.layers.map((l) => (
              <LayerShape key={l.id} l={l} selected={l.id === selected} onPointerDown={(e) => {
                e.stopPropagation();
                setSelected(l.id);
                const p = toCanvas(e);
                drag.current = { id: l.id, dx: p.x - l.x, dy: p.y - l.y };
              }} />
            ))}
          </svg>
        </div>
        <Panel title={layer ? "Selected layer" : "Canvas"}>
          {!layer ? (
            <div className="space-y-3">
              <p className="text-[13px] text-muted">Background</p>
              <div className="flex flex-wrap gap-1.5">{palette.map((c) => <button key={c} aria-label={`Background ${c}`} onClick={() => commit({ ...design, background: c })} className={cn("size-7 rounded border", design.background === c ? "border-ink ring-2 ring-ink/30" : "border-rule")} style={{ background: c }} />)}</div>
              <p className="text-xs text-muted">Click a layer to edit it. Drag to move. Ctrl/⌘+Z undoes.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {layer.type === "text" && (
                <>
                  <Field label="Text"><Textarea rows={3} value={layer.text} onChange={(e) => update(layer.id, { text: e.target.value })} /></Field>
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="Size"><Input type="number" value={layer.fontSize} onChange={(e) => update(layer.id, { fontSize: Number(e.target.value) })} /></Field>
                    <Field label="Weight"><Select value={String(layer.fontWeight)} onChange={(e) => update(layer.id, { fontWeight: Number(e.target.value) })} options={[400, 500, 700, 800, 900].map((v) => ({ value: String(v), label: String(v) }))} /></Field>
                  </div>
                  <Field label="Align"><Select value={layer.align ?? "start"} onChange={(e) => update(layer.id, { align: e.target.value as Layer["align"] })} options={[{ value: "start", label: "Left" }, { value: "middle", label: "Centre" }, { value: "end", label: "Right" }]} /></Field>
                </>
              )}
              {layer.type === "image" && (
                <Field label="Image">
                  <div className="grid grid-cols-3 gap-1.5">
                    {(media ?? []).slice(0, 12).map((m) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <button key={m.id} onClick={() => update(layer.id, { src: m.url })} className={cn("overflow-hidden rounded border", layer.src === m.url ? "border-ink" : "border-rule")}><img src={m.url} alt="" className="aspect-square object-cover" /></button>
                    ))}
                    {brand?.logo_url && <button onClick={() => update(layer.id, { src: brand.logo_url! })} className="rounded border border-rule p-1 text-[11px]">Logo</button>}
                  </div>
                  {!media?.length && <p className="text-xs text-muted">Upload or generate images in the Content studio first.</p>}
                </Field>
              )}
              {(layer.type === "text" || layer.type === "rect") && (
                <div>
                  <p className="mb-1.5 text-[13px] font-medium text-ink-2">Colour</p>
                  <div className="flex flex-wrap gap-1.5">{palette.map((c) => (
                    <button key={c} aria-label={`Colour ${c}`} onClick={() => update(layer.id, layer.type === "text" ? { color: c } : { fill: c })}
                      className={cn("size-7 rounded border", (layer.color ?? layer.fill) === c ? "border-ink ring-2 ring-ink/30" : "border-rule")} style={{ background: c }} />))}
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                {(["x", "y", "w", "h"] as const).map((k) => (
                  <Field key={k} label={{ x: "X", y: "Y", w: "Width", h: "Height" }[k]}><Input type="number" value={layer[k]} onChange={(e) => update(layer.id, { [k]: Number(e.target.value) })} /></Field>
                ))}
              </div>
              <div className="flex gap-1">
                <Button size="sm" onClick={() => move(1)} aria-label="Bring forward"><ArrowUp className="size-3.5" /></Button>
                <Button size="sm" onClick={() => move(-1)} aria-label="Send backward"><ArrowDown className="size-3.5" /></Button>
                <Button size="sm" variant="danger" onClick={() => { commit({ ...design, layers: design.layers.filter((l) => l.id !== layer.id) }); setSelected(null); }}><Trash2 className="size-3.5" /> Delete</Button>
              </div>
            </div>
          )}
          {asset.versions && (
            <div className="mt-5 border-t border-rule pt-3">
              <p className="mb-1.5 text-xs font-medium text-muted">Version history</p>
              <ul className="space-y-1 text-[13px]">
                {asset.versions.slice(-6).reverse().map((v) => (
                  <li key={v.version} className="flex justify-between gap-2">
                    <span>v{v.version} · {v.label ?? v.note ?? v.source}</span>
                    {v.body.design && v.version !== asset.current_version && (
                      <button className="text-xs underline" onClick={() => commit(v.body.design)}>Load</button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
