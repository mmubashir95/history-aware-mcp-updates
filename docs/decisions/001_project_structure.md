# ADR 001: Adopt a modular, configuration-driven ML research layout

## Status

Accepted — 2026-11-24.

## Context

The thesis requires traceable data preparation, annotation, model comparison,
and reproducible research results. A single scripts directory becomes hard to
test and obscures data provenance as the project grows.

## Decision

Use a `src` package layout with thin pipeline entry points, lifecycle-based
data directories, versioned configuration, pytest tests, and research
documentation. Add implementation only when its phase begins.

## Consequences

The layout creates clear ownership and auditability. It also requires moving
validated exploratory logic into named modules and retaining manifests rather
than committing large datasets or generated artifacts.
