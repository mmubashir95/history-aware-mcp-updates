# Repository guidance

- Keep raw data immutable and do not commit large datasets, credentials, or generated model artifacts.
- Put reusable logic in `src/mcp_history_security`; keep `pipelines/` as thin orchestration layers.
- Add tests with every implemented pipeline stage.
- Update the relevant manifest and methodology document when data contracts change.
