/**
 * trajectory fork: benchmark leaderboard for trajectories translated from mini-swe-agent.
 *
 * Reads `data/mswea-projects.json` (scripts/mswea_import.py): per session its task, model, verifier verdict, and
 * figures. Models are ranked by tasks solved; ties go to the shorter trajectories (fewer model calls per task on
 * average). The task × model grid uses status colour plus a ✓/✗ glyph (never colour alone), validated for colour-vision
 * deficiency in light and dark mode.
 */
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { PikaLink as Link } from "../components/PikaLink";
import { ModelName } from "../components/ModelName";
import { cx, EmptyState, Page, PageTitle } from "../components/ui";
import { formatCost, formatCount, formatDuration } from "../lib/format";
import { useMsweaData, type MsweaSession } from "../lib/mswea";

const PASS_CELL = "bg-[#0f9480] dark:bg-[#1aa898]";
const FAIL_CELL = "bg-[#d52b1e] dark:bg-[#ef5a4c]";

interface Cell extends MsweaSession {
	id: string;
}
interface Row {
	model: string;
	name: string;
	solved: number;
	total: number;
	avgSteps: number;
	avgTokens: number;
	avgDuration: number;
	cost: number;
	cells: Map<string, Cell>;
}

const bare = (model: string) => model.split("/").pop() ?? model;
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

