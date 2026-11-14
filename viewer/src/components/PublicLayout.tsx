import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { ApiContext, ApiError, useApi } from "../lib/api";
import { inGuestView, setGuestView } from "../lib/guestView";
import { useTheme } from "../lib/theme";
import { Icon } from "./icons";
import { useVisitorView } from "./useVisitorView";
import { STATIC_SITE } from "../lib/staticApi";
import { useMsweaData } from "../lib/mswea";
import { BAND_CONTROL, BAND_NAV, BAND_NAV_END, BandSearch, NavItem, ScrollRootContext, SignBand, ThemeToggle, useBandSearchShortcut } from "./Layout";

/** Anonymous pages have their own client and cache, even when the browser is also signed in. */
export function PublicLayout() {
	const ownerApi = useApi();
	const [api] = useState(() => ownerApi.forPublic());
	const [queryClient] = useState(() => new QueryClient({
		defaultOptions: { queries: {
			staleTime: 0,
			gcTime: 0,
			refetchOnWindowFocus: true,
			retry: (failures, error) => failures < 1 && !(error instanceof ApiError && error.status < 500),
		} },
	}));
	const [scrollRoot, setScrollRoot] = useState<HTMLElement | null>(null);
	const { theme, toggle } = useTheme();
	// Signing in opens the owner's view of this page; a browser that is already signed in goes straight there, which is
	// also the way out of the owner's guest view.
	const location = useLocation();
	const ownerPage = (location.pathname.replace(/^\/public(?=\/|$)/, "") || "/") + location.search;
	const [guestView] = useState(inGuestView);
	useVisitorView(api, location, guestView);
	const searchRef = useRef<HTMLInputElement>(null);
	// As in the owner's band, `/` goes to search.
	useBandSearchShortcut("/public/search", searchRef);
	// trajectory fork: a session page belongs to "Benchmark trajectory" when the session came from mini-swe-agent and
	// to "Public trajectories" otherwise. Until the list of those sessions loads, neither tab claims it, so the band
	// does not flash the wrong one.
	const mswea = useMsweaData();
	const sessionId = /^\/public\/s\/([^/]+)/.exec(location.pathname)?.[1];
	const sessionTab = sessionId === undefined || !mswea ? undefined : mswea.sessions.has(safeDecode(sessionId)) ? "mswea" : "public";
	return (
		<ApiContext.Provider value={api}>
			<QueryClientProvider client={queryClient}>
				<div className="flex h-full flex-col bg-page text-ink">
					<SignBand
						home="/public"
						controls={
							<>
								<ThemeToggle theme={theme} onToggle={toggle} />
								{!STATIC_SITE && <Link to={`/login?next=${encodeURIComponent(ownerPage)}`} onClick={() => setGuestView(false)} className={BAND_CONTROL}>
									{guestView ? (
										<>
											<Icon name="eye" size={15} />
											Exit guest view
										</>
									) : (
										"Sign in"
									)}
								</Link>}
							</>
						}
					>
						<nav className={BAND_NAV} aria-label="Public">
							<NavItem to="/public" icon="sessions" end within={sessionTab === "public" ? ["/public/s/"] : undefined}>
								Public trajectories
							</NavItem>
							<NavItem to="/public/benchmark" icon="statistics">Benchmark</NavItem>
							<NavItem to="/public/tasks" icon="file">Tasks</NavItem>
							<NavItem to="/public/mswea" icon="sessions" within={sessionTab === "mswea" ? ["/public/s/"] : undefined}>
								Benchmark trajectory
							</NavItem>
							<NavItem to="/public/statistics" icon="statistics">Statistics</NavItem>
							{!STATIC_SITE && <NavItem to="/docs" icon="file">Documentation</NavItem>}
							<div className={BAND_NAV_END}>
								<BandSearch path="/public/search" label="Search published trajectories" inputRef={searchRef} />
							</div>
						</nav>
					</SignBand>
					<main ref={setScrollRoot} className="relative min-h-0 min-w-0 flex-1 overflow-y-auto" data-scroll-root="">
						<ScrollRootContext.Provider value={scrollRoot}><Outlet /></ScrollRootContext.Provider>
					</main>
				</div>
			</QueryClientProvider>
		</ApiContext.Provider>
	);
}

function safeDecode(value: string): string {
	try {
		return decodeURIComponent(value);
	} catch {
		return value;
	}
}
