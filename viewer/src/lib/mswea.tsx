/**
 * trajectory fork: sessions translated from mini-swe-agent (scripts/mswea_to_pi.py).
 *
 * `data/mswea-projects.json` lists the projects whose sessions came from mini-swe-agent, and per session its task,
 * model, and verifier result. The static site shows these sessions on their own page, marks each of their session
 * pages, and shows each result as a badge, so they are never mistaken for native pi runs.
 */
import { useEffect, useState } from "react";
import { readBasePath, withBase } from "./base";

export type Verdict = "pass" | "fail" | "unscored";
export interface MsweaSession {
	task: string;
	model: string;
	verdict: Verdict;
	/** Why there is no score, or how a score was decided (e.g. "API error", "adjudicated"). */
	detail?: string;
}
export interface MsweaData {
	projects: Set<string>;
	sessions: Map<string, MsweaSession>;
}
type RawData = { projects?: string[]; sessions?: Record<string, MsweaSession> };

let cached: Promise<MsweaData> | undefined;

export function msweaData(): Promise<MsweaData> {
	cached ??= fetch(withBase(readBasePath(), "data/mswea-projects.json"))
		.then(async (r): Promise<RawData> => (r.ok ? ((await r.json()) as RawData) : {}))
		.catch((): RawData => ({}))
		.then((raw) => ({ projects: new Set(raw.projects ?? []), sessions: new Map(Object.entries(raw.sessions ?? {})) }));
	return cached;
}

export function useMsweaData(): MsweaData | undefined {
	const [data, setData] = useState<MsweaData>();
	useEffect(() => {
		let live = true;
		void msweaData().then((d) => live && setData(d));
		return () => {
			live = false;
		};
	}, []);
	return data;
}

export function useIsMswea(project: string | undefined): boolean {
	const data = useMsweaData();
	return !!project && !!data?.projects.has(project);
}

export const VERDICT_LABELS: Record<Verdict, string> = { pass: "Passed", fail: "Failed", unscored: "Unscored" };

const VERDICT_STYLE: Record<Verdict, string> = {
	pass: "border-[#16a34a]/50 bg-[#16a34a]/10 text-[#15803d] dark:text-[#4ade80]",
	fail: "border-red/40 bg-red-soft text-red",
	unscored: "border-line bg-soft text-muted",
};

/** The verifier's result for a translated session, as a small badge; nothing for other sessions. */
export function VerdictBadge({ id, large = false }: { id: string; large?: boolean }) {
	const data = useMsweaData();
	const s = data?.sessions.get(id);
	if (!s) return null;
	const mark = s.verdict === "pass" ? "✓" : s.verdict === "fail" ? "✗" : "–";
	const text = s.verdict === "unscored" && s.detail ? `Unscored · ${s.detail}` : VERDICT_LABELS[s.verdict];
	return (
		<span
			className={`inline-flex shrink-0 items-center gap-1 rounded-sm border font-medium ${VERDICT_STYLE[s.verdict]} ${
				large ? "h-6 px-2 text-[12.5px]" : "h-5 px-1.5 text-[11.5px]"
			}`}
			title={`Verifier result: ${text}${s.verdict !== "unscored" && s.detail ? ` (${s.detail})` : ""}`}
			data-verdict={s.verdict}
		>
			<span aria-hidden="true">{mark}</span>
			{text}
		</span>
	);
}

export function MsweaNotice({ compact = false }: { compact?: boolean }) {
	return (
		<div
			className="mt-3 rounded-md border border-line bg-soft px-3.5 py-2.5 text-[13px] leading-[1.55] text-muted"
			data-mswea-notice=""
		>
			<span className="mr-1.5 inline-flex items-center rounded-sm bg-ink px-1.5 py-[1px] text-[11px] font-medium tracking-wide text-page">
				mini-swe-agent
			</span>
			{compact ? (
				<>
					This trajectory was recorded by <span className="text-ink">mini-swe-agent</span> (bash-only harness), not by pi,
					and translated into pi's session format for display. The badge is the hidden verifier's result.
				</>
			) : (
				<>
					These trajectories were recorded by <span className="text-ink">mini-swe-agent</span>, a bash-only agent harness, not by
					pi, and translated into pi's session format for display. Each badge is the hidden verifier's result; "Unscored" means
					the run ended without a gradable submission (API failure, output limit, format errors, grader error), which is not
					counted as a wrong answer. Red shell steps are commands that exited non-zero (usually failing tests while the model
					works), not API failures; failed or superseded model requests (e.g. gateway timeouts) appear as red model calls.
					Durations are measured by the client; there is no time-to-first-token because requests were not streamed. Cached
					input is shown as the provider reported it (most 360 routes report no cache hits). Costs are estimated from the
					provider's list prices (cache hits at 1/10 of the input price; CNY converted to USD at about ¥7.1/$).
				</>
			)}
		</div>
	);
}
