# examples/

Committed reference outputs from running the analyzer against the golden
fixtures. Regenerate with the CLI when the schema or rules change.

## Files

| File | Role |
|---|---|
| `analysis.json` | Golden JSON output for `full-stack-fastapi` (compose stack) |
| `report.md` | Workload-centric Markdown report for `full-stack-fastapi` |
| `jpetstore-analysis.json` | Golden JSON output for `jpetstore-6` (Maven WAR / external servlet container) |
| `jpetstore-report.md` | Workload-centric Markdown report for `jpetstore-6` |
| `spring-petclinic-analysis.json` | Golden JSON output for `spring-petclinic` (Spring Boot + Gradle; generated with `--build-system gradle`) |
| `spring-petclinic-report.md` | Workload-centric Markdown report for `spring-petclinic` |
