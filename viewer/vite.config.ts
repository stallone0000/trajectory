/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import type { Plugin } from "vite";

/** The static trajectory site has no /docs pages; give the docs module an empty body. */
function docsContent(): Plugin {
	const id = "virtual:pi-docs";
	return { name: "pi-docs-stub", resolveId: (s) => (s === id ? `\0${id}` : undefined), load: (s) => (s === `\0${id}` ? "export default { pages: [], groups: [] };" : undefined) };
}

export default defineConfig(({ mode }) => ({
	base: "./",
	plugins: [docsContent(), react(), tailwindcss()],
	server: {
		// Herder worktrees live under `.git/`, which Vite's default deny list blocks for test modules.
		// Tests also read the logo's source of truth, `../resource/pika-icon.svg`.
		...(mode === "test" ? { fs: { deny: [".env", ".env.*", "*.{crt,pem}"], allow: [".", "../resource"] } } : {}),
		proxy: {
			"/api": "http://127.0.0.1:7171",
		},
	},
	build: {
		outDir: "../site-build",
		emptyOutDir: true,
		chunkSizeWarningLimit: 700,
		// Minified builds drop license comments unless asked; keep them, such as the model marks' MIT notice.
		rolldownOptions: { output: { comments: { legal: true } } },
	},
	test: {
		environment: "jsdom",
		setupFiles: ["tests/setup.ts"],
		include: ["tests/**/*.test.{ts,tsx}"],
		css: false,
	},
}));
