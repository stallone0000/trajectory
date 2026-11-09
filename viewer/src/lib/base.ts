/** Normalizes a base path to "/" or "/prefix" without a trailing slash. */
export function normalizeBase(value: string | null | undefined): string {
	const trimmed = (value ?? "").trim();
	if (!trimmed) return "/";
	const withLead = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
	const stripped = withLead.replace(/\/+$/, "");
	return stripped === "" ? "/" : stripped;
}

/** Reads the base path the server injects as `<meta name="pika-base">`. */
export function readBasePath(doc: Document = document): string {
	const meta = doc.querySelector('meta[name="pika-base"]');
	if (meta) return normalizeBase(meta.getAttribute("content"));
	const path = doc.defaultView?.location.pathname ?? "/";
	return normalizeBase(path.replace(/\/(s|runs|herder|search|login|public|settings|devices|active|docs|statistics)(\/.*)?$/, "").replace(/\/index\.html$/, ""));
}

/** Joins the base path and a path relative to it. */
export function withBase(base: string, path: string): string {
	const rel = path.replace(/^\/+/, "");
	return base === "/" ? `/${rel}` : `${base}/${rel}`;
}