export function BenchmarkPage() {
	const data = useMsweaData();
	const [params, setParams] = useSearchParams();
	const [hover, setHover] = useState<Cell>();

	const projects = useMemo(() => {
		const count = new Map<string, number>();
		const tasks = new Map<string, Set<string>>();
		for (const s of data?.sessions.values() ?? []) {
			if (!s.project) continue;
			count.set(s.project, (count.get(s.project) ?? 0) + 1);
			tasks.set(s.project, (tasks.get(s.project) ?? new Set()).add(s.task));
		}
		// A benchmark is a project that covers several tasks; single-task trial projects stay on the trajectory list.
		return [...count.entries()].filter(([p]) => (tasks.get(p)?.size ?? 0) >= 4).sort((a, b) => b[1] - a[1]).map(([p]) => p);
	}, [data]);
	const project = params.get("project") ?? projects[0];

	const { rows, tasks, perTask } = useMemo(() => {
		const cells = [...(data?.sessions.entries() ?? [])].filter(([, s]) => s.project === project).map(([id, s]) => ({ ...s, id }));
		const tasks = [...new Set(cells.map((c) => c.task))].sort();
		const byModel = new Map<string, Cell[]>();
		for (const c of cells) byModel.set(c.model, [...(byModel.get(c.model) ?? []), c]);
		const rows: Row[] = [...byModel.entries()].map(([model, list]) => ({
			model,
			name: bare(model),
			solved: list.filter((c) => c.verdict === "pass").length,
			total: list.length,
			avgSteps: mean(list.map((c) => c.steps ?? 0)),
			avgTokens: mean(list.map((c) => c.tokens ?? 0)),
			avgDuration: mean(list.map((c) => c.durationMs ?? 0)),
			cost: list.reduce((a, c) => a + (c.cost ?? 0), 0),
			cells: new Map(list.map((c) => [c.task, c])),
		}));
		// Most tasks solved first; equal scores go to the shorter trajectories.
		rows.sort((a, b) => b.solved - a.solved || a.avgSteps - b.avgSteps || a.name.localeCompare(b.name));
		const perTask = new Map(tasks.map((t) => [t, cells.filter((c) => c.task === t && c.verdict === "pass").length]));
		return { rows, tasks, perTask };
	}, [data, project]);

	if (data && !rows.length) {
		return (
			<Page className="pb-24">
				<PageTitle>Benchmark</PageTitle>
				<EmptyState title="No benchmark results">No translated benchmark runs are published yet.</EmptyState>
			</Page>
		);
	}
	const trajectories = rows.reduce((a, r) => a + r.total, 0);
	const solved = rows.reduce((a, r) => a + r.solved, 0);
	const brief = (task: string) => data?.tasks.get(task);

	return (
		<Page className="pb-24">
			<PageTitle>Benchmark</PageTitle>
			<p className="mt-3 max-w-[860px] text-[14px] leading-[1.6] text-muted">
				<span className="text-ink">{project}</span>: {tasks.length} networking tasks, each attempted once by every model with the
				mini-swe-agent harness and checked by a hidden verifier. Models are ranked by tasks solved; models with the same
				score are ordered by trajectory length (fewer model calls per task first). Runs that ended without a gradable
				submission count as not solved.
			</p>
			{projects.length > 1 && (
				<div className="mt-4 flex flex-wrap gap-1.5 text-[13px]" role="group" aria-label="Benchmark">
					{projects.map((p) => (
						<button
							key={p}
							type="button"
							onClick={() => setParams({ project: p }, { replace: true })}
							className={cx("h-7 rounded-sm border px-2.5", p === project ? "border-ink bg-ink text-page" : "border-line hover:bg-hover")}
						>
							{p}
						</button>
					))}
				</div>
			)}

			{/* Headline figures */}
			<dl className="mt-7 grid grid-cols-4 border-y border-line max-md:grid-cols-2" data-benchmark-kpis="">
				{[
					["Models", String(rows.length)],
					["Tasks", String(tasks.length)],
					["Trajectories", String(trajectories)],
					["Solved overall", trajectories ? `${Math.round((100 * solved) / trajectories)}%` : "–"],
				].map(([label, value], i) => (
					<div key={label} className={cx("px-5 py-4", i > 0 && "border-l border-line max-md:[&:nth-child(3)]:border-l-0")}>
						<dd className="text-[26px] leading-none font-semibold tracking-[-0.02em]">{value}</dd>
						<dt className="mt-1.5 text-[12.5px] text-muted">{label}</dt>
					</div>
				))}
			</dl>

			{/* Leaderboard */}
			<h2 className="mt-10 text-[17px] font-semibold tracking-[-0.01em]">Leaderboard</h2>
			<div className="mt-3 overflow-x-auto">
				<table className="w-full min-w-[760px] border-collapse text-[13.5px]" data-leaderboard="">
					<thead>
						<tr className="h-8 border-b border-ink text-left text-[12px] font-medium text-muted">
							<th className="w-10 pl-1.5 font-medium">#</th>
							<th className="font-medium">Model</th>
							<th className="w-[260px] font-medium">Solved</th>
							<th className="text-right font-medium" title="Model calls per task that produced an answer (trajectory length)">
								Avg steps
							</th>
							<th className="text-right font-medium">Avg tokens</th>
							<th className="text-right font-medium">Avg time</th>
							<th className="pr-2 text-right font-medium" title="Estimated from list prices">
								Total cost
							</th>
						</tr>
					</thead>
					<tbody>
						{rows.map((r, i) => {
							const rank = i === 0 || rows[i - 1].solved !== r.solved || rows[i - 1].avgSteps !== r.avgSteps ? i + 1 : undefined;
							return (
								<tr key={r.model} className="h-12 border-b border-line hover:bg-hover" data-leader={r.name}>
									<td className="pl-1.5 text-[15px] font-semibold tabular-nums">{rank ?? ""}</td>
									<td>
										<Link
											to={`/mswea?project=${encodeURIComponent(project ?? "")}&model=${encodeURIComponent(r.name)}`}
											className="inline-flex min-w-0 items-center gap-1.5 font-medium hover:underline"
											title={`Open ${r.name}'s trajectories`}
										>
											<ModelName model={r.name} />
										</Link>
									</td>
									<td>
										<div className="flex items-center gap-3">
											<span className="w-[62px] shrink-0 tabular-nums">
												<span className="font-semibold">{r.solved}</span>
												<span className="text-muted">/{r.total}</span>
											</span>
											<span className="relative h-1.5 flex-1 rounded-full bg-line" aria-hidden="true">
												<span
													className="absolute inset-y-0 left-0 rounded-full bg-ink"
													style={{ width: `${r.total ? (100 * r.solved) / r.total : 0}%` }}
												/>
											</span>
											<span className="w-10 shrink-0 text-right text-muted tabular-nums">
												{r.total ? Math.round((100 * r.solved) / r.total) : 0}%
											</span>
										</div>
									</td>
									<td className="text-right tabular-nums">{r.avgSteps.toFixed(1)}</td>
									<td className="text-right tabular-nums">{formatCount(r.avgTokens)}</td>
									<td className="text-right tabular-nums">{formatDuration(r.avgDuration)}</td>
									<td className="pr-2 text-right tabular-nums">{formatCost(r.cost)}</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>

			{/* Task × model results */}
			<div className="mt-12 flex flex-wrap items-end justify-between gap-3">
				<h2 className="text-[17px] font-semibold tracking-[-0.01em]">Results by task</h2>
				<div className="flex items-center gap-4 text-[12.5px] text-muted" aria-label="Legend">
					<span className="inline-flex items-center gap-1.5">
						<span className={cx("inline-flex size-4 items-center justify-center rounded-[4px] text-[10px] font-bold text-white", PASS_CELL)}>✓</span>
						Passed
					</span>
					<span className="inline-flex items-center gap-1.5">
						<span className={cx("inline-flex size-4 items-center justify-center rounded-[4px] text-[10px] font-bold text-white", FAIL_CELL)}>✗</span>
						Failed
					</span>
				</div>
			</div>
			<div className="mt-3 overflow-x-auto" onMouseLeave={() => setHover(undefined)}>
				<table className="table-fixed border-separate border-spacing-[3px] pr-16 text-[12.5px]" data-results-grid="">
					<thead>
						<tr>
							<th className="min-w-[190px]" />
							{tasks.map((t) => (
								<th key={t} className="relative h-[150px] w-8 min-w-8 max-w-8 p-0 align-bottom font-normal" title={brief(t) ? `${t}: ${brief(t)}` : t}>
									{/* Rotated labels take no column width: every column stays one cell wide. */}
									<span className="absolute bottom-1.5 left-[15px] origin-bottom-left -rotate-55 whitespace-nowrap text-muted">{t}</span>
								</th>
							))}
							<th className="pl-3 text-left align-bottom text-[12px] font-medium text-muted">Solved</th>
						</tr>
					</thead>
					<tbody>
						{rows.map((r) => (
							<tr key={r.model}>
								<td className="pr-3">
									<ModelName model={r.name} />
								</td>
								{tasks.map((t) => {
									const c = r.cells.get(t);
									if (!c) return <td key={t} className="size-8 rounded-[4px] bg-soft" title={`${t} · ${r.name}: no run`} />;
									const pass = c.verdict === "pass";
									const label = `${t} · ${r.name}: ${pass ? "Passed" : "Failed"}${c.steps !== undefined ? ` · ${c.steps} steps` : ""}`;
									return (
										<td key={t} className="size-8 p-0">
											<Link
												to={`/s/${encodeURIComponent(c.id)}`}
												aria-label={label}
												title={label}
												onMouseEnter={() => setHover(c)}
												onFocus={() => setHover(c)}
												className={cx(
													"flex size-8 items-center justify-center rounded-[4px] text-[13px] font-bold text-white outline-offset-2 hover:opacity-85 focus-visible:outline-2 focus-visible:outline-ink",
													pass ? PASS_CELL : FAIL_CELL,
													hover?.id === c.id && "ring-2 ring-ink ring-offset-2 ring-offset-page",
												)}
											>
												{pass ? "✓" : "✗"}
											</Link>
										</td>
									);
								})}
								<td className="pl-3 font-semibold tabular-nums">
									{r.solved}
									<span className="font-normal text-muted">/{r.total}</span>
								</td>
							</tr>
						))}
						<tr>
							<td className="pt-1.5 pr-3 text-[12px] font-medium text-muted">Models solving</td>
							{tasks.map((t) => (
								<td key={t} className="pt-1.5 text-center text-[12px] text-muted tabular-nums" title={`${t}: ${perTask.get(t)} of ${rows.length} models`}>
									{perTask.get(t)}
								</td>
							))}
							<td />
						</tr>
					</tbody>
				</table>
			</div>
			{/* Readout of the hovered or focused cell; every figure is also on the trajectory page. */}
			<div className="mt-3 min-h-[44px] rounded-md border border-line bg-soft px-3.5 py-2.5 text-[13px] leading-[1.5] text-muted" aria-live="polite" data-grid-readout="">
				{hover ? (
					<>
						<span className="font-medium text-ink">{hover.task}</span> · {bare(hover.model)} ·{" "}
						<span className={cx("font-medium", hover.verdict === "pass" ? "text-[#0b7a6a] dark:text-[#5fd3c4]" : "text-red")}>
							{hover.verdict === "pass" ? "Passed" : "Failed"}
						</span>
						{hover.steps !== undefined && ` · ${hover.steps} steps`}
						{hover.tokens !== undefined && ` · ${formatCount(hover.tokens)} tokens`}
						{hover.durationMs !== undefined && ` · ${formatDuration(hover.durationMs)}`}
						{hover.cost !== undefined && ` · ${formatCost(hover.cost)}`}
						{hover.detail && <span> · {hover.detail}</span>}
						{brief(hover.task) && <div className="mt-0.5">{brief(hover.task)}</div>}
					</>
				) : (
					"Hover or focus a cell to see that trajectory's figures; click it to open the trajectory."
				)}
			</div>
		</Page>
	);
}
