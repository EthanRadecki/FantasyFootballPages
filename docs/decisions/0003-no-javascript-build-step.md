# 0003: No JavaScript build step

Date: 2026-09-28. Status: accepted.

## Context
The site is vanilla HTML, CSS, and JS on GitHub Pages. A bundler (Vite, webpack) would add tooling and a Node dependency.

## Decision
Use native ES modules served as static files. The Python `engine build` command is the only build step: it assembles the web template, generated data, config, and editorial content into `dist/`.

## Consequences
Anyone can read and edit the frontend without Node. If the frontend later needs TypeScript or bundling, this decision is revisited.
