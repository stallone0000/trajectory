/**
 * trajectory fork: NetBench task pages in the style of Terminal-Bench on Harbor Hub (task list, then per task a header
 * with tags and the run command, and README / Instruction / Files tabs).
 *
 * Reads `data/netbench-tasks-site.json` (scripts/netbench_tasks_export.py). Only public material is in that file:
 * instruction, task.toml and the environment/ build context. Reference solutions and hidden tests are listed as withheld.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { PikaLink as Link } from "../components/PikaLink";
import { CodeBlock } from "../components/code";
import { Markdown } from "../components/Markdown";
import { Icon } from "../components/icons";
import { cx, EmptyState, Page, PageTitle, Pill } from "../components/ui";
import { readBasePath, withBase } from "../lib/base";

interface TaskFile {
	path: string;
	size: number;
	content?: string;
	binary?: boolean;
	withheld?: boolean;
	count?: number;
}
export interface NetbenchTask {
	id: string;
	name: string;
	description: string;
	keywords: string[];
	category: string;
	paper: string;
	conference: string;
	source: string;
	hardware: string;
	resources: { cpus?: number; memory_mb?: number; storage_mb?: number; gpus?: number; network_mode?: string; workdir?: string };
	agentTimeoutSec?: number;
	review: { score?: number; status: string; formal: string };
	readme: string;
	instruction: string;
	files: TaskFile[];
}
interface SiteData {
	benchmark: string;
	tasks: NetbenchTask[];
}

let cached: Promise<SiteData> | undefined;
function useNetbench(): SiteData | null | undefined {
	const [data, setData] = useState<SiteData | null>();
	useEffect(() => {
		cached ??= fetch(withBase(readBasePath(), "data/netbench-tasks-site.json"))
			.then(async (r) => (r.ok ? ((await r.json()) as SiteData) : { benchmark: "NetBench", tasks: [] }))
			.catch(() => ({ benchmark: "NetBench", tasks: [] }));
		let live = true;
		cached.then((d) => live && setData(d));
		return () => {
			live = false;
		};
	}, []);
	return data;
}

const fmtBytes = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
const LANGS: Record<string, string> = { py: "python", sh: "bash", md: "markdown", json: "json", jsonl: "json", toml: "ini", c: "c", h: "c", rs: "rust", go: "go", yaml: "yaml", yml: "yaml" };
const langOf = (path: string) => (path.endsWith("Dockerfile") ? "dockerfile" : LANGS[path.split(".").pop() ?? ""]);
const runCommand = (t: NetbenchTask) => `harbor run -p tasks/${t.id}`;

function Tags({ task }: { task: NetbenchTask }) {
	return (
		<div className="flex flex-wrap gap-1.5">
			<Pill tone="accent">{task.category}</Pill>
			{task.keywords.map((k) => (
				<Pill key={k}>{k}</Pill>
			))}
		</div>
	);
}

export function NetbenchTasksPage() {
	const data = useNetbench();
	const [query, setQuery] = useState("");
	const tasks = useMemo(() => {
		const q = query.trim().toLowerCase();
		return (data?.tasks ?? []).filter((t) => !q || [t.id, t.description, t.paper, ...t.keywords].join(" ").toLowerCase().includes(q));
	}, [data, query]);
	if (data === undefined) return <Page><div role="status" className="text-muted">Loading tasks…</div></Page>;
	return (
		<Page className="pb-16">
			<div className="text-[13px] text-muted">Datasets / netbench</div>
			<PageTitle>netbench / tasks</PageTitle>
			<p className="mt-2 max-w-[760px] text-[14px] leading-[1.6] text-muted">
				Network-research agent tasks synthesised from 2026 networking and security papers. Each task was authored, given an
				independent grader, and reviewed by three separate agents; tasks shown here passed local review. Reference solutions
				and hidden tests are withheld to prevent benchmark contamination.
			</p>
			<div className="mt-6 flex items-center gap-3">
				<input
					value={query}
					onChange={(e) => setQuery(e.target.value)}
					placeholder="Search tasks…"
					aria-label="Search tasks"
					className="h-8 w-72 rounded-sm border border-line bg-page px-2.5 text-[13px] outline-none focus:border-ink"
				/>
				<span className="text-[13px] text-muted">{tasks.length} tasks</span>
			</div>
			{tasks.length === 0 ? (
				<EmptyState title="No tasks match" />
			) : (
				<div className="mt-4 overflow-x-auto">
					<table className="w-full border-collapse text-left text-[13.5px]">
						<thead>
							<tr className="border-b border-line text-[12px] tracking-wide text-muted uppercase">
								<th className="py-2 pr-4 font-medium">Task</th>
								<th className="py-2 pr-4 font-medium">Description</th>
								<th className="py-2 pr-4 font-medium">Tags</th>
								<th className="py-2 pr-0 text-right font-medium" title="Independent reviewer score (0–100)">Review</th>
							</tr>
						</thead>
						<tbody>
							{tasks.map((t) => (
								<tr key={t.id} className="border-b border-line align-top hover:bg-hover">
									<td className="py-3 pr-4 font-medium whitespace-nowrap">
										<Link to={`/tasks/${t.id}`} className="hover:underline">{t.id}</Link>
									</td>
									<td className="py-3 pr-4 leading-[1.5]">
										{t.description}
										<div className="mt-0.5 text-[12px] text-muted">{t.paper} · {t.conference}</div>
									</td>
									<td className="py-3 pr-4"><Tags task={t} /></td>
									<td className="py-3 pr-0 text-right tabular-nums">{t.review.score ?? "—"}</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			)}
		</Page>
	);
}

type Tab = "readme" | "instruction" | "files";
const TABS: { id: Tab; label: string }[] = [
	{ id: "readme", label: "README" },
	{ id: "instruction", label: "Instruction" },
	{ id: "files", label: "Files" },
];

function CopyCommand({ text }: { text: string }) {
	const [done, setDone] = useState(false);
	return (
		<div className="flex max-w-full items-center gap-2 rounded-sm border border-line bg-hover px-3 py-2 font-mono text-[13px]">
			<span className="truncate">{text}</span>
			<button
				type="button"
				aria-label="Copy command"
				className="ml-auto text-muted hover:text-ink"
				onClick={() => {
					void navigator.clipboard?.writeText(text);
					setDone(true);
					setTimeout(() => setDone(false), 1200);
				}}
			>
				<Icon name={done ? "check" : "copy"} size={14} />
			</button>
		</div>
	);
}

function FilesTab({ task }: { task: NetbenchTask }) {
	const first = task.files.find((f) => f.content !== undefined)?.path;
	const [sel, setSel] = useState(first);
	const file = task.files.find((f) => f.path === sel);
	return (
		<div className="grid gap-4 md:grid-cols-[280px_minmax(0,1fr)]">
			<ul className="text-[13px]">
				{task.files.map((f) => (
					<li key={f.path}>
						{f.withheld ? (
							<div className="flex items-center gap-1.5 px-2 py-1 text-muted" title="Withheld to prevent benchmark contamination">
								<Icon name="key" size={13} />
								<span className="truncate">{f.path}</span>
								<span className="ml-auto shrink-0 text-[11.5px]">{f.count} files withheld</span>
							</div>
						) : (
							<button
								type="button"
								onClick={() => setSel(f.path)}
								className={cx("flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left hover:bg-hover", sel === f.path && "bg-hover font-medium")}
							>
								<Icon name="file" size={13} />
								<span className="truncate">{f.path}</span>
								<span className="ml-auto shrink-0 text-[11.5px] text-muted">{fmtBytes(f.size)}</span>
							</button>
						)}
					</li>
				))}
			</ul>
			<div className="min-w-0">
				{file?.content !== undefined ? (
					<>
						<div className="mb-2 font-mono text-[12.5px] text-muted">{file.path}</div>
						<CodeBlock code={file.content} language={langOf(file.path)} maxHeight="70vh" />
					</>
				) : (
					<div className="text-[13px] text-muted">{file ? `${file.path} is a binary or large file (${fmtBytes(file.size)}).` : "Select a file."}</div>
				)}
			</div>
		</div>
	);
}

function Facts({ task }: { task: NetbenchTask }) {
	const r = task.resources;
	const rows: [string, string][] = [
		["Paper", `${task.paper} (${task.conference})`],
		["Hardware", task.hardware],
		["Resources", `${r.cpus ?? "?"} CPU · ${r.memory_mb ?? "?"} MiB RAM · ${r.storage_mb ?? "?"} MiB disk · ${r.gpus ?? 0} GPU · ${r.network_mode ?? ""}`],
		["Agent timeout", task.agentTimeoutSec ? `${Math.round(task.agentTimeoutSec / 60)} min` : "—"],
		["Review", `${task.review.score ?? "—"}/100 · ${task.review.status} · ${task.review.formal}`],
	];
	return (
		<dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
			{rows.map(([k, v]) => (
				<div key={k} className="contents">
					<dt className="text-muted">{k}</dt>
					<dd className="min-w-0 break-words">{v}</dd>
				</div>
			))}
			{task.source && (
				<div className="contents">
					<dt className="text-muted">Source</dt>
					<dd className="min-w-0 truncate"><a href={task.source} target="_blank" rel="noreferrer noopener" className="underline">{task.source}</a></dd>
				</div>
			)}
		</dl>
	);
}

export function NetbenchTaskPage() {
	const { id } = useParams();
	const data = useNetbench();
	const [params, setParams] = useSearchParams();
	const tab = (params.get("tab") as Tab) || "readme";
	const task = data?.tasks.find((t) => t.id === id);
	if (data === undefined) return <Page><div role="status" className="text-muted">Loading task…</div></Page>;
	if (!task) return <Page><EmptyState title="Task not found"><Link to="/tasks" className="underline">All tasks</Link></EmptyState></Page>;
	return (
		<Page className="pb-16">
			<div className="text-[13px] text-muted">
				<Link to="/tasks" className="hover:underline">Tasks</Link> / netbench / {task.id}
			</div>
			<PageTitle>netbench / {task.id}</PageTitle>
			<p className="mt-2 max-w-[820px] text-[15px] leading-[1.55]">{task.description}</p>
			<div className="mt-3"><Tags task={task} /></div>
			<div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
				<CopyCommand text={runCommand(task)} />
			</div>
			<div className="mt-5"><Facts task={task} /></div>
			<div role="tablist" className="mt-7 flex gap-5 border-b border-line text-[14px]">
				{TABS.map((t) => (
					<button
						key={t.id}
						role="tab"
						type="button"
						aria-selected={tab === t.id}
						onClick={() => setParams(t.id === "readme" ? {} : { tab: t.id }, { replace: true })}
						className={cx("-mb-px border-b-2 pb-2", tab === t.id ? "border-ink font-medium" : "border-transparent text-muted hover:text-ink")}
					>
						{t.label}
					</button>
				))}
			</div>
			<div className="mt-5">
				{tab === "readme" && (task.readme ? <Markdown text={task.readme} /> : <EmptyState title="No README" />)}
				{tab === "instruction" && (
					<>
						<div className="mb-2 font-mono text-[12.5px] text-muted">instruction.md</div>
						<Markdown text={task.instruction} />
					</>
				)}
				{tab === "files" && <FilesTab task={task} />}
			</div>
		</Page>
	);
}
