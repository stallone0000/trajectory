/**
 * Static-site transport for the pika web UI (trajectory fork).
 *
 * The upstream UI talks to a pika server. This build is published as plain static files, so
 * every `api/public/v1/*` request is answered here, in the browser, from JSON snapshots that
 * `scripts/pika_snapshot.py` wrote under `data/`. Filtering, pagination, entry ranges, and
 * search are emulated with the server's response shapes; everything else is a 404.
 */
import { withBase } from "./base";

export const STATIC_SITE = true;

type Json = Record<string, unknown>;
type SessionItem = Json & { id: string; project?: string; device?: string; models?: string[]; parentSessionId?: string; startedAt?: string; lastAt?: string };
type EntryItem = Json & { seq: number };
interface SearchDoc { seq: number; entryId?: string; kind: string; at?: string; text: string }
interface SearchSession { sessionId: string; sessionTitle: string; project?: string; lastAt?: string; docs: SearchDoc[] }

const cache = new Map<string, Promise<unknown>>();

function json(body: unknown, status = 200): Response {
	return new Response(status === 204 ? null : JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

const notFound = () => json({ error: "not_found" }, 404);

function page<T>(items: T[], params: URLSearchParams, defaultLimit = 50): { items: T[]; nextCursor: string | null } {
	const offset = Math.max(0, Number(params.get("cursor") ?? 0) || 0);
	const limit = Math.max(1, Number(params.get("limit") ?? defaultLimit) || defaultLimit);
	const slice = items.slice(offset, offset + limit);
	return { items: slice, nextCursor: offset + limit < items.length ? String(offset + limit) : null };
}

export function createStaticFetch(base: string): typeof fetch {
	const dataUrl = (rel: string) => withBase(base, `data/${rel}`);

	function load<T>(rel: string): Promise<T | undefined> {
		let hit = cache.get(rel);
		if (!hit) {
			hit = fetch(dataUrl(rel)).then(async (r) => (r.ok ? r.json() : undefined)).catch(() => undefined);
			cache.set(rel, hit);
		}
		return hit as Promise<T | undefined>;
	}

	async function file(rel: string): Promise<Response> {
		const body = await load(rel);
		return body === undefined ? notFound() : json(body);
	}

	async function sessions(params: URLSearchParams): Promise<Response> {
		const all = (await load<{ items: SessionItem[] }>("sessions.json"))?.items ?? [];
		const ids = new Set(all.map((s) => s.id));
		const project = params.get("project");
		const device = params.get("device");
		const model = params.get("model");
		const from = params.get("from");
		const to = params.get("to");
		const root = params.get("root") === "true";
		// trajectory fork: sessions translated from mini-swe-agent live on their own page (`source=mswea`);
		// every other list shows only native pi sessions.
		const mswea = new Set((await load<{ projects: string[] }>("mswea-projects.json"))?.projects ?? []);
		const wantMswea = params.get("source") === "mswea";
		const items = all.filter((s) => {
			if (mswea.has(s.project ?? "") !== wantMswea) return false;
			if (project && s.project !== project) return false;
			if (device && s.device !== device) return false;
			if (model && !(s.models ?? []).includes(model)) return false;
			if (root && s.parentSessionId && ids.has(s.parentSessionId)) return false;
			if (from && (s.lastAt ?? "") < from) return false;
			if (to && (s.startedAt ?? "") > `${to}T23:59:59.999Z`) return false;
			return true;
		});
		return json(page(items, params));
	}

	async function entries(id: string, params: URLSearchParams): Promise<Response> {
		const all = (await load<{ items: EntryItem[] }>(`s/${id}/entries.json`))?.items;
		if (!all) return notFound();
		const from = params.has("from") ? Number(params.get("from")) : -Infinity;
		const to = params.has("to") ? Number(params.get("to")) : Infinity;
		const limit = params.has("limit") ? Number(params.get("limit")) : 200;
		return json({ items: all.filter((e) => e.seq >= from && e.seq <= to).slice(0, limit) });
	}

	async function search(params: URLSearchParams): Promise<Response> {
		const q = (params.get("q") ?? "").trim().toLowerCase();
		const terms = q.split(/\s+/).filter(Boolean);
		const project = params.get("project");
		const limit = Number(params.get("limit") ?? 20) || 20;
		const data = (await load<{ sessions: SearchSession[] }>("search.json"))?.sessions ?? [];
		if (!terms.length) return json({ items: [], nextCursor: null });
		const items = [];
		for (const s of data) {
			if (project && s.project !== project) continue;
			const docs = s.docs.filter((d) => {
				const text = d.text.toLowerCase();
				return terms.every((t) => text.includes(t));
			});
			if (!docs.length) continue;
			const newest = [...docs].sort((a, b) => b.seq - a.seq);
			items.push({
				sessionId: s.sessionId,
				sessionTitle: s.sessionTitle,
				project: s.project,
				lastAt: s.lastAt,
				matches: docs.length,
				hits: newest.slice(0, 5).map((d) => ({
					sessionId: s.sessionId,
					sessionTitle: s.sessionTitle,
					seq: d.seq,
					entryId: d.entryId,
					kind: d.kind,
					snippet: snippet(d.text, terms),
					at: d.at,
				})),
			});
		}
		items.sort((a, b) => String(b.lastAt ?? "").localeCompare(String(a.lastAt ?? "")));
		return json({ items: items.slice(0, limit), nextCursor: null });
	}

	return async (input: RequestInfo | URL, init?: RequestInit) => {
		const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
		const url = new URL(raw, window.location.origin);
		let path = url.pathname;
		const prefix = base === "/" ? "/" : `${base}/`;
		if (path.startsWith(prefix)) path = path.slice(prefix.length);
		path = path.replace(/^\/+/, "");
		const params = url.searchParams;
		const method = (init?.method ?? "GET").toUpperCase();

		if (path === "api/health") return file("health.json");
		if (!path.startsWith("api/public/v1/")) return json({ error: "unauthorized" }, 401);
		const route = path.slice("api/public/v1/".length).split("/").map(decodeURIComponent);
		if (method !== "GET") return json(null, 204); // visitor-view and other beacons

		const [head, id, sub, seq, leaf] = route;
		switch (head) {
			case "facets":
				return file("facets.json");
			case "sessions":
				if (!id) return sessions(params);
				if (!sub) return file(`s/${id}/session.json`);
				if (sub === "trace" || sub === "tree") return file(`s/${id}/${sub}.json`);
				if (sub === "turns") {
					const turns = await load<{ items: unknown[] }>(`s/${id}/turns.json`);
					return turns ? json(page(turns.items, params)) : notFound();
				}
				if (sub === "updates") return file(`s/${id}/updates.json`);
				if (sub === "entries" && seq === undefined) return entries(id, params);
				if (sub === "entries" && leaf === "raw") return file(`s/${id}/raw/${seq}.json`);
				return notFound();
			case "statistics": {
				const days = params.get("days") ?? "30";
				return file(`stats/statistics_${days}_${params.get("excludeUnpublished") === "true"}.json`);
			}
			case "usage": {
				const days = params.get("days") ?? "30";
				const by = params.get("by") || "total";
				const interval = params.get("interval") || "default";
				return file(`stats/usage_${days}_${by}_${interval}_${params.get("excludeUnpublished") === "true"}.json`);
			}
			case "search":
				return search(params);
			default:
				return notFound();
		}
	};
}

function snippet(text: string, terms: string[]): string {
	const lower = text.toLowerCase();
	const at = Math.max(0, lower.indexOf(terms[0]));
	const start = Math.max(0, at - 60);
	const end = Math.min(text.length, at + 120);
	let out = text.slice(start, end);
	for (const term of terms) {
		const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
		out = out.replace(re, (m) => `<mark>${m}</mark>`);
	}
	return `${start > 0 ? "…" : ""}${out}${end < text.length ? "…" : ""}`;
}

/** The static copy of an entry's raw line, which the UI links to directly. */
export function staticRawUrl(base: string, sessionId: string, seq: number): string {
	return withBase(base, `data/s/${encodeURIComponent(sessionId)}/raw/${seq}.json`);
}
