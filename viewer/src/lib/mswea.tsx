/**
 * trajectory fork: sessions translated from mini-swe-agent (scripts/mswea_to_pi.py).
 *
 * `data/mswea-projects.json` lists the projects whose sessions came from mini-swe-agent; the static site shows them on
 * their own page and marks each of their session pages, so they are never mistaken for native pi runs.
 */
import { useEffect, useState } from "react";
import { readBasePath, withBase } from "./base";

let cached: Promise<Set<string>> | undefined;

export function msweaProjects(): Promise<Set<string>> {
	cached ??= fetch(withBase(readBasePath(), "data/mswea-projects.json"))
		.then(async (r) => new Set<string>(r.ok ? ((await r.json()) as { projects?: string[] }).projects ?? [] : []))
		.catch(() => new Set<string>());
	return cached;
}

export function useIsMswea(project: string | undefined): boolean {
	const [yes, setYes] = useState(false);
	useEffect(() => {
		let live = true;
		void msweaProjects().then((set) => live && setYes(!!project && set.has(project)));
		return () => {
			live = false;
		};
	}, [project]);
	return yes;
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
					and translated into pi's session format for display.
				</>
			) : (
				<>
					These trajectories were recorded by <span className="text-ink">mini-swe-agent</span>, a bash-only agent harness, not by
					pi, and translated into pi's session format for display. Each model request is shown as a model call; failed or
					superseded requests (e.g. gateway timeouts) appear as errors. Durations are measured by the client; there is no
					time-to-first-token because requests were not streamed. Costs are estimated from the provider's list prices
					(CNY converted to USD). Scores are not shown.
				</>
			)}
		</div>
	);
}
